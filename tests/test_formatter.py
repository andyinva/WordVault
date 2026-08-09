"""
Qt-free tests for the Formatter's model and assembly logic — the
BookProject file round trip and the chapter-markdown rules.  These run
on any machine, with or without PyQt6.
"""

import dataclasses

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
