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
pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

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


# -- changed-word spans (history view wash) ---------------------------------

def _spans(old, new):
    from wordvault.editor.age_colors import changed_word_spans
    return changed_word_spans(old, new)


def test_identical_texts_have_no_changed_spans():
    text = "The quick brown fox jumps.\n\nOver the lazy dog."
    assert _spans(text, text) == []


def test_one_reworded_word_is_washed():
    old = "The quick brown fox jumps."
    new = "The swift brown fox jumps."
    spans = _spans(old, new)
    assert len(spans) == 1
    start, end = spans[0]
    assert old[start:end] == "quick"


def test_deleted_sentence_is_washed_in_the_old_version():
    old = "Keep this. Drop all of this entirely. Keep that."
    new = "Keep this. Keep that."
    spans = _spans(old, new)
    washed = " ".join(old[s:e] for s, e in spans)
    assert "Drop all of this entirely." in washed
    assert "Keep this." not in washed


def test_adjacent_changes_merge_into_one_wash():
    old = "alpha beta gamma delta"
    new = "alpha X Y delta"
    spans = _spans(old, new)
    assert len(spans) == 1
    start, end = spans[0]
    assert old[start:end] == "beta gamma"


def test_farther_back_washes_more():
    """The user's own description of the feature: stepping farther
    back, more of the old page should carry the wash."""
    newest = "one two three four five six"
    mid = "one two three four CHANGED six"
    oldest = "one OLD three ALSO CHANGED six"
    area = lambda t: sum(e - s for s, e in _spans(t, newest))
    assert 0 < area(mid) < area(oldest)


# -- corresponding_line (view holds the passage across revisions) -----------

def _line(old, new, n):
    from wordvault.editor.age_colors import corresponding_line
    return corresponding_line(old, new, n)


def test_surviving_line_maps_to_its_twin():
    old = "aaa\nbbb\nwatched line\nddd"
    new = "NEW OPENING\nmore new\naaa\nbbb\nwatched line\nddd"
    # Two lines were added above: the watched line moved from 2 to 4.
    assert _line(old, new, 2) == 4
    assert new.splitlines()[_line(old, new, 2)] == "watched line"


def test_removed_lines_above_shift_the_map_up():
    old = "one\ntwo\nthree\nwatched\nfive"
    new = "one\nwatched\nfive"
    assert new.splitlines()[_line(old, new, 3)] == "watched"


def test_rewritten_line_maps_into_its_replacement():
    old = "same\nold wording here\nsame2"
    new = "same\ncompletely new words\nsame2"
    assert _line(old, new, 1) == 1


def test_deleted_line_lands_on_the_seam():
    old = "keep\ngone entirely\nkeep2"
    new = "keep\nkeep2"
    assert _line(old, new, 1) in (0, 1)   # nearest surviving ground


def test_out_of_range_and_empty_are_safe():
    assert _line("", "anything", 5) == 0
    assert _line("a\nb", "a\nb", 99) == 1
