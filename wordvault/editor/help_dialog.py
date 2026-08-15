"""
help_dialog.py — the Help window (F1) and the User Guide (Shift+F1).

Renders a Markdown document from docs/: help.md is the quick
two-part orientation, guide.md the complete User Guide — philosophy
first, then every feature in detail.  Both are ordinary Markdown in
the repository, so contributors can improve them without touching any
code.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QPushButton, QTextBrowser, QVBoxLayout

#: repo_root/docs/  (this file is wordvault/editor/help_dialog.py)
_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
_HELP_FILE = _DOCS_DIR / "help.md"
_GUIDE_FILE = _DOCS_DIR / "guide.md"
_UPDATES_FILE = _DOCS_DIR / "updating.md"

_FALLBACK = (
    "# WordVault Help\n\nThe help document (docs/help.md) was not found "
    "next to the program.\n\nIn short: WordVault records a revision every "
    "time you pause typing; the History bar under the editor moves through "
    "them; Ctrl+Shift+F searches the whole library; Ctrl+M marks passages "
    "to gather into new documents; and the Settings button can encrypt "
    "your library."
)


def installation_email_text() -> str:
    """The share-with-a-friend email: plain text, ready to paste.
    Written for a friend who may never have installed a Python
    program before."""
    from wordvault import REPO_URL, TAGLINE, __version__

    return f"""\
I've been using a free, open-source writing program called WordVault
({TAGLINE.lower()}) and thought of you.

What makes it different: it quietly keeps EVERY draft of everything
you write. Stop typing for a moment and that state is saved forever —
you can slide back through a document's whole history, compare drafts,
and never lose a paragraph again. It also searches your entire body of
writing at once, and can even assemble essays into a print-ready book.

To install it (about ten minutes):

ON WINDOWS
1. Install Python from https://www.python.org/downloads/
   — during setup, tick the box "Add Python to PATH".
2. Download WordVault {__version__}:
   {REPO_URL}
   Click the green "Code" button, then "Download ZIP", and unzip it
   somewhere easy, like Documents\\WordVault.
3. Open a Command Prompt in that folder and run these two lines:
   pip install PyQt6 pyspellchecker qrcode
   python -m wordvault

ON UBUNTU LINUX
   sudo apt install python3-pip
   pip3 install PyQt6 pyspellchecker qrcode
   python3 -m wordvault

That's it — WordVault creates its library on first start. Help is
built in: press F1 for a quick orientation, Shift+F1 for the full
User Guide (it explains the thinking, not just the buttons).

Your writing stays on your own computer, in one file you can back up.
No account, no subscription, nothing phones home.
"""


class ShareDialog(QDialog):
    """Help > Share WordVault: the installation email, with a
    one-click Copy so it can be pasted straight to a friend."""

    def __init__(self, parent=None):
        from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPlainTextEdit

        super().__init__(parent)
        self.setWindowTitle("Share WordVault with a Friend")
        self.resize(640, 620)

        self._text = QPlainTextEdit(self)
        self._text.setPlainText(installation_email_text())
        self._text.setReadOnly(True)

        copy_btn = QPushButton("&Copy to Clipboard", self)

        def copy():
            QApplication.clipboard().setText(self._text.toPlainText())
            copy_btn.setText("Copied — paste it into an email")

        copy_btn.clicked.connect(copy)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(copy_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(self._text)
        layout.addLayout(buttons)


class HelpDialog(QDialog):
    """A read-only viewer for a Markdown help document.  Defaults to
    the quick help; pass document=_GUIDE_FILE for the full guide."""

    def __init__(self, parent=None, *, document: Path | None = None,
                 title: str = "WordVault Help"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 680)

        viewer = QTextBrowser(self)
        viewer.setOpenExternalLinks(True)
        try:
            viewer.setMarkdown(
                (document or _HELP_FILE).read_text(encoding="utf-8"))
        except OSError:
            viewer.setMarkdown(_FALLBACK)

        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(viewer)
        layout.addWidget(close_btn)
