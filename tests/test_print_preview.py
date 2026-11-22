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


def test_preview_ink_is_black_in_dark_mode(qapp):
    """In dark mode the preview drew its text in the theme's pale gray
    on a white page: "so light that it can hardly be seen" (Nov 2026).
    Qt's preview replays a recording in which "black" was never written
    down, so the text took the window's own text colour.  ink_on_paper
    gives the preview black text colours whatever the theme."""
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewWidget

    from wordvault.printing.renderer import ink_on_paper

    fmt = load_format("formats/essay.wvfmt")
    text = "# Heading\n\n" + ("Body words flow here. " * 60 + "\n\n") * 6

    def dark_pixels(fix: bool) -> int:
        """How many near-black pixels the middle of the page holds."""
        printer = QPrinter()
        page_setup_for_preview(printer, fmt)
        widget = QPrintPreviewWidget(printer)
        if fix:
            ink_on_paper(widget)
        widget.paintRequested.connect(
            lambda p: print_styled(p, text, fmt, title="Essay",
                                   author="Andrew", configure=False))
        widget.resize(700, 900)
        widget.show()
        widget.updatePreview()
        for _ in range(20):
            qapp.processEvents()
        image = widget.grab().toImage()
        w, h = image.width(), image.height()
        # Only the middle of the picture: the page's drop shadow at
        # the edges is dark in every theme and must not be counted.
        return sum(
            QColor(image.pixel(x, y)).lightness() < 70
            for x in range(w // 4, 3 * w // 4, 2)
            for y in range(h // 4, 3 * h // 4, 2))

    # Dress the whole program in dark mode's pale text colour.
    original = qapp.palette()
    dark = QPalette(original)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text):
        dark.setColor(role, QColor("#e4e6e9"))
    qapp.setPalette(dark)
    try:
        assert dark_pixels(fix=False) == 0      # the fault, reproduced
        assert dark_pixels(fix=True) > 200      # the cure: real black ink
    finally:
        qapp.setPalette(original)               # leave other tests alone
