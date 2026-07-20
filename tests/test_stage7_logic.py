"""
Headless tests for stage 7's pure logic: line-age tracking and outline
parsing / section bounds.  (The pure functions live beside their Qt
widgets but import cleanly without a display; age_colors needs PyQt6
only for the QColor helpers, so its import is guarded.)
"""

import pytest

# Both modules live in the editor package and import PyQt6 at module
# level (for their widget/color halves), so the whole test file skips
# when PyQt6 is absent — the logic itself is display-free.
pytest.importorskip("PyQt6")

from wordvault.editor.age_colors import line_birth_indices  # noqa: E402
from wordvault.editor.outline import parse_outline, section_bounds  # noqa: E402


# -- age tracking ------------------------------------------------------------

def test_first_revision_all_lines_age_zero():
    assert line_birth_indices(["a\nb\nc\n"]) == [0, 0, 0]


def test_new_lines_get_new_age():
    texts = [
        "alpha\nbeta\n",
        "alpha\nbeta\ngamma\n",          # gamma born in revision 1
        "alpha\nBETA!\ngamma\ndelta\n",  # edit + another new line in rev 2
    ]
    assert line_birth_indices(texts) == [0, 2, 1, 2]


def test_deleted_lines_do_not_confuse_ages():
    texts = [
        "one\ntwo\nthree\n",
        "one\nthree\n",          # 'two' deleted; survivors keep age 0
    ]
    assert line_birth_indices(texts) == [0, 0]


def test_empty_history():
    assert line_birth_indices([]) == []
    assert line_birth_indices([""]) == []


# -- outline -----------------------------------------------------------------

DOC = """Introduction text before any heading.

# Chapter One
Text of chapter one.

## Section A
Text of section A.

## Section B
Text of section B.

# Chapter Two
Closing text.
"""


def test_parse_outline_levels_and_lines():
    outline = parse_outline(DOC)
    assert [(lvl, title) for lvl, title, _ in outline] == [
        (1, "Chapter One"), (2, "Section A"), (2, "Section B"), (1, "Chapter Two"),
    ]
    # Line numbers point at the heading lines themselves.
    assert DOC.split("\n")[outline[0][2]] == "# Chapter One"


def test_parse_outline_ignores_non_headings():
    assert parse_outline("no headings here\njust prose\n") == []
    assert parse_outline("#not a heading (no space)\n") == []


def test_section_bounds_inside_subsection():
    lines = DOC.split("\n")
    line_in_a = next(i for i, l in enumerate(lines) if l == "Text of section A.")
    first, last = section_bounds(DOC, line_in_a)
    assert lines[first] == "## Section A"
    # Section A ends just before Section B's heading.
    assert lines[last + 1] == "## Section B"


def test_section_bounds_chapter_spans_subsections():
    lines = DOC.split("\n")
    ch1 = next(i for i, l in enumerate(lines) if l == "# Chapter One")
    first, last = section_bounds(DOC, ch1)
    assert first == ch1
    assert lines[last + 1] == "# Chapter Two"   # swallows both subsections


def test_section_bounds_leading_text():
    first, last = section_bounds(DOC, 0)
    assert first == 0
    assert DOC.split("\n")[last + 1] == "# Chapter One"


def test_section_bounds_no_headings():
    text = "plain\nprose\nonly\n"
    assert section_bounds(text, 1) == (0, 3)   # whole text, one section
