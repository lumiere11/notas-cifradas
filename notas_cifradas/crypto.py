"""Formato de la bóveda y primitivas criptográficas.

Esquema:  contraseña ─NFKC/UTF-8→ Argon2id ─→ clave de 256 bits ─→ AES-256-GCM

Archivo en disco (todo big-endian):

    magic      7 B   b"NCVAULT"
    versión    1 B   1
    kdf        1 B   1 = Argon2id
    memoria    4 B   KiB
    iteraciones 4 B
    lanes      1 B
    sal       32 B   aleatoria
    nonce     12 B   aleatorio, nuevo en cada guardado
    ciphertext ...   AES-256-GCM(relleno(datos)) + etiqueta de 16 B

Toda la cabecera se autentica como AAD: si alguien cambia los parámetros del
KDF (p. ej. para rebajar el coste) el descifrado falla.
"""
from __future__ import annotations

import os
import struct
import unicodedata
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
except ImportError as exc:  # pragma: no cover - depende de la instalación
    raise ImportError(
        "Se necesita python-cryptography >= 44 (con Argon2id). "
        "En CachyOS: sudo pacman -Syu python-cryptography"
    ) from exc

MAGIC = b"NCVAULT"
VERSION = 1
KDF_ARGON2ID = 1
SALT_LEN = 32
NONCE_LEN = 12
KEY_LEN = 32  # AES-256
TAG_LEN = 16
PAD_BLOCK = 4096  # el tamaño del archivo solo revela el tamaño "redondeado"

_FIXED = struct.Struct(">7sBBIIB")
HEADER_LEN = _FIXED.size + SALT_LEN + NONCE_LEN

# Topes al leer un archivo, para que uno malicioso no pueda pedir gigas de RAM.
_MAX_MEMORY_KIB = 1 << 20  # 1 GiB
_MAX_ITERATIONS = 16
_MAX_LANES = 16


class VaultError(Exception):
    """Error genérico de la bóveda."""


class WrongPasswordError(VaultError):
    """Contraseña incorrecta (o archivo manipulado: GCM no distingue ambos)."""


class CorruptVaultError(VaultError):
    """El archivo no tiene el formato esperado."""


@dataclass(frozen=True)
class KdfParams:
    memory_kib: int
    iterations: int
    lanes: int

    def validate(self) -> None:
        if not (1 <= self.lanes <= _MAX_LANES):
            raise CorruptVaultError("Parámetro 'lanes' fuera de rango")
        if not (1 <= self.iterations <= _MAX_ITERATIONS):
            raise CorruptVaultError("Parámetro 'iteraciones' fuera de rango")
        if not (8 * self.lanes <= self.memory_kib <= _MAX_MEMORY_KIB):
            raise CorruptVaultError("Parámetro 'memoria' fuera de rango")


# 512 MiB · 3 pasadas · 4 lanes: ~1 s en un PC de escritorio actual.
DEFAULT_KDF = KdfParams(memory_kib=512 * 1024, iterations=3, lanes=4)


def derive_key(password: str, salt: bytes, params: KdfParams) -> bytearray:
    """Contraseña → clave de 256 bits con Argon2id."""
    params.validate()
    secret = unicodedata.normalize("NFKC", password).encode("utf-8")
    try:
        kdf = Argon2id(
            salt=salt,
            length=KEY_LEN,
            iterations=params.iterations,
            lanes=params.lanes,
            memory_cost=params.memory_kib,
        )
        return bytearray(kdf.derive(secret))
    except UnsupportedAlgorithm as exc:  # OpenSSL sin Argon2
        raise VaultError("Tu OpenSSL no soporta Argon2id (necesita >= 3.2)") from exc


def new_salt() -> bytes:
    return os.urandom(SALT_LEN)


def _pack_header(params: KdfParams, salt: bytes, nonce: bytes) -> bytes:
    return (
        _FIXED.pack(
            MAGIC, VERSION, KDF_ARGON2ID, params.memory_kib, params.iterations, params.lanes
        )
        + salt
        + nonce
    )


def _pad(data: bytes) -> bytes:
    body = struct.pack(">I", len(data)) + data
    return body + b"\0" * (-len(body) % PAD_BLOCK)


def _unpad(buf: bytes) -> bytes:
    if len(buf) < 4:
        raise CorruptVaultError("Contenido demasiado corto")
    (n,) = struct.unpack(">I", buf[:4])
    if n > len(buf) - 4:
        raise CorruptVaultError("Longitud interna inválida")
    return buf[4 : 4 + n]


def seal(plaintext: bytes, key: bytes, salt: bytes, params: KdfParams) -> bytes:
    """Cifra con AES-256-GCM usando un nonce nuevo. Devuelve el archivo completo."""
    if len(key) != KEY_LEN:
        raise ValueError("La clave debe tener 32 bytes")
    nonce = os.urandom(NONCE_LEN)
    header = _pack_header(params, salt, nonce)
    return header + AESGCM(bytes(key)).encrypt(nonce, _pad(plaintext), header)


@dataclass
class Opened:
    plaintext: bytes
    key: bytearray
    salt: bytes
    params: KdfParams


def parse_header(blob: bytes) -> tuple[KdfParams, bytes, bytes]:
    if len(blob) < HEADER_LEN + TAG_LEN:
        raise CorruptVaultError("Archivo demasiado corto")
    magic, version, kdf, mem, iters, lanes = _FIXED.unpack_from(blob)
    if magic != MAGIC:
        raise CorruptVaultError("No es una bóveda de Notas Cifradas")
    if version != VERSION:
        raise CorruptVaultError(f"Versión de formato no soportada: {version}")
    if kdf != KDF_ARGON2ID:
        raise CorruptVaultError(f"KDF no soportado: {kdf}")
    params = KdfParams(mem, iters, lanes)
    params.validate()
    off = _FIXED.size
    return params, blob[off : off + SALT_LEN], blob[off + SALT_LEN : HEADER_LEN]


def open_blob(blob: bytes, password: str) -> Opened:
    """Deriva la clave y descifra. Lanza WrongPasswordError si GCM no valida."""
    params, salt, nonce = parse_header(blob)
    key = derive_key(password, salt, params)
    try:
        padded = AESGCM(bytes(key)).decrypt(nonce, blob[HEADER_LEN:], blob[:HEADER_LEN])
    except InvalidTag:
        wipe(key)
        raise WrongPasswordError("Contraseña incorrecta o archivo dañado") from None
    return Opened(_unpad(padded), key, salt, params)


def wipe(buf: bytearray | None) -> None:
    """Sobrescribe con ceros nuestra copia de la clave (mejor esfuerzo)."""
    if buf is not None:
        for i in range(len(buf)):
            buf[i] = 0
