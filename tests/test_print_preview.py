"""
Regression test for Print Preview: the preview widget must actually
produce pages.  The original wiring reconfigured the printer (page
setup, setFullPage) INSIDE the paintRequested slot, which blanks
Qt's preview engine — Andrew saw an all-gray window.  The rule now:
page_setup_for_preview configures everything up front, and the render
call runs with configure=False, painting only.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.printing.format_file import load_format  # noqa: E402
from wordvault.printing.renderer import (  # noqa: E402
    page_setup_for_preview,
    print_styled,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _preview_pages(qapp, fmt, text):
    from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewWidget

    printer = QPrinter()
    page_setup_for_preview(printer, fmt)
    widget = QPrintPreviewWidget(printer)
    widget.paintRequested.connect(
        lambda p: print_styled(p, text, fmt, title="Essay",
                               author="Andrew", configure=False))
    widget.updatePreview()
    qapp.processEvents()
    return widget.pageCount()


def test_simple_format_preview_shows_pages(qapp):
    fmt = load_format("formats/essay.wvfmt")
    text = "# Heading\n\n" + ("Body words flow here. " * 60 + "\n\n") * 12
    assert _preview_pages(qapp, fmt, text) > 1


def test_furnished_format_preview_shows_pages(qapp):
    """A format with headers/footers takes the manual-pagination path
    (print_book) — it must also preview, not blank."""
    fmt = load_format("formats/essay-draft.wvfmt")
    assert fmt.needs_manual_pagination()   # headers/footers present
    text = ("## Section\n\n"
            + ("Draft words to proof on screen. " * 50 + "\n\n") * 10)
    assert _preview_pages(qapp, fmt, text) >= 1


def test_print_dialog_page_ranges_are_honored(qapp, tmp_path):
    """Choosing 'Pages: 1' in the print dialog used to print the whole
    document — the manual paginator never consulted the printer's page
    ranges.  Now a ranged print emits exactly the asked-for pages."""
    import re

    from PyQt6.QtGui import QPageRanges
    from PyQt6.QtPrintSupport import QPrinter

    fmt = load_format("formats/essay-draft.wvfmt")
    assert fmt.needs_manual_pagination()
    text = "## Section\n\n" + ("Range test words. " * 60 + "\n\n") * 30

    def page_count(ranges=None):
        path = str(tmp_path / f"r{id(ranges)}.pdf")
        printer = QPrinter()
        printer.setOutputFileName(path)
        if ranges is not None:
            printer.setPageRanges(ranges)
        print_styled(printer, text, fmt, title="T", author="A")
        data = open(path, "rb").read()
        return len(re.findall(rb"/Type\s*/Page[^s]", data))

    everything = page_count()
    assert everything > 3
    one = QPageRanges()
    one.addPage(1)
    assert page_count(one) == 1
    pair = QPageRanges()
    pair.addRange(2, 3)
    assert page_count(pair) == 2
