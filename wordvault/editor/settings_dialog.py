"""
settings_dialog.py — the Settings box (toolbar button).

A small dialog with the everyday knobs:

  * Auto-save pause — how many seconds of typing silence make a revision.
  * Editor font size.
  * Recent documents — how far back File > Recent remembers.
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
    QFontComboBox,
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
        author: str = "",
        recent_limit: int = 25,
        reopen_last: bool = True,
        font_family: str = "",
        notes_family: str = "",
        notes_size: int = 10,
        reading_speed: int = 100,
        dark_mode: bool = False,
        paragraph_return: bool = True,
        disabled_keys: tuple = (),
        line_light: bool = True,
        recent_panel_count: int = 10,
        tts_engine: str = "system",
        piper_dir: str = "",
        piper_voice: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("WordVault Settings")
        self._initially_encrypted = encrypted

        # The author's name: fills the {author} variable in print
        # formats (bylines, headers, footers).
        self._author_edit = QLineEdit(self)
        self._author_edit.setText(author)
        self._author_edit.setPlaceholderText("Used by print formats ({author})")

        # --- everyday knobs ---
        self._idle_spin = QSpinBox(self)
        self._idle_spin.setRange(1, 60)
        self._idle_spin.setSuffix(" seconds")
        self._idle_spin.setValue(idle_seconds)

        self._font_spin = QSpinBox(self)
        self._font_spin.setRange(8, 28)
        self._font_spin.setSuffix(" pt")
        self._font_spin.setValue(font_size)

        # The editor's typeface: QFontComboBox lists whatever fonts THIS
        # system has (Windows fonts on Windows, Linux fonts on Ubuntu).
        # Display only — printed pages take their fonts from .wvfmt
        # files.  A family missing on the other platform falls back to
        # Qt's nearest look-alike, never an error.
        self._font_combo = QFontComboBox(self)
        if font_family:
            from PyQt6.QtGui import QFont

            self._font_combo.setCurrentFont(QFont(font_family))

        # The NOTES pane's own typeface and size (they need not match
        # the editor's — a smaller, plainer face suits marginalia).
        self._notes_font_combo = QFontComboBox(self)
        if notes_family:
            from PyQt6.QtGui import QFont

            self._notes_font_combo.setCurrentFont(QFont(notes_family))
        self._notes_size_spin = QSpinBox(self)
        self._notes_size_spin.setRange(7, 24)
        self._notes_size_spin.setSuffix(" pt")
        self._notes_size_spin.setValue(notes_size)

        # Read Aloud pace: 100% is the voice's natural speed; 50% is
        # half speed for careful proofing, 150% for quick passes.
        self._speed_spin = QSpinBox(self)
        self._speed_spin.setRange(50, 150)
        self._speed_spin.setSingleStep(5)
        self._speed_spin.setSuffix(" %")
        self._speed_spin.setValue(reading_speed)

        # Which voice reads aloud.  "System" is the operating system's
        # own voice through Qt (fine on Windows, a robot on Ubuntu).
        # "Piper" is a free neural voice that sounds human on both; it
        # needs the Piper program and a voice file in a folder of the
        # user's choosing (see editor/piper_voice.py).
        from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

        from wordvault.editor.piper_voice import (
            DEFAULT_PIPER_DIR, find_piper_executable, list_voices,
            voice_display_name,
        )

        self._engine_combo = QComboBox(self)
        self._engine_combo.addItem("System voice", "system")
        self._engine_combo.addItem("Piper (neural voice)", "piper")
        self._engine_combo.setCurrentIndex(1 if tts_engine == "piper" else 0)

        self._piper_dir_edit = QLineEdit(self)
        self._piper_dir_edit.setText(piper_dir or str(DEFAULT_PIPER_DIR))
        self._piper_dir_edit.setToolTip(
            "The folder holding the Piper program and its voice files "
            "(NAME.onnx and NAME.onnx.json)")
        browse_btn = QPushButton("Browse…", self)
        browse_btn.clicked.connect(self._browse_piper_dir)
        piper_row = QWidget(self)
        piper_layout = QHBoxLayout(piper_row)
        piper_layout.setContentsMargins(0, 0, 0, 0)
        piper_layout.addWidget(self._piper_dir_edit, 1)
        piper_layout.addWidget(browse_btn)

        self._voice_combo = QComboBox(self)
        self._piper_status = QLabel("", self)
        self._piper_status.setWordWrap(True)
        self._piper_status.setStyleSheet("color: gray;")
        self._wanted_voice = piper_voice
        self._piper_dir_edit.editingFinished.connect(self._refresh_voices)
        self._engine_combo.currentIndexChanged.connect(self._refresh_voices)
        self._find_piper = find_piper_executable
        self._list_voices = list_voices
        self._voice_name = voice_display_name
        self._refresh_voices()

        # How far back File > Recent remembers (the list itself lives
        # in QSettings; this is only its length).
        self._recent_spin = QSpinBox(self)
        self._recent_spin.setRange(5, 100)
        self._recent_spin.setSuffix(" documents")
        self._recent_spin.setValue(recent_limit)

        # Start where you left off — or with a clean desk.
        self._reopen_box = QCheckBox(
            "Reopen the last document when WordVault starts", self
        )
        self._reopen_box.setChecked(reopen_last)

        # Dark mode: applied to the whole window, immediately on OK.
        # The Enter key: in the vault a paragraph is a line and a blank
        # line makes the next one, so Enter can add that blank line
        # itself — one keystroke and the cursor is ready for the next
        # paragraph.  Shift+Enter is always a plain single return.
        from PyQt6.QtWidgets import QComboBox

        self._enter_combo = QComboBox(self)
        self._enter_combo.addItem(
            "Starts a new paragraph (adds the blank line)")
        self._enter_combo.addItem("Plain return")
        self._enter_combo.setCurrentIndex(0 if paragraph_return else 1)
        self._enter_combo.setToolTip(
            "What the Enter key does while writing. Shift+Enter is "
            "always a plain single return, in either mode.")

        # Disabled keys: keys the writer wants SILENCED in the editor —
        # a stray Page Up mid-sentence throws the view across the
        # document, and Insert silently flips overwrite mode.  Only the
        # editor ignores them; dialogs and lists keep them.
        from PyQt6.QtWidgets import QHBoxLayout, QWidget

        self._key_boxes = {}
        keys_row = QWidget(self)
        keys_layout = QHBoxLayout(keys_row)
        keys_layout.setContentsMargins(0, 0, 0, 0)
        for name, label in (("pgup", "Pg Up"), ("pgdn", "Pg Dn"),
                            ("home", "Home"), ("end", "End"),
                            ("insert", "Insert")):
            box = QCheckBox(label, keys_row)
            box.setChecked(name in disabled_keys)
            self._key_boxes[name] = box
            keys_layout.addWidget(box)
        keys_layout.addStretch(1)
        keys_row.setToolTip(
            "Checked keys are ignored while typing in the editor — "
            "for keyboards where a stray press keeps sending the view "
            "flying. They still work everywhere else.")

        # The Recent Work panel (below the Outline): how many works in
        # progress it keeps in view.
        self._recent_panel_spin = QSpinBox(self)
        self._recent_panel_spin.setRange(3, 25)
        self._recent_panel_spin.setValue(recent_panel_count)
        self._recent_panel_spin.setSuffix(" documents")
        self._recent_panel_spin.setToolTip(
            "The Recent Work panel lists this many recently worked "
            "documents, with their age, size, month's growth, and "
            "writing hours.")

        self._line_light_box = QCheckBox(
            "Highlight the line being edited", self)
        self._line_light_box.setChecked(line_light)
        self._line_light_box.setToolTip(
            "A gentle full-width wash under the cursor's line — the "
            "eye finds its place at a glance. A calm blue-gray on the "
            "white page; its counterpart in dark mode.")

        self._dark_box = QCheckBox("Dark mode", self)
        self._dark_box.setChecked(dark_mode)

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
        form.addRow("Author name:", self._author_edit)
        form.addRow("Auto-save after a pause of:", self._idle_spin)
        form.addRow("Editor font:", self._font_combo)
        form.addRow("Editor font size:", self._font_spin)
        form.addRow("Notes font:", self._notes_font_combo)
        form.addRow("Notes font size:", self._notes_size_spin)
        form.addRow("Reading speed:", self._speed_spin)
        form.addRow("Reading voice:", self._engine_combo)
        form.addRow("Piper folder:", piper_row)
        form.addRow("Piper voice:", self._voice_combo)
        form.addRow("", self._piper_status)
        form.addRow("Enter key:", self._enter_combo)
        form.addRow("Disabled keys:", keys_row)
        form.addRow(self._line_light_box)
        form.addRow(self._dark_box)
        form.addRow("Recent list remembers:", self._recent_spin)
        form.addRow("Recent Work panel shows:", self._recent_panel_spin)
        form.addRow(self._reopen_box)
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
    def author(self) -> str:
        return self._author_edit.text().strip()

    @property
    def idle_seconds(self) -> int:
        return self._idle_spin.value()

    @property
    def font_size(self) -> int:
        return self._font_spin.value()

    @property
    def font_family(self) -> str:
        return self._font_combo.currentFont().family()

    @property
    def notes_family(self) -> str:
        return self._notes_font_combo.currentFont().family()

    @property
    def notes_size(self) -> int:
        return self._notes_size_spin.value()

    @property
    def reading_speed(self) -> int:
        return self._speed_spin.value()

    @property
    def tts_engine(self) -> str:
        """"system" or "piper"."""
        return self._engine_combo.currentData()

    @property
    def piper_dir(self) -> str:
        return self._piper_dir_edit.text().strip()

    @property
    def piper_voice(self) -> str:
        """The chosen voice's file name (e.g. "en_US-ryan-medium.onnx"),
        or "" when no voice is available."""
        return self._voice_combo.currentData() or ""

    @property
    def paragraph_return(self) -> bool:
        return self._enter_combo.currentIndex() == 0

    @property
    def disabled_keys(self) -> tuple:
        """Names of the keys to silence, e.g. ("pgup", "pgdn")."""
        return tuple(name for name, box in self._key_boxes.items()
                     if box.isChecked())

    @property
    def recent_panel_count(self) -> int:
        return self._recent_panel_spin.value()

    @property
    def line_light(self) -> bool:
        return self._line_light_box.isChecked()

    @property
    def dark_mode(self) -> bool:
        return self._dark_box.isChecked()

    @property
    def recent_limit(self) -> int:
        return self._recent_spin.value()

    @property
    def reopen_last(self) -> bool:
        return self._reopen_box.isChecked()

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

    def _browse_piper_dir(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(
            self, "Piper folder", self._piper_dir_edit.text())
        if folder:
            self._piper_dir_edit.setText(folder)
            self._refresh_voices()

    def _refresh_voices(self) -> None:
        """Re-scan the Piper folder: fill the voice list and say plainly
        what is missing, so the writer never has to guess why Piper
        is silent.  The Piper rows are dimmed while System is chosen."""
        from pathlib import Path

        piper_on = self._engine_combo.currentData() == "piper"
        for widget in (self._piper_dir_edit, self._voice_combo):
            widget.setEnabled(piper_on)

        folder = Path(self._piper_dir_edit.text().strip() or ".").expanduser()
        exe = self._find_piper(folder)
        voices = self._list_voices(folder)

        previous = self._voice_combo.currentData() or self._wanted_voice
        self._voice_combo.clear()
        for voice in voices:
            self._voice_combo.addItem(self._voice_name(voice), voice.name)
        index = self._voice_combo.findData(previous)
        if index >= 0:
            self._voice_combo.setCurrentIndex(index)

        if not piper_on:
            self._piper_status.setText("")
        elif exe is None and not voices:
            self._piper_status.setText(
                "Piper is not in this folder yet. Unpack the Piper "
                "release archive there and add a voice (NAME.onnx and "
                "NAME.onnx.json); see Help > User Guide > Read Aloud.")
        elif exe is None:
            self._piper_status.setText(
                "Voices found, but not the Piper program (piper/piper "
                "or piper.exe).")
        elif not voices:
            self._piper_status.setText(
                "Piper found, but no voice. Download NAME.onnx and "
                "NAME.onnx.json into this folder.")
        else:
            self._piper_status.setText(
                f"Piper ready: {len(voices)} voice"
                f"{'s' if len(voices) != 1 else ''} found.")

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
