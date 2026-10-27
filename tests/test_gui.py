import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NOTAS_NO_HARDEN", "1")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from notas_cifradas.crypto import KdfParams
from notas_cifradas.store import Vault

FAST = KdfParams(memory_kib=1024, iterations=1, lanes=1)
PW = "una contraseña maestra larga"


@unittest.skipUnless(HAVE_QT, "PySide6 no instalado")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from notas_cifradas.ui import MainWindow

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "vault.ncv"
        self.MainWindow = MainWindow

    def window(self, preexisting=False):
        vault = Vault(self.path)
        if preexisting:
            vault.create(PW, FAST)
            vault.lock()
        w = self.MainWindow(vault)
        w.show()
        self.addCleanup(w.close)
        return w

    def unlock(self, w):
        w.lock_page.password.setText(PW)
        w.lock_page.button.click()

    def titles(self, w):
        return [w.list.item(i).text().split("\n")[0] for i in range(w.list.count())]

    # ── pruebas ───────────────────────────────────────────────────────────
    def test_first_run_creates_vault_through_ui(self):
        w = self.window()
        lp = w.lock_page
        self.assertIs(w.stack.currentWidget(), lp)
        self.assertTrue(lp.confirm.isVisibleTo(lp))

        lp.password.setText("corta")
        lp.button.click()
        self.assertIn("al menos", lp.error.text())
        self.assertFalse(self.path.exists())

        lp.password.setText(PW)
        lp.confirm.setText(PW + "x")
        lp.button.click()
        self.assertIn("no coinciden", lp.error.text())

        lp.confirm.setText(PW)
        lp.button.click()  # usa los parámetros KDF reales (512 MiB)
        self.assertTrue(self.path.exists())
        self.assertIs(w.stack.currentWidget(), w.notes_page)
        self.assertEqual(self.titles(w), ["Bienvenida"])
        w.grab().save(os.path.join(self.tmp.name, "notes.png"))

    def test_edit_autosave_lock_unlock(self):
        w = self.window(preexisting=True)
        self.unlock(w)
        w.title_edit.setText("Secreto-ÑÑ")
        w.body_edit.setPlainText("contenido muy privado")
        self.assertTrue(w._dirty)
        w._save_timer.timeout.emit()  # no esperar 1,2 s
        self.assertFalse(w._dirty)
        self.assertNotIn(b"privado", self.path.read_bytes())

        w.lock_now()
        self.assertIs(w.stack.currentWidget(), w.lock_page)
        self.assertEqual(w.list.count(), 0)
        self.assertEqual(w.body_edit.toPlainText(), "")
        self.assertEqual(w.title_edit.text(), "")
        self.assertFalse(w.vault.unlocked)
        self.assertEqual(w.vault.notes, {})
        w.grab().save(os.path.join(self.tmp.name, "locked.png"))

        w.lock_page.password.setText("incorrecta incorrecta")
        w.lock_page.button.click()
        self.assertIn("incorrecta", w.lock_page.error.text())
        self.assertIs(w.stack.currentWidget(), w.lock_page)

        self.unlock(w)
        self.assertEqual(self.titles(w), ["Secreto-ÑÑ"])
        self.assertEqual(w.body_edit.toPlainText(), "contenido muy privado")

    def test_lock_with_active_search_leaves_nothing_in_widgets(self):
        w = self.window(preexisting=True)
        self.unlock(w)
        w.search.setText("bienvenida")
        self.assertEqual(w.list.count(), 1)
        w.lock_now()
        self.assertEqual(w.list.count(), 0)
        self.assertEqual(w.body_edit.toPlainText(), "")
        self.assertEqual(w.search.text(), "")

    def test_search_new_delete(self):
        w = self.window(preexisting=True)
        self.unlock(w)
        w._new_note()
        w.title_edit.setText("Compra")
        w.body_edit.setPlainText("leche y pan")
        w._autosave()
        self.assertEqual(self.titles(w)[0], "Compra")  # la más reciente primero
        self.assertEqual(w.list.count(), 2)

        w.search.setText("pan")
        self.assertEqual(self.titles(w), ["Compra"])
        w.search.setText("nada que coincida")
        self.assertEqual(w.list.count(), 0)
        self.assertFalse(w.body_edit.isEnabled())
        w.search.setText("")
        self.assertEqual(w.list.count(), 2)

        w.search.setText("compra")
        orig = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        self.addCleanup(setattr, QMessageBox, "question", orig)
        w._delete_note()
        w.search.setText("")
        self.assertEqual(self.titles(w), ["Bienvenida"])
        w.lock_now()
        v = Vault(self.path)
        v.unlock(PW)
        self.assertEqual([n.title for n in v.notes.values()], ["Bienvenida"])

    def test_idle_autolock(self):
        w = self.window(preexisting=True)
        self.unlock(w)
        self.assertTrue(w._idle_timer.isActive())
        w._idle_timer.timeout.emit()
        self.assertFalse(w.vault.unlocked)
        self.assertIs(w.stack.currentWidget(), w.lock_page)

    def test_edit_while_typing_does_not_reload_editor(self):
        w = self.window(preexisting=True)
        self.unlock(w)
        w.body_edit.setPlainText("abc")
        w.body_edit.moveCursor(w.body_edit.textCursor().MoveOperation.End)
        pos = w.body_edit.textCursor().position()
        w._autosave()
        self.assertEqual(w.body_edit.textCursor().position(), pos)

    def test_change_password_through_ui_upgrades_kdf(self):
        from notas_cifradas import crypto, ui

        w = self.window(preexisting=True)  # creada con parámetros FAST
        self.unlock(w)
        self.assertEqual(w.vault._params, FAST)

        def fake_exec(dlg):
            dlg.current.setText(PW)
            dlg.new.setText("otra contraseña distinta y larga")
            dlg.confirm.setText("otra contraseña distinta y larga")
            dlg._accept()
            return ui.QDialog.Accepted

        orig = ui.ChangePasswordDialog.exec
        ui.ChangePasswordDialog.exec = fake_exec
        self.addCleanup(setattr, ui.ChangePasswordDialog, "exec", orig)
        w._change_password()
        self.assertEqual(w.vault._params, crypto.DEFAULT_KDF)
        w.lock_now()

        w.lock_page.password.setText(PW)  # la antigua ya no sirve
        w.lock_page.button.click()
        self.assertIn("incorrecta", w.lock_page.error.text())
        w.lock_page.password.setText("otra contraseña distinta y larga")
        w.lock_page.button.click()
        self.assertTrue(w.vault.unlocked)

    def test_change_password_wrong_current_is_rejected(self):
        from notas_cifradas import ui

        w = self.window(preexisting=True)
        self.unlock(w)

        def fake_exec(dlg):
            dlg.current.setText("no es esta la contraseña")
            dlg.new.setText("otra contraseña distinta y larga")
            dlg.confirm.setText("otra contraseña distinta y larga")
            dlg._accept()
            return ui.QDialog.Accepted

        warned = []
        orig_exec, orig_warn = ui.ChangePasswordDialog.exec, QMessageBox.warning
        ui.ChangePasswordDialog.exec = fake_exec
        QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
        self.addCleanup(setattr, ui.ChangePasswordDialog, "exec", orig_exec)
        self.addCleanup(setattr, QMessageBox, "warning", orig_warn)
        w._change_password()
        self.assertEqual(len(warned), 1)
        self.assertEqual(w.vault._params, FAST)  # nada cambió
        self.assertTrue(w.vault.verify_password(PW))

    def test_second_window_cannot_open_busy_vault(self):
        w1 = self.window(preexisting=True)
        self.unlock(w1)
        w2 = self.window()
        w2.lock_page.password.setText(PW)
        w2.lock_page.button.click()
        self.assertIn("otra ventana", w2.lock_page.error.text())


if __name__ == "__main__":
    unittest.main()
