"""
Tests for tools/split_book_docx.py and tools/import_markdown.py — the
book-to-chapters pipeline.  A tiny synthetic .docx is built in-test
(zipfile + hand-written WordprocessingML), so the tools' whole path
runs without any real Word file.  Standard library only.
"""

import importlib.util
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def para(text, style=None, italic=False, instr=None):
    """One WordprocessingML paragraph, minimally but honestly formed."""
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    rpr = "<w:rPr><w:i/></w:rPr>" if italic else ""
    runs = f"<w:r>{rpr}<w:t xml:space=\"preserve\">{text}</w:t></w:r>"
    if instr:   # a hidden field instruction run (XE marker, PAGEREF...)
        runs += f"<w:r><w:instrText>{instr}</w:instrText></w:r>"
    return f"<w:p>{ppr}{runs}</w:p>"


def make_docx(path, paragraphs):
    body = "".join(paragraphs)
    xml = (f'<?xml version="1.0"?><w:document {W_NS}>'
           f"<w:body>{body}</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def test_split_drops_front_and_back_matter(tmp_path):
    split = load_tool("split_book_docx")
    docx = tmp_path / "book.docx"
    make_docx(docx, [
        para("My Book Title", style="Title"),
        para("Contents"),
        para("Chapter One 5", style="TOC1", instr="PAGEREF _Toc1 \\h"),
        para("Chapter One", style="Heading1"),
        para("First words.", instr='XE "Eve" \\f "a"'),
        para("A Section", style="Heading2"),
        para("More prose."),
        para("Chapter Two", style="Heading1"),
        para("Second chapter text."),
        para("Scripture Index", style="Heading1"),
        para("(index placeholder)", instr='INDEX \\f "b"'),
    ])
    written = split.split_book(docx, tmp_path / "out")
    names = [p.name for p in written]
    assert names == ["00 Chapter One.md", "01 Chapter Two.md"]

    ch1 = written[0].read_text(encoding="utf-8")
    # Structure survived; front matter, TOC, XE and INDEX fields did not.
    assert ch1.startswith("# Chapter One\n\nFirst words.")
    assert "## A Section" in ch1
    assert "Title" not in ch1 and "PAGEREF" not in ch1 and "XE" not in ch1
    assert "Scripture Index" not in (tmp_path / "out" / "01 Chapter Two.md"
                                     ).read_text(encoding="utf-8")


def test_split_marks_italics_once_across_run_fragments(tmp_path):
    split = load_tool("split_book_docx")
    docx = tmp_path / "i.docx"
    # Word habitually splits one italic phrase into several runs.
    body = ('<w:p><w:r><w:t xml:space="preserve">The word </w:t></w:r>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t>qol</w:t></w:r>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve"> echad</w:t></w:r>'
            '<w:r><w:t xml:space="preserve"> means one voice.</w:t></w:r></w:p>')
    make_docx(docx, [para("C", style="Heading1"), body])
    out = split.split_book(docx, tmp_path / "out")[0].read_text("utf-8")
    assert "The word *qol echad* means one voice." in out


def test_import_markdown_titles_and_no_duplicates(tmp_path):
    imp = load_tool("import_markdown")
    folder = tmp_path / "md"
    folder.mkdir()
    (folder / "00 Preface.md").write_text("# Preface\n\nText.\n", "utf-8")
    (folder / "01 Chapter.md").write_text("no heading here\n", "utf-8")

    lib = tmp_path / "lib.db"
    assert imp.main([str(folder), "--library", str(lib)]) == 0
    # Second run: both skipped (same text), nothing duplicated.
    assert imp.main([str(folder), "--library", str(lib)]) == 0

    from wordvault import DocumentStore
    store = DocumentStore(lib)
    titles = sorted(d.title for d in store.list_documents())
    # Heading wins; filename (minus number) is the fallback.
    assert titles == ["Chapter", "Preface"]
    store.close()


def test_import_title_collision_with_different_text(tmp_path):
    """The Preface lesson (Aug 2026): an OLD essay named 'Preface'
    must not block a BOOK's preface from importing.  Same title +
    different text -> imported under 'Preface (2)'; rerunning skips
    it (the text is now present), still never duplicating."""
    imp = load_tool("import_markdown")
    from wordvault import DocumentStore

    lib = tmp_path / "lib.db"
    store = DocumentStore(lib)
    old = store.create_document("Preface")
    store.save_revision(old.id, "# Preface\n\nAn unrelated old essay.")
    store.close()

    folder = tmp_path / "md"
    folder.mkdir()
    (folder / "00 Preface.md").write_text(
        "# Preface\n\nThe book's own preface.\n", "utf-8")

    assert imp.main([str(folder), "--library", str(lib)]) == 0
    assert imp.main([str(folder), "--library", str(lib)]) == 0  # rerun

    store = DocumentStore(lib)
    titles = sorted(d.title for d in store.list_documents())
    assert titles == ["Preface", "Preface (2)"]
    two = [d for d in store.list_documents() if d.title == "Preface (2)"][0]
    text = store.get_text(store.latest_revision(two.id).id)
    assert "The book's own preface." in text
    store.close()
