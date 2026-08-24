"""
Tests for .wvfmt loading and validation (Qt-free — runs everywhere).
"""

import pytest

import wordvault.printing.format_file as ff
from wordvault.printing.format_file import (
    FormatError,
    ensure_default_formats,
    list_formats,
    load_format,
)

GOOD = """
[format]
name = "Test Format"

[page]
size = "A4"
margins_mm = [20, 15, 20, 15]

[body]
font = "Georgia"
size_pt = 12
align = "justify"
line_spacing = 1.5

[heading1]
size_pt = 22
bold = true
align = "center"
page_break_before = true

[quote]
italic = true
indent_mm = 10
"""


def write(tmp_path, text, name="t.wvfmt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_format(tmp_path):
    fmt = load_format(write(tmp_path, GOOD))
    assert fmt.name == "Test Format"
    assert fmt.page_size == "A4"
    # Legacy margins_mm shorthand: [top, right, bottom, left], not mirrored.
    assert not fmt.margins.mirrored
    assert fmt.margins.for_page(0) == (20.0, 15.0, 20.0, 15.0)
    assert fmt.margins.for_page(1) == fmt.margins.for_page(0)  # every page
    assert fmt.body.size_pt == 12 and fmt.body.align == "justify"


MIRRORED = """
[format]
name = "Book"

[page]
size = "Letter"

[page.margins]
unit = "in"
top = 0.7
bottom = 0.5
inside = 1.2
outside = 0.7
gutter = 0.1
"""


def test_mirror_margins_word_style(tmp_path):
    fmt = load_format(write(tmp_path, MIRRORED))
    m = fmt.margins
    assert m.mirrored
    # Inches converted to millimetres.
    assert m.top == pytest.approx(0.7 * 25.4)
    assert m.inside == pytest.approx(1.2 * 25.4)
    assert m.gutter == pytest.approx(0.1 * 25.4)

    spine = m.inside + m.gutter
    # Page 1 (index 0) is a RIGHT-hand page: spine margin on its left.
    top, right, bottom, left = m.for_page(0)
    assert left == pytest.approx(spine)
    assert right == pytest.approx(m.outside)
    # Page 2 mirrors: spine on its right.
    top, right, bottom, left = m.for_page(1)
    assert right == pytest.approx(spine)
    assert left == pytest.approx(m.outside)
    # Text width deduction is constant, so layout never reflows.
    assert m.text_width_deduction() == pytest.approx(spine + m.outside)


def test_normal_margins_table_in_mm(tmp_path):
    fmt = load_format(write(
        tmp_path,
        "[page.margins]\ntop = 30\nbottom = 30\nleft = 22\nright = 18\n",
        "n1.wvfmt",
    ))
    assert not fmt.margins.mirrored
    assert fmt.margins.for_page(0) == (30.0, 18.0, 30.0, 22.0)


FURNISHED = """
[format]
name = "Furnished"

[header]
center = "{title}"
italic = true
size_pt = 8.5

[footer]
left = "{author}"
center = "Page {page} of {pages}"

[byline]
text = "{author} — {date}"
align = "center"
italic = true
"""


def test_furniture_and_byline_parse(tmp_path):
    fmt = load_format(write(tmp_path, FURNISHED, "furn.wvfmt"))
    assert fmt.header.wanted() and fmt.header.center == "{title}"
    assert fmt.header.italic and fmt.header.size_pt == 8.5
    assert fmt.footer.left == "{author}"
    assert fmt.byline_text == "{author} — {date}"
    style = fmt.style_for_byline()
    assert style.italic and style.align == "center"
    assert style.font == "Georgia"       # inherits from body defaults
    # Furniture forces manual pagination even without mirror margins.
    assert fmt.needs_manual_pagination()


def test_duplex_key(tmp_path):
    """[page] duplex: the format itself asks for two-sided printing;
    absent = false; non-boolean = a named error."""
    fmt = load_format(write(tmp_path, "[page]\nduplex = true\n", "d.wvfmt"))
    assert fmt.duplex is True
    assert load_format(write(tmp_path, GOOD)).duplex is False
    with pytest.raises(FormatError, match="duplex must be"):
        load_format(write(tmp_path, "[page]\nduplex = 'yes'\n", "db.wvfmt"))


def test_essay_draft_ships_and_saves_paper(tmp_path, monkeypatch):
    """The Essay Draft master: half-inch margins, duplex, small body
    type with heading sizes descending — checked STRUCTURALLY, not by
    exact point sizes, because the author tunes this format's numbers
    by hand (9pt body as of Aug 2026) and the master is his spec."""
    monkeypatch.setattr(ff, "FORMATS_DIR", tmp_path / "formats")
    ensure_default_formats()
    draft = next(f for f in list_formats() if f.name == "Essay Draft")
    fmt = load_format(draft.path)
    assert fmt.duplex is True
    assert fmt.margins.for_page(0) == tuple(pytest.approx(0.5 * 25.4)
                                            for _ in range(4))
    assert fmt.body.size_pt <= 10             # the paper-saver promise
    h1, h2, h3 = (fmt.style_for_heading(n) for n in (1, 2, 3))
    assert h1.size_pt > h2.size_pt > h3.size_pt >= fmt.body.size_pt
    assert h1.bold and h2.bold and h3.bold
    assert fmt.footer.center == "{page} of {pages}"
    assert fmt.needs_manual_pagination()      # furniture drives it


def test_6x9_kdp_trim_size_accepted(tmp_path):
    fmt = load_format(write(
        tmp_path, "[page]\nsize = '6x9'\n", "kdp.wvfmt"))
    assert fmt.page_size == "6x9"


def test_plain_format_needs_no_manual_pagination(tmp_path):
    fmt = load_format(write(tmp_path, GOOD))
    assert not fmt.needs_manual_pagination()


@pytest.mark.parametrize("bad,fragment", [
    ("[footer]\ncenter = '{pgae}'\n", "unknown variable"),
    ("[byline]\ntext = 'p. {page}'\n", "unknown variable"),
    ("[byline]\nitalic = true\n", "needs a 'text'"),
    ("[header]\nmiddle = 'x'\n", "unknown key"),
    ("[page.margins]\nleft = 20\ninside = 30\n", "not both"),
    ("[page.margins]\ngutter = 5\nleft = 20\n", "gutter only applies"),
    ("[page.margins]\nunit = 'cm'\n", "must be 'mm' or 'in'"),
    ("[page.margins]\ntop = -5\n", "non-negative"),
    ("[page.margins]\nspine = 12\n", "unknown key"),
    ("[page]\nmargins_mm = [1,2,3,4]\n\n[page.margins]\ntop = 5\n",
     "not both"),
])
def test_margin_validation_errors(tmp_path, bad, fragment):
    with pytest.raises(FormatError, match=fragment):
        load_format(write(tmp_path, bad, "bad_m.wvfmt"))


def test_styles_inherit_from_body(tmp_path):
    fmt = load_format(write(tmp_path, GOOD))
    h1 = fmt.style_for_heading(1)
    assert h1.size_pt == 22 and h1.bold and h1.align == "center"
    assert h1.font == "Georgia"          # inherited from body
    assert h1.line_spacing == 1.5        # inherited from body

    quote = fmt.style_for_quote()
    assert quote.italic and quote.indent_mm == 10
    assert quote.size_pt == 12           # inherited


def test_missing_heading_falls_back_to_shallower(tmp_path):
    fmt = load_format(write(tmp_path, GOOD))
    # heading3 undefined: uses heading1's style (nearest shallower).
    assert fmt.style_for_heading(3).size_pt == 22
    # A format with no headings at all still prints them sensibly.
    bare = load_format(write(tmp_path, "[body]\nsize_pt = 10\n", "bare.wvfmt"))
    derived = bare.style_for_heading(2)
    assert derived.bold and derived.size_pt == pytest.approx(12.0)


def test_defaults_when_sections_missing(tmp_path):
    fmt = load_format(write(tmp_path, "[format]\nname = 'Minimal'\n"))
    assert fmt.page_size == "Letter"
    assert fmt.body.font == "Georgia" and fmt.body.size_pt == 11.0


@pytest.mark.parametrize("bad,fragment", [
    ("[body]\nsize_pt = 'big'\n", "must be a number"),
    ("[body]\nalign = 'middle'\n", "align must be"),
    ("[body]\ncolour = 'red'\n", "unknown key"),
    ("[margins]\n", "unknown section"),
    ("[page]\nsize = 'Tabloid'\n", "not supported"),
    ("[page]\nmargins_mm = [1, 2]\n", "four numbers"),
    ("not toml at all ===", "not valid TOML"),
])
def test_validation_errors_name_the_problem(tmp_path, bad, fragment):
    with pytest.raises(FormatError, match=fragment):
        load_format(write(tmp_path, bad))


def test_ensure_defaults_and_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(ff, "FORMATS_DIR", tmp_path / "formats")
    ensure_default_formats()
    names = {f.name for f in list_formats()}
    assert {"Essay", "Book Chapter", "Manuscript (double-spaced)"} <= names

    # The author's edits survive re-seeding.
    essay = ff.FORMATS_DIR / "essay.wvfmt"
    essay.write_text("[format]\nname = 'My Essay'\n", encoding="utf-8")
    ensure_default_formats()
    assert "My Essay" in {f.name for f in list_formats()}

    # Invalid files are skipped by the chooser list, not fatal.
    (ff.FORMATS_DIR / "broken.wvfmt").write_text("[[[", encoding="utf-8")
    assert "broken" not in {f.name.lower() for f in list_formats()}


def test_untouched_copies_auto_upgrade_edited_ones_never(tmp_path, monkeypatch):
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "a.wvfmt").write_text("[format]\nname = 'A v1'\n")
    (shipped / "b.wvfmt").write_text("[format]\nname = 'B v1'\n")
    monkeypatch.setattr(ff, "_SHIPPED_DIR", shipped)
    monkeypatch.setattr(ff, "FORMATS_DIR", tmp_path / "user")
    ensure_default_formats()

    # The author edits their copy of B; A stays untouched.
    (ff.FORMATS_DIR / "b.wvfmt").write_text("[format]\nname = 'B mine'\n")

    # A new WordVault version ships improved masters.
    (shipped / "a.wvfmt").write_text("[format]\nname = 'A v2'\n")
    (shipped / "b.wvfmt").write_text("[format]\nname = 'B v2'\n")
    ensure_default_formats()

    names = {f.name for f in list_formats()}
    assert "A v2" in names           # untouched copy: auto-upgraded
    assert "B mine" in names         # edited copy: the author's, forever
    assert "B v2" not in names
