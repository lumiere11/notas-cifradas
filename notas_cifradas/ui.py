"""Interfaz Qt6 (se integra con el estilo Breeze y los iconos de Plasma)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import crypto, passwords
from .crypto import VaultError, WrongPasswordError
from .store import Vault

APP_NAME = "Notas Cifradas"
# Dentro de Flatpak el escritorio identifica la app (icono, .desktop, app_id de Wayland) por su ID.
APP_ID = os.environ.get("FLATPAK_ID", "notas-cifradas")
ICON_PATH = Path(__file__).with_name("icon.svg")
CIPHER_INFO = "AES-256-GCM · Argon2id ({} MiB, {} pasadas)".format(
    crypto.DEFAULT_KDF.memory_kib // 1024, crypto.DEFAULT_KDF.iterations
)
AUTOLOCK_CHOICES = (("1 minuto", 1), ("5 minutos", 5), ("15 minutos", 15), ("30 minutos", 30), ("Nunca", 0))
SAVE_DELAY_MS = 1200
UNTITLED = "(sin título)"


def icon(name: str) -> QIcon:
    return QIcon.fromTheme(name)


def app_icon() -> QIcon:
    return QIcon.fromTheme(APP_ID, QIcon(str(ICON_PATH)))


class PasswordField(QLineEdit):
    """Campo de contraseña con botón de mostrar/ocultar."""

    def __init__(self, placeholder: str = ""):
        super().__init__()
        self.setEchoMode(QLineEdit.Password)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(False)
        toggle = QAction(icon("password-show-on"), "Mostrar u ocultar", self)
        toggle.setCheckable(True)
        toggle.toggled.connect(
            lambda on: self.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        self.addAction(toggle, QLineEdit.TrailingPosition)


class StrengthMeter(QWidget):
    def __init__(self):
        super().__init__()
        self.bar = QProgressBar()
        self.bar.setRange(0, 128)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.label = QLabel()
        self.label.setStyleSheet("font-size: 11px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.bar)
        lay.addWidget(self.label)
        self.update_for("")

    def update_for(self, password: str) -> None:
        bits, text, color = passwords.describe(password)
        self.bar.setValue(int(min(bits, 128)))
        self.bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}")
        if password:
            self.label.setText(f"{text} · ≈{int(bits)} bits (estimación orientativa)")
        else:
            self.label.setText(f"Mínimo {passwords.MIN_LENGTH} caracteres. Mejor una frase de 5+ palabras.")


def validate_new_password(pw: str, confirm: str) -> str | None:
    if len(pw) < passwords.MIN_LENGTH:
        return f"La contraseña debe tener al menos {passwords.MIN_LENGTH} caracteres."
    if pw != confirm:
        return "Las contraseñas no coinciden."
    return None


# ───────────────────────────── pantalla de bloqueo ──────────────────────────
class LockPage(QWidget):
    submitted = Signal(str)

    def __init__(self):
        super().__init__()
        self._create_mode = False

        pic = QLabel()
        pic.setPixmap(app_icon().pixmap(96, 96))
        pic.setAlignment(Qt.AlignCenter)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 20px; font-weight: 600;")
        self.subtitle = QLabel()
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setWordWrap(True)

        self.password = PasswordField("Contraseña maestra")
        self.confirm = PasswordField("Repite la contraseña")
        self.meter = StrengthMeter()
        self.error = QLabel()
        self.error.setStyleSheet("color: #da4453;")
        self.error.setWordWrap(True)
        self.error.setAlignment(Qt.AlignCenter)
        self.error.hide()
        self.button = QPushButton()
        self.button.setDefault(True)
        self.info = QLabel(CIPHER_INFO)
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setEnabled(False)

        col = QWidget()
        col.setMaximumWidth(380)
        lay = QVBoxLayout(col)
        lay.setSpacing(10)
        for w in (pic, self.title, self.subtitle, self.password, self.confirm,
                  self.meter, self.error, self.button, self.info):
            lay.addWidget(w)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(col)
        row.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self.button.clicked.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        self.confirm.returnPressed.connect(self._submit)
        self.password.textChanged.connect(self._on_password_changed)

    def set_mode(self, create: bool) -> None:
        self._create_mode = create
        self.title.setText(APP_NAME)
        if create:
            self.subtitle.setText(
                "Crea tu bóveda. Si olvidas la contraseña maestra, "
                "<b>no hay forma de recuperar las notas</b>."
            )
            self.button.setText("Crear bóveda")
        else:
            self.subtitle.setText("La bóveda está bloqueada.")
            self.button.setText("Desbloquear")
        self.confirm.setVisible(create)
        self.meter.setVisible(create)
        self.reset()

    def reset(self) -> None:
        self.password.clear()
        self.confirm.clear()
        self._set_error("")
        self.meter.update_for("")
        self.password.setEchoMode(QLineEdit.Password)
        self.confirm.setEchoMode(QLineEdit.Password)
        self.password.setFocus()

    def _set_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def show_error(self, text: str) -> None:
        self._set_error(text)
        self.password.selectAll()
        self.password.setFocus()

    def set_busy(self, busy: bool) -> None:
        for w in (self.password, self.confirm, self.button):
            w.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.button.setText("Derivando clave…")
            QApplication.processEvents()
        else:
            QApplication.restoreOverrideCursor()
            self.button.setText("Crear bóveda" if self._create_mode else "Desbloquear")

    def _on_password_changed(self, text: str) -> None:
        self._set_error("")
        if self._create_mode:
            self.meter.update_for(text)

    def _submit(self) -> None:
        pw = self.password.text()
        if not pw:
            return
        if self._create_mode:
            problem = validate_new_password(pw, self.confirm.text())
            if problem:
                self.show_error(problem)
                return
        self.submitted.emit(pw)


class ChangePasswordDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Cambiar contraseña maestra")
        self.current = PasswordField()
        self.new = PasswordField()
        self.confirm = PasswordField()
        self.meter = StrengthMeter()
        self.error = QLabel()
        self.error.setStyleSheet("color: #da4453;")
        self.error.setWordWrap(True)
        self.new.textChanged.connect(self.meter.update_for)

        form = QFormLayout()
        form.addRow("Contraseña actual:", self.current)
        form.addRow("Nueva contraseña:", self.new)
        form.addRow("", self.meter)
        form.addRow("Repetir nueva:", self.confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addWidget(buttons)
        self.setMinimumWidth(420)

    def _accept(self) -> None:
        problem = validate_new_password(self.new.text(), self.confirm.text())
        if problem:
            self.error.setText(problem)
            return
        self.accept()


# ─────────────────────── bloqueo al bloquear pantalla / suspender ───────────
class SessionWatcher(QObject):
    """Emite `lockRequested` cuando Plasma bloquea la pantalla o el sistema suspende."""

    lockRequested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.connected: list[str] = []
        try:
            from PySide6.QtCore import SLOT
            from PySide6.QtDBus import QDBusConnection
        except ImportError:  # pragma: no cover
            return
        session, system = QDBusConnection.sessionBus(), QDBusConnection.systemBus()
        targets = [
            (session, "/ScreenSaver", "org.freedesktop.ScreenSaver", "ActiveChanged"),
            (session, "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver", "ActiveChanged"),
            (system, "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "PrepareForSleep"),
        ]
        for bus, path, iface, name in targets:
            if bus.isConnected() and bus.connect("", path, iface, name, self, SLOT("_on_signal(bool)")):
                self.connected.append(f"{iface}.{name}@{path}")

    @Slot(bool)
    def _on_signal(self, active: bool) -> None:
        if active:
            self.lockRequested.emit()


# ───────────────────────────── ventana principal ────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, vault: Vault):
        super().__init__()
        self.vault = vault
        self.settings = QSettings("notas-cifradas", "notas-cifradas")
        self._loading = False
        self._dirty = False
        self._current_id: str | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(940, 620)

        self.stack = QStackedWidget()
        self.lock_page = LockPage()
        self.notes_page = self._build_notes_page()
        self.stack.addWidget(self.lock_page)
        self.stack.addWidget(self.notes_page)
        self.setCentralWidget(self.stack)
        self.status_info = QLabel(CIPHER_INFO)
        self.statusBar().addPermanentWidget(self.status_info)

        self._build_actions()
        self._build_menus()

        self._save_timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._autosave)
        self._idle_timer = QTimer(self, singleShot=True)
        self._idle_timer.timeout.connect(self.lock_now)
        QApplication.instance().installEventFilter(self)

        self.watcher = SessionWatcher(self)
        self.watcher.lockRequested.connect(self.lock_now)
        self.lock_page.submitted.connect(self._on_submit)

        self._show_lock_page()

    # ── construcción ──────────────────────────────────────────────────────
    def _build_notes_page(self) -> QWidget:
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._refresh_list(self._current_id))
        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.currentItemChanged.connect(self._on_select)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 0, 6)
        ll.addWidget(self.search)
        ll.addWidget(self.list)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Título")
        self.title_edit.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText("Escribe aquí. Todo se cifra con AES-256-GCM al guardar.")
        self.body_edit.setTabChangesFocus(False)
        self.title_edit.textChanged.connect(self._on_edited)
        self.body_edit.textChanged.connect(self._on_edited)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 6, 6, 6)
        rl.addWidget(self.title_edit)
        rl.addWidget(self.body_edit)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 680])
        splitter.setChildrenCollapsible(False)
        return splitter

    def _build_actions(self) -> None:
        def act(text, icon_name, shortcut=None, slot=None):
            a = QAction(icon(icon_name), text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if slot:
                a.triggered.connect(slot)
            return a

        self.a_new = act("Nueva nota", "document-new", QKeySequence.New, self._new_note)
        self.a_delete = act("Eliminar nota", "edit-delete", "Ctrl+Shift+Del", self._delete_note)
        self.a_save = act("Guardar", "document-save", QKeySequence.Save, lambda: self._save(True))
        self.a_lock = act("Bloquear", "system-lock-screen", "Ctrl+L", self.lock_now)
        self.a_find = act("Buscar", "edit-find", QKeySequence.Find, self._focus_search)
        self.a_passwd = act("Cambiar contraseña maestra…", "dialog-password", None, self._change_password)
        self.a_quit = act("Salir", "application-exit", QKeySequence.Quit, self.close)
        self.a_about = act("Acerca de…", "help-about", None, self._about)
        self.a_zoom_in = act("Aumentar texto", "zoom-in", QKeySequence.ZoomIn, lambda: self.body_edit.zoomIn(1))
        self.a_zoom_out = act("Reducir texto", "zoom-out", QKeySequence.ZoomOut, lambda: self.body_edit.zoomOut(1))
        self.a_lock_min = QAction("Bloquear al minimizar", self, checkable=True)
        self.a_lock_min.setChecked(self.settings.value("lock_on_minimize", False, bool))
        self.a_lock_min.toggled.connect(lambda v: self.settings.setValue("lock_on_minimize", v))

        self.unlocked_actions = (
            self.a_new, self.a_delete, self.a_save, self.a_lock, self.a_find, self.a_passwd,
            self.a_zoom_in, self.a_zoom_out,
        )

        tb = QToolBar("Principal")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.a_new, self.a_delete, self.a_save):
            tb.addAction(a)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.a_lock)
        self.addToolBar(tb)
        self.toolbar = tb

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&Archivo")
        for a in (self.a_new, self.a_save):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_quit)

        m = mb.addMenu("&Edición")
        for a in (self.a_find, self.a_delete):
            m.addAction(a)

        m = mb.addMenu("&Ver")
        m.addAction(self.a_zoom_in)
        m.addAction(self.a_zoom_out)

        m = mb.addMenu("&Seguridad")
        m.addAction(self.a_lock)
        m.addAction(self.a_passwd)
        m.addSeparator()
        sub = m.addMenu("Bloqueo automático por inactividad")
        group = QActionGroup(self)
        current = self._autolock_minutes()
        for label, minutes in AUTOLOCK_CHOICES:
            a = QAction(label, self, checkable=True)
            a.setChecked(minutes == current)
            a.triggered.connect(lambda _=False, mins=minutes: self._set_autolock(mins))
            group.addAction(a)
            sub.addAction(a)
        m.addAction(self.a_lock_min)

        m = mb.addMenu("A&yuda")
        m.addAction(self.a_about)

    # ── estado bloqueado / desbloqueado ───────────────────────────────────
    def _show_lock_page(self) -> None:
        self._set_unlocked_ui(False)
        self.lock_page.set_mode(create=not self.vault.exists)
        self.stack.setCurrentWidget(self.lock_page)

    def _set_unlocked_ui(self, unlocked: bool) -> None:
        for a in self.unlocked_actions:
            a.setEnabled(unlocked)
        self.toolbar.setVisible(unlocked)
        self.a_lock_min.setEnabled(True)

    @Slot(str)
    def _on_submit(self, password: str) -> None:
        self.lock_page.set_busy(True)
        try:
            if self.vault.exists:
                self.vault.unlock(password)
            else:
                self.vault.create(password)
        except WrongPasswordError:
            self.lock_page.set_busy(False)
            self.lock_page.show_error("Contraseña incorrecta.")
            return
        except (VaultError, OSError) as exc:
            self.lock_page.set_busy(False)
            self.lock_page.show_error(str(exc))
            return
        self.lock_page.set_busy(False)
        self.lock_page.reset()
        self._enter_notes()

    def _enter_notes(self) -> None:
        self._set_unlocked_ui(True)
        self.stack.setCurrentWidget(self.notes_page)
        if not self.vault.notes:
            self.vault.add_note("Bienvenida", "Esta nota está cifrada con AES-256-GCM.\n")
            self._save(False)
        self.search.clear()
        self._refresh_list(None)
        self._restart_idle()
        self.statusBar().showMessage("Bóveda desbloqueada", 3000)

    def lock_now(self) -> None:
        if not self.vault.unlocked:
            return
        if not self._flush():
            return  # no se pudo guardar: no tirar los cambios por bloquear
        self._save_timer.stop()
        self._idle_timer.stop()
        self._loading = True
        self.search.blockSignals(True)  # si no, vaciar la búsqueda repuebla la lista
        self.search.clear()
        self.search.blockSignals(False)
        self.list.clear()
        self.title_edit.clear()
        self.body_edit.clear()
        self.body_edit.document().clearUndoRedoStacks()
        self._loading = False
        self._current_id = None
        self.vault.lock()
        self.statusBar().clearMessage()
        self._show_lock_page()

    # ── lista y edición ───────────────────────────────────────────────────
    def _refresh_list(self, select_id: str | None) -> None:
        needle = self.search.text().strip().lower()
        scroll = self.list.verticalScrollBar().value()
        self.list.blockSignals(True)
        self.list.clear()
        target = None
        for note in self.vault.sorted_notes():
            if needle and needle not in note.title.lower() and needle not in note.body.lower():
                continue
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(note.modified))
            item = QListWidgetItem(f"{note.title or UNTITLED}\n{when}")
            item.setData(Qt.UserRole, note.id)
            item.setSizeHint(QSize(0, 46))
            self.list.addItem(item)
            if note.id == select_id:
                target = item
        self.list.verticalScrollBar().setValue(scroll)
        if target is None and self.list.count():
            target = self.list.item(0)
        self.list.setCurrentItem(target)
        self.list.blockSignals(False)
        new_id = target.data(Qt.UserRole) if target else None
        if new_id != self._current_id or select_id is None:
            self._load_note(new_id)

    def _load_note(self, note_id: str | None) -> None:
        self._loading = True
        self._current_id = note_id
        note = self.vault.notes.get(note_id) if note_id else None
        self.title_edit.setText(note.title if note else "")
        self.body_edit.setPlainText(note.body if note else "")
        self.body_edit.document().clearUndoRedoStacks()
        for w in (self.title_edit, self.body_edit):
            w.setEnabled(note is not None)
        self.a_delete.setEnabled(note is not None and self.vault.unlocked)
        self._loading = False

    def _on_select(self, current: QListWidgetItem | None, _previous) -> None:
        if self._loading or not self.vault.unlocked:
            return
        self._flush()
        self._load_note(current.data(Qt.UserRole) if current else None)

    def _on_edited(self) -> None:
        if self._loading or not self._current_id:
            return
        note = self.vault.notes.get(self._current_id)
        if note is None:
            return
        note.title = self.title_edit.text()
        note.body = self.body_edit.toPlainText()
        note.modified = time.time()
        self._dirty = True
        self.statusBar().showMessage("Cambios sin guardar…")
        self._save_timer.start()

    def _autosave(self) -> None:
        if self._flush():
            self._refresh_list(self._current_id)

    def _flush(self) -> bool:
        """Guarda si hay cambios pendientes. Devuelve False si falló."""
        if not self._dirty:
            return True
        return self._save(False)

    def _save(self, interactive: bool) -> bool:
        if not self.vault.unlocked:
            return True
        self._save_timer.stop()
        try:
            self.vault.save()
        except OSError as exc:
            self.statusBar().showMessage(f"Error al guardar: {exc}")
            if interactive:
                QMessageBox.critical(self, APP_NAME, f"No se pudo guardar la bóveda:\n{exc}")
            return False
        self._dirty = False
        self.statusBar().showMessage("Guardado y cifrado · " + time.strftime("%H:%M:%S"), 4000)
        return True

    def _new_note(self) -> None:
        if not self._flush():
            return
        self.search.clear()
        note = self.vault.add_note()
        self._save(False)
        self._refresh_list(note.id)
        self.title_edit.setFocus()

    def _delete_note(self) -> None:
        note = self.vault.notes.get(self._current_id or "")
        if note is None:
            return
        answer = QMessageBox.question(
            self, APP_NAME, f"¿Eliminar «{note.title or UNTITLED}»? No se puede deshacer.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self.vault.delete_note(note.id)
        self._dirty = True
        self._flush()
        self._current_id = None
        self._refresh_list(None)

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # ── seguridad ─────────────────────────────────────────────────────────
    def _change_password(self) -> None:
        if not self._flush():
            return
        dlg = ChangePasswordDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            QApplication.processEvents()
            if not self.vault.verify_password(dlg.current.text()):
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, APP_NAME, "La contraseña actual no es correcta.")
                return
            self.vault.change_password(dlg.new.text(), crypto.DEFAULT_KDF)  # de paso, sube el coste del KDF
        except (VaultError, OSError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, f"No se pudo cambiar la contraseña:\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage("Contraseña cambiada. La copia de seguridad antigua se eliminó.", 6000)

    def _autolock_minutes(self) -> int:
        return int(self.settings.value("autolock_minutes", 5))

    def _set_autolock(self, minutes: int) -> None:
        self.settings.setValue("autolock_minutes", minutes)
        self._restart_idle()

    def _restart_idle(self) -> None:
        minutes = self._autolock_minutes()
        if minutes > 0 and self.vault.unlocked:
            self._idle_timer.start(minutes * 60_000)
        else:
            self._idle_timer.stop()

    def _about(self) -> None:
        kdf = crypto.DEFAULT_KDF
        QMessageBox.about(
            self, APP_NAME,
            f"<h3>{APP_NAME}</h3>"
            "<p>Notas cifradas en un único archivo.</p>"
            "<ul>"
            "<li><b>Cifrado:</b> AES-256-GCM (autenticado), nonce aleatorio nuevo en cada guardado</li>"
            f"<li><b>Derivación de clave:</b> Argon2id, {kdf.memory_kib // 1024} MiB, "
            f"{kdf.iterations} pasadas, {kdf.lanes} lanes</li>"
            "<li><b>Archivo:</b> la cabecera completa está autenticada; el tamaño se redondea a 4 KiB</li>"
            "</ul>"
            f"<p>Bóveda: <code>{self.vault.path}</code></p>",
        )

    # ── eventos ───────────────────────────────────────────────────────────
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() in (
            QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.Wheel,
        ) and self.vault.unlocked:
            self._restart_idle()
        return False

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if (
            event.type() == QEvent.WindowStateChange
            and self.isMinimized()
            and self.a_lock_min.isChecked()
        ):
            QTimer.singleShot(0, self.lock_now)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.vault.unlocked and not self._flush():
            answer = QMessageBox.question(
                self, APP_NAME, "No se pudieron guardar los últimos cambios. ¿Salir de todos modos?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.vault.lock()
        event.accept()
