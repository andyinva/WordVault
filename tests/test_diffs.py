"""
Tests for the delta engine (wordvault/storage/diffs.py).

The single property that matters:
    apply_delta(old, make_delta(old, new)) == new   for ALL strings.
These tests hammer that property on ordinary prose and on every edge case
that has historically broken diff/patch code: empty texts, missing trailing
newlines, unicode, repeated blank lines, and total rewrites.
"""

from wordvault.storage.diffs import apply_delta, make_delta


def roundtrip(old: str, new: str) -> None:
    """Assert the fundamental property for one (old, new) pair."""
    assert apply_delta(old, make_delta(old, new)) == new


def test_simple_edit():
    roundtrip("In the beginning\n", "In the beginning was the Word\n")


def test_append_paragraph():
    old = "First paragraph.\n"
    new = "First paragraph.\n\nSecond paragraph.\n"
    roundtrip(old, new)


def test_delete_middle():
    old = "one\ntwo\nthree\nfour\n"
    new = "one\nfour\n"
    roundtrip(old, new)


def test_identical_texts():
    text = "no change at all\n"
    roundtrip(text, text)


def test_empty_to_text_and_back():
    roundtrip("", "something appeared\n")
    roundtrip("something vanished\n", "")
    roundtrip("", "")


def test_no_trailing_newline():
    # splitlines(keepends=True) must preserve the missing final newline.
    roundtrip("ends without newline", "still ends without newline")
    roundtrip("had newline\n", "now does not")
    roundtrip("no newline", "gains one\n")


def test_unicode_content():
    old = "Ἐν ἀρχῇ ἦν ὁ λόγος\n"
    new = "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν\n"
    roundtrip(old, new)


def test_many_repeated_blank_lines():
    # Repeated identical lines are where autojunk heuristics misfire;
    # we disable autojunk, and this test proves the round trip anyway.
    old = "a\n\n\n\nb\n\n\n\nc\n"
    new = "a\n\n\nB\n\n\n\nc\nextra\n"
    roundtrip(old, new)


def test_total_rewrite():
    roundtrip("completely different\ntext here\n", "nothing survives\n")


def test_large_document_small_edit_is_compact():
    # The whole point of deltas: a small edit to a large document must
    # produce a payload far smaller than the document itself.
    old = "".join(f"line {i}\n" for i in range(500))
    new = old.replace("line 250\n", "line two-fifty edited\n")
    delta = make_delta(old, new)
    assert apply_delta(old, delta) == new
    assert len(delta) < len(new) / 10  # compact, not a hidden snapshot
