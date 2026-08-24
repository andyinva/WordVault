"""
Tests for the personal-extensions hook (wordvault/editor/extensions.py):
files in the personal folder register against the window, a broken file
is skipped without harming the others, and no folder means no fuss.
Pure filesystem + import tests — no Qt required.
"""

from wordvault.editor import extensions


class FakeWindow:
    """Stands in for the main window; records what extensions do."""

    def __init__(self):
        self.buttons = []

    def add_extension_button(self, text, tooltip, callback):
        self.buttons.append((text, tooltip, callback))


def test_missing_folder_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "EXTENSIONS_DIR", tmp_path / "nowhere")
    assert extensions.load_extensions(FakeWindow()) == []


def test_extension_registers_a_button(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "EXTENSIONS_DIR", tmp_path)
    (tmp_path / "greeter.py").write_text(
        "def register(window):\n"
        "    window.add_extension_button('Hi', 'says hi', lambda: None)\n",
        encoding="utf-8")
    window = FakeWindow()
    assert extensions.load_extensions(window) == ["greeter"]
    assert window.buttons[0][:2] == ("Hi", "says hi")


def test_broken_extension_never_blocks_the_rest(tmp_path, monkeypatch, capsys):
    """One bad file must not take WordVault (or its neighbors) down."""
    monkeypatch.setattr(extensions, "EXTENSIONS_DIR", tmp_path)
    (tmp_path / "broken.py").write_text("this is ( not python",
                                        encoding="utf-8")
    (tmp_path / "working.py").write_text(
        "def register(window):\n    window.add_extension_button("
        "'Ok', 'ok', lambda: None)\n", encoding="utf-8")
    window = FakeWindow()
    assert extensions.load_extensions(window) == ["working"]
    assert "broken.py failed to load" in capsys.readouterr().err


def test_underscore_helpers_and_registerless_files_skipped(
        tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "EXTENSIONS_DIR", tmp_path)
    (tmp_path / "_helper.py").write_text(
        "raise RuntimeError('should never be imported')", encoding="utf-8")
    (tmp_path / "quiet.py").write_text("x = 1\n", encoding="utf-8")
    assert extensions.load_extensions(FakeWindow()) == []
