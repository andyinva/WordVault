"""
Offscreen tests for the Markdown -> styled-document print renderer.

The document never reaches a screen; these tests inspect the styled
blocks directly — the same structures the printer receives.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QTextBlockFormat  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.printing.format_file import load_format  # noqa: E402
from wordvault.printing.renderer import build_print_document  # noqa: E402

FORMAT = """
[format]
name = "T"
[body]
size_pt = 11
align = "justify"
[heading1]
size_pt = 20
bold = true
align = "center"
page_break_before = true
[quote]
italic = true
indent_mm = 10
"""

MARKDOWN = """# Chapter One

First paragraph line one
continues on a second source line.

> A quotation here.

- first item
- second item

1. alpha
1. beta

# Chapter Two

Closing words with **bold** inside.
"""


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def document(qapp, tmp_path):
    """The rendered document itself.  IMPORTANT: tests must hold the
    DOCUMENT, not bare QTextBlock handles — blocks are views into the
    document's memory, and letting the document be garbage-collected
    while keeping blocks caused a genuine heap-corruption crash."""
    path = tmp_path / "t.wvfmt"
    path.write_text(FORMAT, encoding="utf-8")
    return build_print_document(MARKDOWN, load_format(path))


def get_blocks(document):
    out = []
    block = document.firstBlock()
    while block.isValid():
        out.append(block)
        block = block.next()
    return out


def texts(document):
    return [b.text() for b in get_blocks(document)]


def first_run_font(block):
    """The font of the block's FIRST text fragment — what the printer
    actually renders.  (block.charFormat() is only the block's baseline
    format, a different thing — the source of an earlier test bug.)"""
    iterator = block.begin()
    return iterator.fragment().charFormat().font()


def test_structure_and_paragraph_joining(document):
    assert texts(document) == [
        "Chapter One",
        "First paragraph line one continues on a second source line.",
        "A quotation here.",
        "•  first item",
        "•  second item",
        "1.  alpha",
        "2.  beta",              # renumbered sequentially
        "Chapter Two",
        "Closing words with bold inside.",   # markers consumed, not printed
    ]


def test_heading_styling_and_page_breaks(document):
    blocks = get_blocks(document)
    first, second = blocks[0], blocks[7]
    assert first.blockFormat().alignment() & Qt.AlignmentFlag.AlignHCenter
    # First block must NOT force a leading blank page...
    assert first.blockFormat().pageBreakPolicy() == \
        QTextBlockFormat.PageBreakFlag.PageBreak_Auto
    # ...but the second chapter starts a fresh page.
    assert second.blockFormat().pageBreakPolicy() == \
        QTextBlockFormat.PageBreakFlag.PageBreak_AlwaysBefore
    assert first_run_font(first).pointSizeF() == pytest.approx(20.0)
    assert first_run_font(first).bold()


def test_quote_indent_and_italic(document):
    quote = get_blocks(document)[2]
    assert quote.blockFormat().leftMargin() > 20     # 10mm in points
    assert first_run_font(quote).italic()


def test_inline_bold_run(document):
    closing = get_blocks(document)[8]
    it = closing.begin()
    weights = []
    while not it.atEnd():
        frag = it.fragment()
        weights.append((frag.text(), frag.charFormat().font().bold()))
        it += 1
    assert ("bold", True) in weights
    assert any(not bold for _t, bold in weights)     # body stays regular
