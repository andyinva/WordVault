"""
Tests for Markdown -> .docx export (wordvault/export_docx.py).

The crown test is the ROUND TRIP: export through markdown_to_docx,
re-import through the ingest extractor, and the structure must
survive the full circle — headings, emphasis, lists, quotes,
paragraph joins.  Exporter and importer are exact inverses, and this
is where that claim is enforced.
"""

import pytest

docx = pytest.importorskip("docx")

from wordvault.export_docx import markdown_to_docx  # noqa: E402
from wordvault.ingest.extract import extract_markdown  # noqa: E402

MARKDOWN = """# The Coming Kingdom

## First Signs

The word **kingdom** appears *often* and ***emphatically*** here.

A second paragraph, whose two source lines
join into one, as the conventions say.

> A quoted verse stands apart.

- first point
- second point

1. alpha
2. beta
"""


def test_round_trip_survives(tmp_path):
    path = tmp_path / "out.docx"
    markdown_to_docx(MARKDOWN, path, title="The Coming Kingdom",
                     author="Andrew Hopkins")
    back = extract_markdown(path)

    assert "# The Coming Kingdom" in back
    assert "## First Signs" in back
    assert "**kingdom**" in back
    assert "*often*" in back
    assert "***emphatically***" in back
    assert "join into one, as the conventions say." in back
    assert "whose two source lines join" in back      # joined, not split
    assert "> A quoted verse stands apart." in back
    assert "- first point" in back and "- second point" in back
    assert "1. alpha" in back                          # a numbered list
    # And the Word file's own identity fields carry the metadata.
    d = docx.Document(str(path))
    assert d.core_properties.title == "The Coming Kingdom"
    assert d.core_properties.author == "Andrew Hopkins"


def test_unmatched_markers_stay_literal(tmp_path):
    path = tmp_path / "lit.docx"
    markdown_to_docx("A lone *asterisk pair left open.\n", path)
    d = docx.Document(str(path))
    text = "\n".join(p.text for p in d.paragraphs)
    assert "*asterisk" in text          # untouched, exactly as typed


def test_heading_levels_map_to_word_styles(tmp_path):
    path = tmp_path / "h.docx"
    markdown_to_docx("# One\n\n### Three\n\nBody.\n", path)
    d = docx.Document(str(path))
    styles = [p.style.name for p in d.paragraphs if p.text]
    assert "Heading 1" in styles and "Heading 3" in styles
