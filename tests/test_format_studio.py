"""
Tests for the Format Studio (wordvault/printing/studio.py): the
settings column must faithfully round-trip a format — load a .wvfmt
into the widgets, serialize it back, and the reloaded format must
say the same things.  Also: an edit through a widget lands in the
saved file, and validation refuses to save nonsense.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.printing.format_file import load_format  # noqa: E402
from wordvault.printing.studio import FormatStudio  # noqa: E402

SOURCE = """
[format]
name = "Studio Test"

[page]
size = "6x9"
duplex = true

[page.margins]
unit = "mm"
top = 18
bottom = 13
left = 30
right = 18

[body]
font = "Georgia"
size_pt = 11
align = "justify"
line_spacing = 1.25
space_after_pt = 10

[heading1]
size_pt = 17
bold = true

[quote]
italic = true
indent_mm = 6

[footer]
center = "{page} of {pages}"
size_pt = 9

[byline]
text = "by {author}"
"""


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def studio(qapp, tmp_path):
    path = tmp_path / "studio-test.wvfmt"
    path.write_text(SOURCE, encoding="utf-8")
    s = FormatStudio(path)
    yield s, path
    s.close()


def test_round_trip_preserves_the_format(studio, tmp_path):
    s, _path = studio
    out = tmp_path / "out.wvfmt"
    out.write_text(s.serialized(), encoding="utf-8")
    fmt = load_format(out)
    assert fmt.name == "Studio Test"
    assert fmt.page_size == "6x9"
    assert fmt.duplex is True
    top, right, _b, left = fmt.margins.for_page(0)
    assert top == pytest.approx(18) and left == pytest.approx(30)
    assert fmt.body.font == "Georgia"
    assert fmt.body.size_pt == pytest.approx(11)
    assert fmt.body.align == "justify"
    assert fmt.body.line_spacing == pytest.approx(1.25)
    assert fmt.body.space_after_pt == pytest.approx(10)
    h1 = fmt.style_for_heading(1)
    assert h1.size_pt == pytest.approx(17) and h1.bold
    assert fmt.style_for_quote().italic
    assert fmt.footer.center == "{page} of {pages}"
    assert fmt.byline_text == "by {author}"


def test_a_widget_edit_lands_in_the_saved_file(studio):
    s, path = studio
    s._controls[("body", "size_pt")].setValue(12.5)
    s._controls[("body", "line_height_pt")].setValue(15.0)
    s._save()
    fmt = load_format(path)
    assert fmt.body.size_pt == pytest.approx(12.5)
    assert fmt.body.line_height_pt == pytest.approx(15.0)


def test_invalid_edit_is_not_saved(studio):
    s, path = studio
    before = path.read_text(encoding="utf-8")
    s._controls[("body", "line_height_pt")].setValue(2.0)  # below 4pt
    s._save()
    assert path.read_text(encoding="utf-8") == before
    assert "Not saved" in s._status.text()
