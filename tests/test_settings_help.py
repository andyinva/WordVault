"""
Offscreen tests for the Settings dialog and Help window.

The passphrase-match rule is the important behavior: enabling encryption
must refuse empty or mismatched passphrase pairs.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.editor.help_dialog import _HELP_FILE, HelpDialog  # noqa: E402
from wordvault.editor.settings_dialog import SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _dialog(qapp, encrypted=False):
    return SettingsDialog(
        None, encrypted=encrypted, idle_seconds=3, font_size=12
    )


def test_help_document_exists_and_has_both_parts():
    text = _HELP_FILE.read_text(encoding="utf-8")
    assert "Part 1" in text and "Concept" in text
    assert "Part 2" in text and "Using" in text


def test_help_dialog_opens(qapp):
    HelpDialog()   # constructing it loads and renders the markdown


def test_enable_encryption_requires_matching_passphrases(qapp, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: warnings.append(a[2])),
    )

    dlg = _dialog(qapp)
    dlg._enc_box.setChecked(True)

    dlg._on_ok()                       # empty passphrase: refused
    assert dlg.result() == 0 and len(warnings) == 1

    dlg._pw_edit.setText("one thing")
    dlg._pw_confirm.setText("another") # mismatch: refused
    dlg._on_ok()
    assert dlg.result() == 0 and len(warnings) == 2

    dlg._pw_confirm.setText("one thing")   # matched: accepted
    dlg._on_ok()
    assert dlg.result() == 1
    assert dlg.wants_encryption and dlg.passphrase == "one thing"


def test_passphrase_fields_track_checkbox(qapp):
    dlg = _dialog(qapp)
    assert not dlg._pw_edit.isEnabled()        # off: fields dormant
    dlg._enc_box.setChecked(True)
    assert dlg._pw_edit.isEnabled()            # on: fields live


def test_already_encrypted_library_needs_no_passphrase(qapp):
    # Keeping encryption ON for an already-encrypted library: no fields,
    # no passphrase, OK accepts directly.
    dlg = _dialog(qapp, encrypted=True)
    assert dlg._enc_box.isChecked()
    assert not dlg._pw_edit.isEnabled()
    dlg._on_ok()
    assert dlg.result() == 1
    assert dlg.passphrase is None              # nothing to hand over


def test_plain_settings_pass_through(qapp):
    dlg = _dialog(qapp)
    dlg._idle_spin.setValue(7)
    dlg._font_spin.setValue(14)
    dlg._on_ok()
    assert dlg.result() == 1
    assert dlg.idle_seconds == 7 and dlg.font_size == 14
    assert not dlg.wants_encryption
