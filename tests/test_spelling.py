"""
Tests for the spelling module (non-GUI half).  Skipped when the optional
pyspellchecker package is absent.
"""

import pytest

pytest.importorskip("spellchecker")

from wordvault.editor.spelling import Spelling  # noqa: E402


@pytest.fixture(scope="module")
def spelling():
    return Spelling()   # loads the dictionary once for the whole module


def test_common_words_pass(spelling):
    assert not spelling.is_misspelled("beginning")
    assert not spelling.is_misspelled("Word")


def test_obvious_typo_is_flagged(spelling):
    assert spelling.is_misspelled("beginnning")


def test_bible_book_names_are_preseeded(spelling):
    # The user dictionary is seeded with the scripture module's books.
    assert not spelling.is_misspelled("Deuteronomy")
    assert not spelling.is_misspelled("Ecclesiastes")


def test_acronyms_and_numbers_skipped(spelling):
    assert not spelling.is_misspelled("KJV")
    assert not spelling.is_misspelled("v1")


def test_spans_locate_misspellings(spelling):
    line = "In the beginnning was the Wrod."
    spans = spelling.misspelled_spans(line)
    words = [line[a:b] for a, b in spans]
    assert "beginnning" in words and "Wrod" in words
    assert "the" not in words


def test_suggestions_offer_the_fix(spelling):
    assert "beginning" in spelling.suggestions("beginnning")
    # Capitalization mirrors the input.
    assert any(s[0].isupper() for s in spelling.suggestions("Beginnning"))


def test_classify_error_kinds():
    from wordvault.editor.spelling import classify_error

    assert classify_error("seperate", "separate") == ("vowel swap", "e->a")
    assert classify_error("becase", "because") == ("dropped letter", "u")
    assert classify_error("bein", "being") == ("dropped letter", "g")
    assert classify_error("happend", "happened") == ("dropped letter", "e")
    assert classify_error("teh", "the") == ("swapped letters", "he")
    assert classify_error("christain", "christian") == ("swapped letters", "ia")
    assert classify_error("wrod", "word") == ("swapped letters", "or")
    assert classify_error("bookes", "books") == ("added letter", "e")
    assert classify_error("strick", "struck") == ("vowel swap", "i->u")
    assert classify_error("worls", "world") == ("wrong letter", "s->d")
    assert classify_error("cat", "dog")[0] == "other"


def test_extract_corrections_finds_hand_fixes():
    from wordvault.editor.spelling import extract_corrections

    bad = {"seperate", "becase"}
    is_missp = lambda w: w.lower() in bad

    old = "We must seperate the two ideas becase they differ.\n"
    new = "We must separate the two ideas because they differ.\n"
    assert extract_corrections(old, new, is_missp) == [
        ("seperate", "separate"), ("becase", "because"),
    ]
    # Ordinary rewrites of well-spelled words are NOT corrections.
    old2 = "the kingdom concept grows\n"
    new2 = "the covenant concept grows\n"
    assert extract_corrections(old2, new2, is_missp) == []


def test_apply_correction_to_text():
    from wordvault.editor.spelling import apply_correction_to_text

    # Proper-noun correction (capitalized): used verbatim everywhere.
    text = "cave of Machpela. The Machpela field, and machpela again.\n"
    new, n = apply_correction_to_text(text, "Machpela", "Machpelah")
    assert n == 3
    assert new == ("cave of Machpelah. The Machpelah field, "
                   "and Machpelah again.\n")

    # Lowercase correction mirrors each occurrence's capitalization.
    text2 = "Becase of this, becase of that.\n"
    new2, n2 = apply_correction_to_text(text2, "becase", "because")
    assert n2 == 2 and new2 == "Because of this, because of that.\n"

    # Whole words only — no touching words that merely contain the typo.
    text3 = "the ark embarked\n"
    new3, n3 = apply_correction_to_text(text3, "ark", "arc")
    assert n3 == 1 and new3 == "the arc embarked\n"

    # Case-only differences are not corrections.
    assert apply_correction_to_text("word Word\n", "word", "Word") == \
        ("word Word\n", 0)


def test_add_to_dictionary_sticks(spelling, tmp_path, monkeypatch):
    import wordvault.editor.spelling as mod
    monkeypatch.setattr(mod, "_USER_DICT", tmp_path / "user.txt")

    fresh = Spelling()
    assert fresh.is_misspelled("Melchizedekian")
    fresh.add_to_dictionary("Melchizedekian")
    assert not fresh.is_misspelled("Melchizedekian")
    # Persisted: a new instance reads it back from the file.
    again = Spelling()
    assert not again.is_misspelled("Melchizedekian")
