"""Modelo de notas y persistencia cifrada en un único archivo."""
from __future__ import annotations

import fcntl
import hmac
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import crypto
from .crypto import KdfParams, VaultError

DATA_VERSION = 1


def default_vault_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "notas-cifradas" / "vault.ncv"


@dataclass
class Note:
    title: str = ""
    body: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)


class VaultLockedError(VaultError):
    pass


class VaultBusyError(VaultError):
    """Otra instancia tiene la bóveda abierta."""


class Vault:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.notes: dict[str, Note] = {}
        self._key: bytearray | None = None
        self._salt = b""
        self._params: KdfParams | None = None
        self._lock_fd: int | None = None
        self._backed_up = False

    # ── estado ────────────────────────────────────────────────────────────
    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    @property
    def _backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")

    # ── ciclo de vida ────────────────────────────────────────────────────
    def create(self, password: str, params: KdfParams = crypto.DEFAULT_KDF) -> None:
        if self.exists:
            raise VaultError("Ya existe una bóveda en esa ruta")
        self._acquire_lock()
        try:
            self._salt = crypto.new_salt()
            self._params = params
            self._key = crypto.derive_key(password, self._salt, params)
            self.notes = {}
            self._backed_up = True  # nada que respaldar todavía
            self.save()
        except BaseException:
            self.lock()
            raise

    def unlock(self, password: str) -> None:
        if self.unlocked:
            return
        self._acquire_lock()
        try:
            opened = crypto.open_blob(self.path.read_bytes(), password)
            self._key, self._salt, self._params = opened.key, opened.salt, opened.params
            self.notes = self._decode(opened.plaintext)
            self._backed_up = False
        except BaseException:
            self.lock()
            raise

    def lock(self) -> None:
        crypto.wipe(self._key)
        self._key = None
        self.notes = {}
        self._release_lock()

    def verify_password(self, password: str) -> bool:
        self._require_unlocked()
        candidate = crypto.derive_key(password, self._salt, self._params)
        try:
            return hmac.compare_digest(bytes(candidate), bytes(self._key))
        finally:
            crypto.wipe(candidate)

    def change_password(self, new_password: str, params: KdfParams | None = None) -> None:
        self._require_unlocked()
        old = (self._key, self._salt, self._params)
        new_params = params or self._params
        salt = crypto.new_salt()
        key = crypto.derive_key(new_password, salt, new_params)
        self._key, self._salt, self._params = key, salt, new_params
        try:
            self.save()
        except BaseException:
            crypto.wipe(key)
            self._key, self._salt, self._params = old
            raise
        crypto.wipe(old[0])
        # La copia de seguridad sigue cifrada con la contraseña antigua: se borra.
        self._backup_path.unlink(missing_ok=True)
        self._backed_up = True

    # ── notas ─────────────────────────────────────────────────────────────
    def add_note(self, title: str = "", body: str = "") -> Note:
        self._require_unlocked()
        note = Note(title=title, body=body)
        self.notes[note.id] = note
        return note

    def delete_note(self, note_id: str) -> None:
        self._require_unlocked()
        self.notes.pop(note_id, None)

    def sorted_notes(self) -> list[Note]:
        return sorted(self.notes.values(), key=lambda n: n.modified, reverse=True)

    # ── persistencia ──────────────────────────────────────────────────────
    def save(self) -> None:
        self._require_unlocked()
        payload = json.dumps(
            {"version": DATA_VERSION, "notes": [asdict(n) for n in self.notes.values()]},
            ensure_ascii=False,
        ).encode("utf-8")
        blob = crypto.seal(payload, self._key, self._salt, self._params)
        self._atomic_write(blob)

    @staticmethod
    def _decode(plaintext: bytes) -> dict[str, Note]:
        try:
            data = json.loads(plaintext.decode("utf-8"))
            return {n["id"]: Note(**n) for n in data["notes"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise crypto.CorruptVaultError("Contenido descifrado ilegible") from exc

    def _atomic_write(self, blob: bytes) -> None:
        directory = self.path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".vault-", suffix=".tmp")  # 0600
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
                fh.flush()
                os.fsync(fh.fileno())
            if not self._backed_up and self.path.exists():
                self._write_backup()
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    def _write_backup(self) -> None:
        """Una copia del estado al abrir la sesión, para recuperar borrados accidentales."""
        fd = os.open(self._backup_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.path.read_bytes())
            fh.flush()
            os.fsync(fh.fileno())
        self._backed_up = True

    # ── bloqueo de instancia única ────────────────────────────────────────
    def _acquire_lock(self) -> None:
        if self._lock_fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path.with_name(self.path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise VaultBusyError("La bóveda ya está abierta en otra ventana") from None
        self._lock_fd = fd

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)  # cerrar el fd libera el flock
            self._lock_fd = None

    def _require_unlocked(self) -> None:
        if not self.unlocked:
            raise VaultLockedError("La bóveda está bloqueada")
