"""
settings_dialog.py — the Settings box (toolbar button).

A small dialog with the everyday knobs:

  * Auto-save pause — how many seconds of typing silence make a revision.
  * Editor font size.
  * Library encryption — a checkbox.  Turning it ON reveals a passphrase
    field and a verification field that must match before OK is allowed;
    turning it OFF (when currently encrypted) asks MainWindow to remove
    encryption after its own confirmation.

The dialog only COLLECTS choices; applying them (re-keying the database,
changing the editor) is MainWindow's job, since it owns the store and
the widgets.  Read the results from the properties after exec().
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    """Collect settings; validate the passphrase pair when enabling
    encryption."""

    def __init__(
        self,
        parent=None,
        *,
        encrypted: bool,
        idle_seconds: int,
        font_size: int,
    ):
        super().__init__(parent)
        self.setWindowTitle("WordVault Settings")
        self._initially_encrypted = encrypted

        # --- everyday knobs ---
        self._idle_spin = QSpinBox(self)
        self._idle_spin.setRange(1, 60)
        self._idle_spin.setSuffix(" seconds")
        self._idle_spin.setValue(idle_seconds)

        self._font_spin = QSpinBox(self)
        self._font_spin.setRange(8, 28)
        self._font_spin.setSuffix(" pt")
        self._font_spin.setValue(font_size)

        # --- encryption ---
        self._enc_box = QCheckBox(
            "Encrypt the library on disk (passphrase asked at startup)", self
        )
        self._enc_box.setChecked(encrypted)
        self._enc_box.toggled.connect(self._update_passphrase_fields)

        self._pw_edit = QLineEdit(self)
        self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_confirm = QLineEdit(self)
        self._pw_confirm.setEchoMode(QLineEdit.EchoMode.Password)

        self._pw_label = QLabel("Passphrase:", self)
        self._pw_confirm_label = QLabel("Repeat passphrase:", self)
        warning = QLabel(
            "There is NO passphrase recovery — a forgotten passphrase "
            "means the library stays locked forever.", self
        )
        warning.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Auto-save after a pause of:", self._idle_spin)
        form.addRow("Editor font size:", self._font_spin)
        form.addRow(self._enc_box)
        form.addRow(self._pw_label, self._pw_edit)
        form.addRow(self._pw_confirm_label, self._pw_confirm)
        form.addRow(warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addWidget(buttons)

        self._update_passphrase_fields()

    # ------------------------------------------------------------- results --

    @property
    def idle_seconds(self) -> int:
        return self._idle_spin.value()

    @property
    def font_size(self) -> int:
        return self._font_spin.value()

    @property
    def wants_encryption(self) -> bool:
        return self._enc_box.isChecked()

    @property
    def passphrase(self) -> Optional[str]:
        """The matched passphrase, only when encryption is being ENABLED."""
        if self.wants_encryption and not self._initially_encrypted:
            return self._pw_edit.text()
        return None

    # ----------------------------------------------------------- internals --

    def _update_passphrase_fields(self) -> None:
        """The passphrase pair only matters when turning encryption ON
        (an already-encrypted library keeps its existing passphrase)."""
        needed = self._enc_box.isChecked() and not self._initially_encrypted
        for widget in (self._pw_label, self._pw_edit,
                       self._pw_confirm_label, self._pw_confirm):
            widget.setEnabled(needed)

    def _on_ok(self) -> None:
        """Validate before accepting: enabling encryption requires a
        non-empty passphrase entered identically twice."""
        if self.wants_encryption and not self._initially_encrypted:
            if not self._pw_edit.text():
                QMessageBox.warning(
                    self, "Settings", "Enter a passphrase to enable encryption."
                )
                return
            if self._pw_edit.text() != self._pw_confirm.text():
                QMessageBox.warning(
                    self, "Settings",
                    "The two passphrase boxes do not match — please retype them."
                )
                return
        self.accept()
