import os
import stat
import struct
import tempfile
import unittest
from pathlib import Path

from notas_cifradas import crypto
from notas_cifradas.crypto import (
    CorruptVaultError,
    KdfParams,
    WrongPasswordError,
)
from notas_cifradas.store import Vault, VaultBusyError

FAST = KdfParams(memory_kib=1024, iterations=1, lanes=1)  # solo para tests
PW = "correct horse battery staple"


class CryptoTests(unittest.TestCase):
    def roundtrip(self, data=b"hola"):
        salt = crypto.new_salt()
        key = crypto.derive_key(PW, salt, FAST)
        return crypto.seal(data, key, salt, FAST)

    def test_roundtrip(self):
        blob = self.roundtrip(b"secreto \xc3\xb1")
        self.assertEqual(crypto.open_blob(blob, PW).plaintext, b"secreto \xc3\xb1")

    def test_default_is_strong(self):
        self.assertEqual(crypto.KEY_LEN, 32)  # AES-256
        self.assertGreaterEqual(crypto.DEFAULT_KDF.memory_kib, 256 * 1024)
        self.assertGreaterEqual(crypto.DEFAULT_KDF.iterations, 3)

    def test_wrong_password(self):
        with self.assertRaises(WrongPasswordError):
            crypto.open_blob(self.roundtrip(), PW + "x")

    def test_unicode_normalisation(self):
        salt = crypto.new_salt()
        k1 = crypto.derive_key("café-clave-larga", salt, FAST)  # é compuesta
        k2 = crypto.derive_key("café-clave-larga", salt, FAST)  # e + acento
        self.assertEqual(k1, k2)

    def test_nonce_is_fresh(self):
        salt = crypto.new_salt()
        key = crypto.derive_key(PW, salt, FAST)
        a, b = (crypto.seal(b"x", key, salt, FAST) for _ in range(2))
        self.assertNotEqual(a, b)

    def test_any_bit_flip_is_detected(self):
        blob = bytearray(self.roundtrip(b"x" * 100))
        # cabecera (incl. sal, nonce y parámetros), cuerpo y etiqueta
        for pos in (8, 10, 20, crypto.HEADER_LEN - 1, crypto.HEADER_LEN, len(blob) - 1):
            bad = bytearray(blob)
            bad[pos] ^= 1
            with self.assertRaises((WrongPasswordError, CorruptVaultError), msg=f"pos {pos}"):
                crypto.open_blob(bytes(bad), PW)

    def test_truncated_and_garbage(self):
        blob = self.roundtrip()
        for bad in (b"", b"NCVAULT", blob[:-1], blob[: crypto.HEADER_LEN], b"x" * 200):
            with self.assertRaises((WrongPasswordError, CorruptVaultError)):
                crypto.open_blob(bad, PW)

    def test_rejects_absurd_kdf_params(self):
        blob = bytearray(self.roundtrip())
        struct.pack_into(">I", blob, 9, 0xFFFFFFFF)  # memoria gigantesca
        with self.assertRaises(CorruptVaultError):
            crypto.open_blob(bytes(blob), PW)

    def test_padding_hides_exact_length(self):
        small = [len(self.roundtrip(b"a" * n)) for n in (1, 50, 4000)]
        self.assertEqual(len(set(small)), 1)


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sub" / "vault.ncv"

    def make(self):
        v = Vault(self.path)
        v.create(PW, FAST)
        return v

    def test_create_unlock_persist(self):
        v = self.make()
        n = v.add_note("Título", "Cuerpo con ñ y 日本語")
        v.save()
        v.lock()
        self.assertFalse(v.unlocked)
        v2 = Vault(self.path)
        v2.unlock(PW)
        self.assertEqual(v2.notes[n.id].body, "Cuerpo con ñ y 日本語")

    def test_plaintext_not_on_disk(self):
        v = self.make()
        v.add_note("MUY-SECRETO-TITULO", "MUY-SECRETO-CUERPO")
        v.save()
        raw = self.path.read_bytes()
        self.assertNotIn(b"MUY-SECRETO", raw)

    def test_wrong_password_leaves_vault_locked(self):
        self.make().lock()
        v = Vault(self.path)
        with self.assertRaises(WrongPasswordError):
            v.unlock("otra contraseña")
        self.assertFalse(v.unlocked)
        v.unlock(PW)  # la tentativa fallida no dejó el flock retenido
        self.assertTrue(v.unlocked)

    def test_permissions(self):
        v = self.make()
        v.save()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_no_tmp_files_left(self):
        v = self.make()
        for _ in range(3):
            v.save()
        leftovers = [p.name for p in self.path.parent.iterdir() if p.name.startswith(".vault-")]
        self.assertEqual(leftovers, [])

    def test_single_instance(self):
        v = self.make()
        with self.assertRaises(VaultBusyError):
            Vault(self.path).unlock(PW)
        v.lock()
        Vault(self.path).unlock(PW)

    def test_change_password(self):
        v = self.make()
        v.add_note("a", "b")
        v.save()
        v.lock()
        v.unlock(PW)  # abre sesión nueva → crea .bak con la clave antigua
        v.save()
        self.assertTrue(v._backup_path.exists())
        self.assertTrue(v.verify_password(PW))
        self.assertFalse(v.verify_password("no"))
        v.change_password("nueva contraseña muy larga", FAST)
        self.assertFalse(v._backup_path.exists())
        v.lock()
        with self.assertRaises(WrongPasswordError):
            Vault(self.path).unlock(PW)
        v2 = Vault(self.path)
        v2.unlock("nueva contraseña muy larga")
        self.assertEqual(len(v2.notes), 1)

    def test_backup_is_taken_once_per_session(self):
        v = self.make()
        n = v.add_note("v1", "")
        v.save()
        v.lock()
        v.unlock(PW)
        v.notes[n.id].title = "v2"
        v.save()  # primer guardado de la sesión → respalda v1
        v.notes[n.id].title = "v3"
        v.save()  # no vuelve a respaldar
        bak = Vault(self.path.with_name("copy.ncv"))
        bak.path.write_bytes(v._backup_path.read_bytes())
        v.lock()
        bak.unlock(PW)
        self.assertEqual(bak.notes[n.id].title, "v1")

    def test_locked_vault_refuses_operations(self):
        v = self.make()
        v.lock()
        with self.assertRaises(Exception):
            v.add_note()
        with self.assertRaises(Exception):
            v.save()


class HardeningTests(unittest.TestCase):
    """prctl(PR_SET_DUMPABLE) se aplica fuera de Flatpak y se omite dentro."""

    def run_child(self, env_extra):
        import subprocess
        import sys

        code = (
            "import ctypes; from notas_cifradas.app import harden_process; harden_process();"
            "print(ctypes.CDLL('libc.so.6').prctl(3, 0, 0, 0, 0))"
        )
        env = {k: v for k, v in os.environ.items() if k not in ("FLATPAK_ID", "NOTAS_NO_HARDEN")}
        env.update(env_extra)
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        return int(out.stdout.strip())

    def test_dumpable_cleared_outside_flatpak(self):
        self.assertEqual(self.run_child({}), 0)

    def test_dumpable_untouched_inside_flatpak(self):
        self.assertEqual(self.run_child({"FLATPAK_ID": "io.github.lumiere11.NotasCifradas"}), 1)

    def test_opt_out(self):
        self.assertEqual(self.run_child({"NOTAS_NO_HARDEN": "1"}), 1)


if __name__ == "__main__":
    unittest.main()
