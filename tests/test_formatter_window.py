"""
Offscreen tests for the Formatter window and the PDF build path.

The window tests drive the widget logic directly (no clicks needed);
the build test writes a real PDF through the manual-pagination
renderer.  Settings use a throwaway INI file, never the registry.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import wordvault.printing.format_file as ff  # noqa: E402
from wordvault import DocumentStore  # noqa: E402
from wordvault.formatter.book import BookProject, ChapterRef  # noqa: E402
from wordvault.formatter.builder import build_book_pdf  # noqa: E402
from wordvault.formatter.window import FormatterWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def store(tmp_path):
    s = DocumentStore(tmp_path / "lib.db")
    for title, text in [
        ("Preface", "A short preface."),
        ("The Holy Nation", "# The Holy Nation\n\nChapter text."),
        ("Appendix", "Closing matter."),
    ]:
        doc = s.create_document(title)
        s.save_revision(doc.id, text)
    yield s
    s.close()


@pytest.fixture()
def window(qapp, store, tmp_path, monkeypatch):
    # Personal formats seeded into a sandbox dir, not the user's real one.
    monkeypatch.setattr(ff, "FORMATS_DIR", tmp_path / "formats")
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    w = FormatterWindow(store, settings)
    yield w
    w.close()


def titles(list_widget):
    return [list_widget.item(i).text() for i in range(list_widget.count())]


def test_library_list_and_filter(window):
    assert titles(window._library_list) == \
        ["Preface", "The Holy Nation", "Appendix"]
    window._filter_edit.setText("holy")
    assert titles(window._library_list) == ["The Holy Nation"]
    window._filter_edit.setText("")
    assert len(titles(window._library_list)) == 3


def test_add_reorder_and_no_duplicates(window):
    window._library_list.setCurrentRow(0)          # Preface
    window._on_add_chapter()
    window._on_add_chapter()                       # again: quiet no-op
    window._library_list.setCurrentRow(1)          # The Holy Nation
    window._on_add_chapter()
    assert titles(window._chapter_list) == ["Preface", "The Holy Nation"]

    window._chapter_list.setCurrentRow(1)
    window._move_chapter(-1)
    assert titles(window._chapter_list) == ["The Holy Nation", "Preface"]
    window._move_chapter(-1)                       # at the top: no-op
    assert titles(window._chapter_list)[0] == "The Holy Nation"


def test_project_save_and_reapply(window, tmp_path):
    window._title_edit.setText("My Book")
    window._library_list.setCurrentRow(1)
    window._on_add_chapter()
    project = window._gather_project()
    path = tmp_path / "p.wvbook"
    project.save(path)

    reloaded = BookProject.load(path)
    window._chapter_list.clear()
    window._apply_project(reloaded)
    assert window._title_edit.text() == "My Book"
    assert titles(window._chapter_list) == ["The Holy Nation"]


def test_saving_project_syncs_book_tags(window, store, tmp_path):
    """Tags are the .wvbook's shadow in the library: stamped on save,
    lifted from ex-chapters, and cleaned up after a book rename."""
    window._title_edit.setText("My Book")
    window._library_list.setCurrentRow(0)          # Preface
    window._on_add_chapter()
    window._library_list.setCurrentRow(1)          # The Holy Nation
    window._on_add_chapter()
    window._project_path = tmp_path / "p.wvbook"
    window._on_save_project()

    def tagged(tag):
        return sorted(d.title for d in store.documents_with_tag(tag))

    assert tagged("Book: My Book") == ["Preface", "The Holy Nation"]

    # Drop a chapter; its tag goes at the next save.
    window._chapter_list.setCurrentRow(0)
    window._on_remove_chapter()
    window._on_save_project()
    assert tagged("Book: My Book") == ["The Holy Nation"]

    # Rename the book; the old tag vanishes, the new one appears.
    window._title_edit.setText("Renamed Book")
    window._on_save_project()
    assert tagged("Book: My Book") == []
    assert tagged("Book: Renamed Book") == ["The Holy Nation"]


def test_add_all_by_tag(window, store):
    docs = {d.title: d for d in store.list_documents()}
    store.add_tag(docs["Preface"].id, "Book: Test")
    store.add_tag(docs["Appendix"].id, "Book: Test")
    # One of them is already in the book: it must not double up.
    window._library_list.setCurrentRow(0)          # Preface
    window._on_add_chapter()
    assert window._add_documents_with_tag("Book: Test") == 1
    assert titles(window._chapter_list) == ["Preface", "Appendix"]


def test_create_draft_document(window, store, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    window._title_edit.setText("My Book")
    window._library_list.setCurrentRow(0)          # Preface
    window._on_add_chapter()
    window._library_list.setCurrentRow(1)          # The Holy Nation
    window._on_add_chapter()
    window._on_create_draft()

    drafts = [d for d in store.list_documents()
              if d.title.startswith("My Book — draft of ")]
    assert len(drafts) == 1
    text = store.get_text(store.latest_revision(drafts[0].id).id)
    # Both chapters, in order, each opening with its heading.
    assert text.index("# Preface") < text.index("# The Holy Nation")
    assert "Chapter text." in text and "A short preface." in text


def test_collect_headings_reports_true_pages(qapp, tmp_path):
    """The TOC's fact-gatherer: headings come back with the page the
    print layout ACTUALLY puts them on — a heading pushed past page
    one by 300 paragraphs must report a later page."""
    from wordvault.printing.format_file import load_format
    from wordvault.printing.renderer import (
        build_print_document,
        collect_headings,
    )

    fmt_path = tmp_path / "t.wvfmt"
    fmt_path.write_text("[body]\nsize_pt = 11\n", encoding="utf-8")
    fmt = load_format(fmt_path)

    filler = "\n\n".join(f"Paragraph {i} of the chapter." for i in range(300))
    markdown = ("# Chapter One\n\nShort.\n\n## Early Section\n\n"
                + filler + "\n\n# Chapter Two\n\nEnd.\n")
    document = build_print_document(markdown, fmt)
    headings = collect_headings(document, fmt)

    assert [(lvl, text) for lvl, text, _p in headings] == [
        (1, "Chapter One"), (2, "Early Section"), (1, "Chapter Two")]
    pages = [p for _l, _t, p in headings]
    assert pages[0] == 1 and pages[1] == 1
    assert pages[2] > 1                     # pushed deep by the filler
    assert pages == sorted(pages)           # pages never run backwards


def test_toc_section_in_front_matter(qapp):
    """The Contents page: fresh page after title/copyright, levels 1-2
    only, each line 'title <tab> page'."""
    from PyQt6.QtGui import QTextBlockFormat

    from wordvault.formatter.frontmatter import build_front_matter
    from wordvault.printing.format_file import PrintFormat

    project = BookProject(title="My Book", author="A. H.")
    project.sections["title_page"] = True
    project.sections["toc"] = True
    entries = [(1, "Chapter One", 1), (2, "A Section", 3),
               (1, "Chapter Two", 9), (3, "Too Deep", 4)]
    document = build_front_matter(PrintFormat(name="T"), project, entries)

    blocks = []
    block = document.firstBlock()
    while block.isValid():
        blocks.append(block)
        block = block.next()
    texts = [b.text() for b in blocks]

    contents_at = texts.index("Contents")
    assert blocks[contents_at].blockFormat().pageBreakPolicy() == \
        QTextBlockFormat.PageBreakFlag.PageBreak_AlwaysBefore
    assert texts[contents_at + 1:] == [
        "Chapter One\t1", "A Section\t3", "Chapter Two\t9"]  # no level 3
    # The section line is indented; chapter lines are not.
    assert blocks[contents_at + 2].blockFormat().leftMargin() > 0
    assert blocks[contents_at + 1].blockFormat().leftMargin() == 0


def test_front_matter_document(qapp):
    """Title page and copyright page as styled blocks: title large and
    centered, byline beneath, then the quiet copyright block opening
    on a FRESH page (the verso) with only the filled-in fields."""
    from PyQt6.QtGui import QTextBlockFormat

    from wordvault.formatter.frontmatter import build_front_matter
    from wordvault.printing.format_file import PrintFormat

    project = BookProject(title="My Book", author="Andrew Hopkins")
    fmt = PrintFormat(name="T")

    # Both sections off: no front matter at all.
    assert build_front_matter(fmt, project) is None

    project.sections["title_page"] = True
    project.sections["copyright"] = True
    project.copyright.isbn = "979-8-1234-5678-9"
    project.copyright.year = "2026"
    project.copyright.edition = ""          # empty: must not print
    document = build_front_matter(fmt, project)

    blocks = []
    block = document.firstBlock()
    while block.isValid():
        blocks.append(block)
        block = block.next()
    texts = [b.text() for b in blocks]

    assert texts[0] == "My Book"
    assert texts[1] == "By Andrew Hopkins"
    assert texts[2].startswith("© 2026 Andrew Hopkins. All rights")
    assert texts[3] == "ISBN 979-8-1234-5678-9"
    assert len(texts) == 4                  # no blank "edition" line
    # The copyright block starts the second page.
    assert blocks[2].blockFormat().pageBreakPolicy() == \
        QTextBlockFormat.PageBreakFlag.PageBreak_AlwaysBefore
    # And the title is display-sized, not body-sized.
    it = blocks[0].begin()
    assert it.fragment().charFormat().font().pointSizeF() == 24.0


def test_copyright_qr_image_and_caption(qapp, tmp_path):
    """The QR provenance mark: with include_qr on, the copyright page
    gains an image block and the explanatory caption; the payload the
    image encodes carries title/ISBN and the .wvfmt text."""
    pytest.importorskip("qrcode")

    import json

    from wordvault.formatter import frontmatter as fm
    from wordvault.printing.format_file import load_format

    fmt_path = tmp_path / "t.wvfmt"
    fmt_path.write_text("[format]\nname = 'QR Test'\n", encoding="utf-8")
    fmt = load_format(fmt_path)

    project = BookProject(title="My Book", author="A. H.")
    project.sections["copyright"] = True
    project.copyright.isbn = "979-8-1111-2222-3"
    project.copyright.include_qr = True

    payload = json.loads(fm._qr_payload(fmt, project))
    assert payload["title"] == "My Book"
    assert payload["isbn"] == "979-8-1111-2222-3"
    assert "name = 'QR Test'" in payload["wvfmt"]

    document = fm.build_front_matter(fmt, project)
    texts = []
    has_image = False
    block = document.firstBlock()
    while block.isValid():
        texts.append(block.text())
        it = block.begin()
        while not it.atEnd():
            if it.fragment().charFormat().isImageFormat():
                has_image = True
            it += 1
        block = block.next()
    assert has_image, "no QR image found on the copyright page"
    assert any(fm.QR_CAPTION[:30] in t for t in texts)

    # Round trip: the project file remembers the choice.
    path = tmp_path / "p.wvbook"
    project.save(path)
    assert BookProject.load(path).copyright.include_qr is True


def test_back_matter_document_structure(qapp, tmp_path):
    """The indexes as styled blocks: Scripture in canonical book order
    with verses numeric, Subject alphabetical, each index opening a
    fresh page — and a missing vocabulary is a named error."""
    from PyQt6.QtGui import QTextBlockFormat

    from wordvault.formatter.indexes import build_back_matter
    from wordvault.printing.format_file import PrintFormat

    project = BookProject(title="B")
    project.sections["scripture_index"] = True
    project.sections["subject_index"] = True
    project.vocabulary_path = str(tmp_path / "v.json")
    (tmp_path / "v.json").write_text(
        '{"Zeal": ["zeal"], "Ark": ["ark"]}', encoding="utf-8")

    blocks = [
        ("Chapter", 1, 1),
        ("The ark rested (Genesis 8:4). Full of zeal.", 2, 0),
        ("Matthew 24:31 sounds; the ark again.", 5, 0),
    ]
    document = build_back_matter(PrintFormat(name="T"), project, blocks)

    texts = []
    breaks = []
    block = document.firstBlock()
    while block.isValid():
        if block.text():
            texts.append(block.text())
            breaks.append(block.blockFormat().pageBreakPolicy())
        block = block.next()

    s = texts.index("Scripture Index")
    u = texts.index("Subject Index")
    assert s < u                                  # scripture first
    assert texts[s + 1] == "Genesis"              # canonical, not Matthew
    assert texts[s + 2] == "8:4 — 2"
    assert texts[s + 3] == "Matthew"
    assert texts[s + 4] == "24:31 — 5"
    assert texts[u + 1] == "Ark — 2, 5"           # alphabetical subjects
    assert texts[u + 2] == "Zeal — 2"
    # The Subject Index starts its own page.
    assert breaks[u] == QTextBlockFormat.PageBreakFlag.PageBreak_AlwaysBefore

    # Subject index without a vocabulary: a named, helpful error.
    project.vocabulary_path = ""
    from wordvault.formatter.book import BookProjectError
    with pytest.raises(BookProjectError, match="vocabulary"):
        build_back_matter(PrintFormat(name="T"), project, blocks)


def test_build_book_pdf_writes_a_real_pdf(qapp, store, tmp_path, monkeypatch):
    """End to end: project -> assembled markdown -> manual-pagination
    renderer -> a PDF on disk.  (Glyph-level checks live in the print
    renderer's native-platform test; here the whole pipeline must at
    least produce a plausible multi-page file without error.)"""
    monkeypatch.setattr(ff, "FORMATS_DIR", tmp_path / "formats")
    docs = {d.title: d for d in store.list_documents()}
    # KDP 6x9: custom trim size + mirror margins + footer, the whole
    # manual-pagination gauntlet in one format.
    project = BookProject(title="Assembled", author="A. H.",
                          format_name="KDP 6x9 Book")
    project.chapters = [
        ChapterRef(docs["Preface"].uuid, "Preface"),
        ChapterRef(docs["The Holy Nation"].uuid, "The Holy Nation"),
    ]
    out = tmp_path / "book.pdf"
    build_book_pdf(store, project, out)
    assert out.exists() and out.stat().st_size > 1000
    data = out.read_bytes()
    # Two chapters with forced page breaks: at least two pages.
    # (\b guard: '/Type /Pages' must not count as a page.)
    import re
    assert len(re.findall(rb"/Type /Page\b(?!s)", data)) >= 2
    # The paper is really 6x9 inches (432 x 648 pt).  Qt's writer is
    # free about MediaBox formatting — spacing and decimals vary by
    # platform — so parse the four numbers and allow 1 pt of rounding.
    box = re.search(
        rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]",
        data)
    assert box, "no MediaBox found in the PDF"
    width = float(box.group(3)) - float(box.group(1))
    height = float(box.group(4)) - float(box.group(2))
    assert abs(width - 432.0) < 1.0 and abs(height - 648.0) < 1.0, \
        f"expected 6x9in (432x648pt) paper, got {width}x{height}pt"


def test_build_with_front_matter_adds_silent_pages(qapp, store, tmp_path,
                                                   monkeypatch):
    """Title + copyright checkboxes on: the PDF grows by two front
    pages ahead of the same two chapter pages."""
    import re

    monkeypatch.setattr(ff, "FORMATS_DIR", tmp_path / "formats")
    docs = {d.title: d for d in store.list_documents()}
    project = BookProject(title="Assembled", author="A. H.",
                          format_name="KDP 6x9 Book")
    project.sections["title_page"] = True
    project.sections["copyright"] = True
    project.sections["toc"] = True
    project.sections["scripture_index"] = True
    project.sections["subject_index"] = True
    project.copyright.isbn = "979-8-0000-0000-0"
    vocab = tmp_path / "v.json"
    vocab.write_text('{"Nation": ["nation"]}', encoding="utf-8")
    project.vocabulary_path = str(vocab)
    project.chapters = [
        ChapterRef(docs["Preface"].uuid, "Preface"),
        ChapterRef(docs["The Holy Nation"].uuid, "The Holy Nation"),
    ]
    out = tmp_path / "book_fm.pdf"
    build_book_pdf(store, project, out)
    pages = len(re.findall(rb"/Type /Page\b(?!s)", out.read_bytes()))
    # Title + copyright + contents + two chapter pages + two indexes.
    assert pages >= 7, f"expected front+chapters+indexes, got {pages} pages"
