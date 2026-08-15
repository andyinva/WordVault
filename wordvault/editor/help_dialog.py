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

_FALLBACK = (
    "# WordVault Help\n\nThe help document (docs/help.md) was not found "
    "next to the program.\n\nIn short: WordVault records a revision every "
    "time you pause typing; the History bar under the editor moves through "
    "them; Ctrl+Shift+F searches the whole library; Ctrl+M marks passages "
    "to gather into new documents; and the Settings button can encrypt "
    "your library."
)


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
