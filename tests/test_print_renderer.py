"""
Offscreen tests for the Markdown -> styled-document print renderer.

The document never reaches a screen; these tests inspect the styled
blocks directly — the same structures the printer receives.
"""

import os
from pathlib import Path

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


BYLINE_FORMAT = FORMAT + """
[byline]
text = "{author} — printed {date}"
italic = true
align = "center"
"""


def test_byline_follows_first_heading(qapp, tmp_path):
    path = tmp_path / "b.wvfmt"
    path.write_text(BYLINE_FORMAT, encoding="utf-8")
    document = build_print_document(
        MARKDOWN, load_format(path),
        title="My Essay", author="Andrew Hopkins", date_str="July 25, 2026",
    )
    lines = [b.text() for b in get_blocks(document)]
    assert lines[0] == "Chapter One"
    assert lines[1] == "Andrew Hopkins — printed July 25, 2026"
    byline_block = get_blocks(document)[1]
    assert byline_block.blockFormat().alignment() & Qt.AlignmentFlag.AlignHCenter
    assert first_run_font(byline_block).italic()


def test_byline_leads_headingless_document(qapp, tmp_path):
    path = tmp_path / "b2.wvfmt"
    path.write_text(BYLINE_FORMAT, encoding="utf-8")
    document = build_print_document(
        "Just plain prose here.\n", load_format(path),
        author="A. H.", date_str="today",
    )
    lines = [b.text() for b in get_blocks(document)]
    assert lines[0] == "A. H. — printed today"
    assert lines[1] == "Just plain prose here."


def test_expand_fills_variables():
    from wordvault.printing.renderer import _expand
    out = _expand("Page {page} of {pages} — {title}",
                  {"page": 3, "pages": 12, "title": "Essay"})
    assert out == "Page 3 of 12 — Essay"
    # Unknown variables pass through untouched (load-time validation is
    # the real guard; expansion never crashes mid-print).
    assert _expand("{mystery}", {}) == "{mystery}"


def _pdf_text_ops(pdf_path):
    """Count text-showing operators (Tj/TJ) inside a PDF's content
    streams — the ground truth of whether anything was DRAWN.  Document
    objects can look perfect while the page prints blank (the invisible
    -text bug this guards against), so tests must read the output."""
    import re as _re
    import zlib

    data = pdf_path.read_bytes()
    count = 0
    for match in _re.finditer(rb"stream\r?\n(.*?)endstream", data, _re.S):
        payload = match.group(1)
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            pass
        count += len(_re.findall(rb"T[jJ]", payload))
    return count


#: Runs in a SUBPROCESS on the NATIVE platform (not offscreen): Qt's
#: offscreen plugin on Windows has no fonts at all, so nothing can be
#: drawn there and the test would be blind.  argv: repo, fmt, out, md.
_NATIVE_PRINT_SCRIPT = """
import sys
sys.path.insert(0, sys.argv[1])
from PyQt6.QtWidgets import QApplication
from PyQt6.QtPrintSupport import QPrinter
from wordvault.printing.format_file import load_format
from wordvault.printing.renderer import print_styled
app = QApplication([])
fmt = load_format(sys.argv[2])
printer = QPrinter(QPrinter.PrinterMode.HighResolution)
printer.setOutputFileName(sys.argv[3])
markdown = open(sys.argv[4], encoding="utf-8").read()
print_styled(printer, markdown, fmt, title="T", author="A")
"""


def test_manual_pagination_actually_draws_the_body(tmp_path):
    """Print through the MANUAL pagination path (furniture forces it) to
    a real PDF — with real fonts, in a native-platform subprocess — then
    verify the body text was drawn, not just the header and footer."""
    import os
    import subprocess
    import sys

    repo = Path(__file__).resolve().parent.parent
    fmt_path = tmp_path / "furn.wvfmt"
    fmt_path.write_text(FORMAT + '\n[footer]\ncenter = "{page}"\n',
                        encoding="utf-8")
    md_path = tmp_path / "doc.md"
    md_path.write_text(MARKDOWN, encoding="utf-8")
    out = tmp_path / "out.pdf"

    assert load_format(fmt_path).needs_manual_pagination()

    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)   # native platform: real fonts
    proc = subprocess.run(
        [sys.executable, "-c", _NATIVE_PRINT_SCRIPT,
         str(repo), str(fmt_path), str(out), str(md_path)],
        env=env, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.skip("native-platform printing unavailable here: "
                    + proc.stderr.strip()[-200:])

    assert out.exists() and out.stat().st_size > 1000
    ops = _pdf_text_ops(out)
    # Two pages of prose plus footers: dozens of text ops.  A furniture-
    # only print (the invisible-body bug) produced one or two per page.
    assert ops > 10, f"only {ops} text-draw ops — body not rendered"


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
