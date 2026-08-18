"""
Qt-free tests for the Formatter's model and assembly logic — the
BookProject file round trip and the chapter-markdown rules.  These run
on any machine, with or without PyQt6.
"""

import dataclasses
import json

import pytest

from wordvault.formatter.book import (
    SECTION_KEYS,
    BookProject,
    BookProjectError,
    ChapterRef,
)
from wordvault.formatter.builder import (
    assemble_markdown,
    chapter_markdown,
    format_for_book,
)
from wordvault.printing.format_file import PrintFormat, StyleSpec


def make_project() -> BookProject:
    p = BookProject(title="Inside God's House", author="Andrew Hopkins",
                    format_name="Book Chapter")
    p.chapters = [ChapterRef("uuid-1", "The Holy Nation"),
                  ChapterRef("uuid-2", "The Glory That Excels")]
    p.sections["toc"] = True
    p.copyright.isbn = "978-1-4028-9462-6"
    p.copyright.year = "2026"
    return p


def test_project_round_trip(tmp_path):
    path = tmp_path / "book.wvbook"
    make_project().save(path)
    loaded = BookProject.load(path)
    assert loaded.title == "Inside God's House"
    assert [c.uuid for c in loaded.chapters] == ["uuid-1", "uuid-2"]
    assert loaded.chapters[1].title == "The Glory That Excels"
    assert loaded.sections["toc"] and not loaded.sections["copyright"]
    assert loaded.copyright.isbn == "978-1-4028-9462-6"
    assert loaded.copyright.rights == "All rights reserved."
    # Every known section key survives the trip, even the off ones.
    assert set(loaded.sections) == set(SECTION_KEYS)


@pytest.mark.parametrize("bad,fragment", [
    ("not json {{{", "not valid JSON"),
    ('{"title": "no marker"}', "missing the 'wordvault_book' marker"),
    ('{"wordvault_book": 99}', "newer WordVault"),
    ('{"wordvault_book": 1, "chapters": [{"title": "no uuid"}]}',
     "needs a 'uuid'"),
])
def test_load_errors_name_the_problem(tmp_path, bad, fragment):
    path = tmp_path / "bad.wvbook"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(BookProjectError, match=fragment):
        BookProject.load(path)


def test_chapter_markdown_trusts_existing_title():
    text = "# My Own Title\n\nBody prose.\n"
    assert chapter_markdown("Library Title", text).startswith("# My Own Title")


def test_chapter_markdown_inserts_missing_title():
    out = chapter_markdown("The Holy Nation", "Body starts immediately.")
    assert out.startswith("# The Holy Nation\n\n")
    assert "Body starts immediately." in out
    # A deeper heading is NOT a chapter title; the real one is inserted.
    out2 = chapter_markdown("Chapter", "## Subheading first\ntext")
    assert out2.startswith("# Chapter\n\n")


def test_assemble_joins_with_blank_lines():
    out = assemble_markdown([("A", "alpha text"), ("B", "# B\n\nbeta")])
    assert "# A\n\nalpha text\n\n\n# B\n\nbeta\n" == out


def test_format_for_book_forces_chapter_breaks():
    # An essay-ish format without page_break_before on heading1:
    fmt = PrintFormat(name="Essayish",
                      headings={1: StyleSpec(size_pt=20.0)})
    booked = format_for_book(fmt)
    assert booked.headings[1].page_break_before is True
    assert booked.headings[1].size_pt == 20.0     # other traits kept
    assert fmt.headings[1].page_break_before is None   # original untouched

    # Already book-ready: returned as-is (same object, no copying).
    ready = PrintFormat(name="Book", headings={
        1: StyleSpec(page_break_before=True)})
    assert format_for_book(ready) is ready


def test_format_for_book_handles_no_heading1_defined():
    fmt = PrintFormat(name="Bare")
    booked = format_for_book(fmt)
    assert booked.headings[1].page_break_before is True


def test_vocabulary_loading_both_forms(tmp_path):
    """The Word Index Creator's vocabulary.json works as-is: plain
    trigger lists, dict form with caps, and re: regex triggers."""
    from wordvault.formatter.indexes import load_vocabulary

    path = tmp_path / "vocab.json"
    path.write_text(json.dumps({
        "Abraham": ["Abraham", "Abram"],
        "Glory": {"triggers": ["glory"], "max": 1, "scope": "chapter"},
        "Cycles": {"triggers": ["re:\\bcycl(e|es|ical)\\b"]},
    }), encoding="utf-8")
    vocab = load_vocabulary(path)
    by_name = {e.headword: e for e in vocab}
    assert by_name["Abraham"].matches("Now ABRAM dwelt in the land")
    assert by_name["Glory"].max_count == 1
    assert by_name["Glory"].scope == "chapter"
    assert by_name["Cycles"].matches("a cyclical journey")
    # re: triggers are real regexes (searched, unanchored — same as the
    # original tool): word boundaries are the vocabulary author's tool.
    assert not by_name["Cycles"].matches("a bicycle")

    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(BookProjectError, match="headword"):
        load_vocabulary(bad)


def test_collect_index_entries_pages_and_caps():
    """The scan: scripture references gather their true pages in
    canonical shape; subject caps limit marked paragraphs per chapter
    (Andrew's max-2-per-chapter rule) and reset at the next chapter."""
    from wordvault.formatter.indexes import VocabEntry, collect_index_entries

    vocab = [VocabEntry("Glory", ["glory"], 2, "chapter"),
             VocabEntry("Moriah", ["Moriah"])]
    blocks = [
        ("Chapter One", 1, 1),
        ("The glory appears (Genesis 22:2).", 1, 0),
        ("More glory here.", 2, 0),
        ("Third glory mention is over the cap.", 3, 0),
        ("Mount Moriah again, and Genesis 22:2 too.", 3, 0),
        ("Chapter Two", 4, 1),
        ("Fresh chapter, fresh glory cap.", 4, 0),
        ("See 2 Chronicles 3:1 about Moriah.", 5, 0),
    ]
    scripture, subjects = collect_index_entries(blocks, vocab)

    # Scripture: same verse on two pages -> both pages, once each.
    genesis = scripture["Genesis"]
    (key,) = genesis.keys()
    assert key[3] == "22:2" and genesis[key] == [1, 3]
    assert scripture["2 Chronicles"][(3, 1, 1, "3:1")] == [5]

    # Subjects: chapter cap of 2 -> pages 1,2 kept, page 3 dropped,
    # chapter two starts a fresh count (page 4).
    assert subjects["Glory"] == [1, 2, 4]
    assert subjects["Moriah"] == [3, 5]


def test_resolve_chapters_reports_missing(tmp_path):
    """resolve_chapters pulls CURRENT text by uuid and names every
    chapter that has vanished from the library."""
    from wordvault import DocumentStore
    from wordvault.formatter.builder import resolve_chapters

    store = DocumentStore(tmp_path / "lib.db")
    doc = store.create_document("Chapter One")
    store.save_revision(doc.id, "# Chapter One\n\nFirst text.")
    store.save_revision(doc.id, "# Chapter One\n\nRevised text.")

    project = BookProject()
    project.chapters = [ChapterRef(doc.uuid, doc.title)]
    chapters = resolve_chapters(store, project)
    assert chapters == [("Chapter One", "# Chapter One\n\nRevised text.")]

    project.chapters.append(ChapterRef("gone-uuid", "Lost Chapter"))
    with pytest.raises(BookProjectError, match="Lost Chapter"):
        resolve_chapters(store, project)
    store.close()
