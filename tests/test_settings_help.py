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


def test_user_guide_covers_philosophy_and_features():
    """The full User Guide (Shift+F1): philosophy first, then every
    feature area, plus the shortcut table."""
    from wordvault.editor.help_dialog import _GUIDE_FILE

    text = _GUIDE_FILE.read_text(encoding="utf-8")
    assert "Philosophy" in text
    for phrase in ("Nothing is ever lost", "Time Travel", "The Library",
                   "Making a Book", "Keyboard shortcuts", ".wvfmt",
                   "notes pane", "Gather", "Scripture",
                   "The editor is a window into the vault",
                   "in the vault at all times", "SQL"):
        assert phrase in text, f"guide is missing '{phrase}'"


def test_share_email_is_complete_and_copyable(qapp):
    """Help > Share WordVault: the email must carry the download link,
    both platforms' install commands, and the no-account promise; the
    Copy button must land it on the clipboard verbatim."""
    from PyQt6.QtWidgets import QApplication

    from wordvault import REPO_URL
    from wordvault.editor.help_dialog import (
        ShareDialog,
        installation_email_text,
    )

    text = installation_email_text()
    assert REPO_URL in text
    assert "pip install PyQt6" in text and "pip3 install" in text
    assert "ON WINDOWS" in text and "ON UBUNTU" in text
    assert "python -m wordvault" in text
    assert "No account" in text

    dlg = ShareDialog(None)
    dlg.findChildren(type(dlg))  # noqa: B018 (touch the widget tree)
    for button in dlg.findChildren(__import__("PyQt6.QtWidgets",
                                              fromlist=["QPushButton"]
                                              ).QPushButton):
        if "Copy" in button.text():
            button.click()
            break
    assert QApplication.clipboard().text() == text


def test_updating_document_promises_library_safety():
    from wordvault.editor.help_dialog import _UPDATES_FILE

    text = _UPDATES_FILE.read_text(encoding="utf-8")
    # Markdown wraps lines freely, so match with whitespace collapsed.
    flat = " ".join(text.split())
    assert "never touches your writing" in flat
    assert "GitHub Desktop" in flat and "ZIP" in flat
    assert ".wordvault" in flat


def test_guide_dialog_opens(qapp):
    from wordvault.editor.help_dialog import _GUIDE_FILE

    dlg = HelpDialog(None, document=_GUIDE_FILE,
                     title="WordVault User Guide")
    assert dlg.windowTitle() == "WordVault User Guide"


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


def test_reopen_last_switch(qapp):
    """The start-where-you-left-off switch: on by default, honored
    when handed a remembered value, reported after a change."""
    dlg = _dialog(qapp)
    assert dlg.reopen_last is True             # the shipped default

    dlg = SettingsDialog(None, encrypted=False, idle_seconds=3,
                         font_size=12, reopen_last=False)
    assert dlg.reopen_last is False
    dlg._reopen_box.setChecked(True)
    assert dlg.reopen_last is True


def test_font_family_choice(qapp):
    """The editor-typeface knob: always reports SOME family, and
    honors a remembered choice.  The round trip only makes sense
    where fonts exist — Windows' offscreen platform has none (the
    same desert the print tests live with), so it is skipped there."""
    dlg = _dialog(qapp)
    assert dlg.font_family            # a family name, even fontless

    if dlg._font_combo.count() == 0:
        pytest.skip("offscreen platform has no fonts to choose from")
    remembered = dlg._font_combo.itemText(0)     # any real font name
    dlg2 = SettingsDialog(None, encrypted=False, idle_seconds=3,
                          font_size=12, font_family=remembered)
    assert dlg2.font_family == remembered


def test_notes_font_knobs(qapp):
    """The notes pane's own typeface and size in Settings."""
    dlg = _dialog(qapp)
    assert dlg.notes_size == 10                  # the shipped default
    dlg._notes_size_spin.setValue(12)
    assert dlg.notes_size == 12
    assert isinstance(dlg.notes_family, str)     # a name, even fontless

    dlg2 = SettingsDialog(None, encrypted=False, idle_seconds=3,
                          font_size=12, notes_size=14)
    assert dlg2.notes_size == 14


def test_recent_limit_default_and_change(qapp):
    """The 'Recent list remembers' knob: defaults to 25, changeable,
    and the spin box clamps out-of-range values."""
    dlg = _dialog(qapp)
    assert dlg.recent_limit == 25          # the shipped default

    dlg = SettingsDialog(None, encrypted=False, idle_seconds=3,
                         font_size=12, recent_limit=40)
    assert dlg.recent_limit == 40          # remembered value honored
    dlg._recent_spin.setValue(60)
    assert dlg.recent_limit == 60
    dlg._recent_spin.setValue(1000)        # clamped by the 5..100 range
    assert dlg.recent_limit == 100
