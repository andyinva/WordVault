"""
Suite-wide guards.

THE SETTINGS SHIELD: GUI tests drive the real MainWindow, whose
QSettings("WordVault", "WordVault") are the AUTHOR'S OWN registry
keys — the same ones the everyday program reads.  A test that toggles
Check Spelling off, or closes a window (saving layout), was silently
rewriting the author's real preferences: "the spelling check does not
remain on ... I have to turn it on every time" (Aug 2026) was pytest
itself, wiping the setting between sessions.

This autouse fixture snapshots every key before each test and puts
them all back afterwards, so tests may do anything to settings and
the author's real preferences survive untouched.
"""

import pytest


@pytest.fixture(autouse=True)
def _preserve_wordvault_settings():
    try:
        from PyQt6.QtCore import QSettings
    except ImportError:
        yield                      # no Qt here: nothing to protect
        return

    settings = QSettings("WordVault", "WordVault")
    saved = {key: settings.value(key) for key in settings.allKeys()}
    del settings
    yield
    settings = QSettings("WordVault", "WordVault")
    settings.clear()
    for key, value in saved.items():
        settings.setValue(key, value)
    settings.sync()
