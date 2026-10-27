"""Punto de entrada: endurecimiento del proceso + arranque de Qt."""
from __future__ import annotations

import argparse
import ctypes
import os
import resource
import sys
from pathlib import Path

PR_SET_DUMPABLE = 4


def harden_process() -> None:
    """Sin volcados de memoria y sin que otros procesos del mismo usuario
    puedan leer nuestra memoria con ptrace o /proc/PID/mem.
    Desactivable con NOTAS_NO_HARDEN=1 si interfiere con algo de tu entorno.

    En Flatpak solo se desactivan los core dumps: el sandbox ya aísla el proceso, y con
    PR_SET_DUMPABLE=0 los portales de escritorio no pueden identificar a la aplicación."""
    if os.environ.get("NOTAS_NO_HARDEN"):
        return
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if not os.environ.get("FLATPAK_ID"):
            ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
    except (OSError, ValueError, AttributeError):
        pass


def selftest() -> int:
    """Comprueba que todo lo necesario está disponible y dice de dónde sale (útil en el bundle)."""
    import platform
    import tempfile

    failures = 0

    def check(label: str, fn) -> None:
        nonlocal failures
        try:
            print(f"  ok   {label}: {fn()}")
        except Exception as exc:  # noqa: BLE001 - es un diagnóstico
            failures += 1
            print(f"  FAIL {label}: {type(exc).__name__}: {exc}")

    print(f"Python {platform.python_version()} · empaquetado: {getattr(sys, 'frozen', False)}")

    def crypto_roundtrip() -> str:
        import cryptography
        from cryptography.hazmat.backends.openssl.backend import backend

        from . import crypto

        fast = crypto.KdfParams(memory_kib=1024, iterations=1, lanes=1)
        salt = crypto.new_salt()
        key = crypto.derive_key("prueba", salt, fast)
        blob = crypto.seal(b"hola", key, salt, fast)
        assert crypto.open_blob(blob, "prueba").plaintext == b"hola"
        return f"Argon2id + AES-256-GCM, cryptography {cryptography.__version__}, {backend.openssl_version_text()}"

    def vault_roundtrip() -> str:
        from . import crypto
        from .store import Vault

        with tempfile.TemporaryDirectory() as d:
            v = Vault(Path(d) / "v.ncv")
            v.create("contraseña de prueba", crypto.KdfParams(memory_kib=1024, iterations=1, lanes=1))
            v.add_note("t", "b")
            v.save()
            v.lock()
            v.unlock("contraseña de prueba")
            assert len(v.notes) == 1
            v.lock()
        return "crear, guardar, bloquear y desbloquear"

    def qt_info() -> str:
        from PySide6.QtCore import QCoreApplication, QLibraryInfo
        from PySide6.QtGui import QImageReader
        import PySide6.QtDBus  # noqa: F401 - comprueba que el módulo está empaquetado
        import PySide6.QtSvg  # noqa: F401 - el plugin SVG se empaqueta al importarlo
        import PySide6.QtWidgets  # noqa: F401

        app = QCoreApplication.instance() or QCoreApplication([])
        formats = [bytes(f).decode() for f in QImageReader.supportedImageFormats()]
        assert "svg" in formats, "falta el plugin de imágenes SVG"
        plugins = QLibraryInfo.path(QLibraryInfo.PluginsPath)
        del app
        return f"Qt {QLibraryInfo.version().toString()}, plugins en {plugins}"

    def bundled_files() -> str:
        from .ui import ICON_PATH

        assert ICON_PATH.is_file(), f"falta {ICON_PATH}"
        return str(ICON_PATH)

    check("cifrado", crypto_roundtrip)
    check("bóveda", vault_roundtrip)
    check("Qt", qt_info)
    check("icono", bundled_files)
    print("TODO CORRECTO" if not failures else f"{failures} COMPROBACIÓN(ES) FALLIDA(S)")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="notas-cifradas", description="Notas cifradas con AES-256-GCM")
    parser.add_argument("--vault", type=Path, help="ruta del archivo de la bóveda")
    parser.add_argument("--selftest", action="store_true", help="comprueba dependencias y sale")
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)

    if args.selftest:
        return selftest()

    harden_process()

    from PySide6.QtWidgets import QApplication

    from .store import Vault, default_vault_path
    from .theme import apply_plasma_look
    from .ui import APP_ID, APP_NAME, MainWindow

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("notas-cifradas")
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)  # enlaza la ventana con el .desktop en Plasma
    apply_plasma_look(app)  # solo actúa con el Qt empaquetado (sin estilo Breeze)

    window = MainWindow(Vault(args.vault or default_vault_path()))
    window.show()
    return app.exec()
