"""
Tests for SearchEngine (find + staged replace) and the gather tray.

All storage-level — no GUI, runs everywhere.
"""

import pytest

from wordvault import DocumentStore
from wordvault.storage.search import SearchEngine


@pytest.fixture()
def library():
    """Three documents with known text, plus the engine."""
    store = DocumentStore(":memory:")
    ids = {}
    for title, text in [
        ("Priesthood", "Melchizedek king of Salem brought forth bread.\n"
                       "The order of Melchizedek endures.\n"),
        ("Hebrews", "A priest after the order of Melchizedek.\n"),
        ("Unrelated", "The vineyard produced its fruit in season.\n"),
    ]:
        doc = store.create_document(title)
        store.save_revision(doc.id, text)
        ids[title] = doc.id
    yield store, SearchEngine(store), ids
    store.close()


# -- find --------------------------------------------------------------------

def test_find_across_library(library):
    store, engine, ids = library
    matches = engine.find("melchizedek")          # case-insensitive default
    assert len(matches) == 3
    assert {m.doc_id for m in matches} == {ids["Priesthood"], ids["Hebrews"]}
    # Offsets point at the actual text.
    m = matches[0]
    text = store.current_text(m.doc_id)
    assert text[m.start:m.end].lower() == "melchizedek"


def test_find_scoped_to_documents(library):
    store, engine, ids = library
    matches = engine.find("melchizedek", doc_ids=[ids["Hebrews"]])
    assert len(matches) == 1
    assert matches[0].doc_id == ids["Hebrews"]


def test_find_case_sensitive(library):
    store, engine, ids = library
    assert engine.find("melchizedek", case_sensitive=True) == []
    assert len(engine.find("Melchizedek", case_sensitive=True)) == 3


def test_find_regex(library):
    store, engine, ids = library
    matches = engine.find(r"order of \w+", regex=True)
    assert len(matches) == 2
    assert engine.find("", regex=True) == []


def test_snippet_contains_match_in_long_paragraph(library):
    # A match deep inside a long single-line paragraph must still appear
    # in its own snippet (the window centers on the match).
    store, engine, ids = library
    doc = store.create_document("Long Paragraph")
    text = ("word " * 120) + "Melchizedek appears here " + ("word " * 60) + "\n"
    store.save_revision(doc.id, text)

    matches = [m for m in engine.find("melchizedek") if m.doc_id == doc.id]
    assert len(matches) == 1
    assert "Melchizedek" in matches[0].line       # the fix under test
    assert matches[0].line.startswith("…")        # trimmed lead-in marked


# -- staged replace ----------------------------------------------------------

def test_replace_preview_then_apply(library):
    store, engine, ids = library
    plans = engine.plan_replace("Melchizedek", "Melchisedec")
    assert {p.title for p in plans} == {"Priesthood", "Hebrews"}

    changed, skipped = engine.apply_replace(plans)
    assert changed == 2 and skipped == []
    assert "Melchisedec" in store.current_text(ids["Priesthood"])
    assert "Melchizedek" not in store.current_text(ids["Priesthood"])

    # The replace is an ordinary revision: origin recorded, old text intact.
    revs = store.list_revisions(ids["Priesthood"])
    assert revs[-1].origin == "replace"
    assert "Melchizedek" in store.get_text(revs[0].id)   # history unchanged


def test_replace_respects_unchecked_matches(library):
    store, engine, ids = library
    plans = engine.plan_replace("Melchizedek", "X")
    # Keep only the FIRST match in Priesthood checked (uncheck the rest).
    keep = {(ids["Priesthood"], plans[0].matches[0].start)}
    changed, _ = engine.apply_replace(plans, selected=keep)

    assert changed == 1
    text = store.current_text(ids["Priesthood"])
    assert text.count("X") == 1 and text.count("Melchizedek") == 1
    # Hebrews had nothing checked: untouched, no new revision.
    assert len(store.list_revisions(ids["Hebrews"])) == 1


def test_replace_skips_documents_edited_since_preview(library):
    store, engine, ids = library
    plans = engine.plan_replace("Melchizedek", "X")
    # The author keeps typing after the preview...
    store.save_revision(ids["Priesthood"], "totally new text\n")

    changed, skipped = engine.apply_replace(plans)
    assert "Priesthood" in skipped                 # stale offsets: skipped
    assert store.current_text(ids["Priesthood"]) == "totally new text\n"
    assert changed == 1                            # Hebrews still applied


def test_regex_replace_expands_groups(library):
    store, engine, ids = library
    plans = engine.plan_replace(
        r"order of (\w+)", r"order of \1 the priest", regex=True
    )
    engine.apply_replace(plans)
    assert "order of Melchizedek the priest" in store.current_text(ids["Hebrews"])


# -- gather tray -------------------------------------------------------------

def test_mark_and_gather(library):
    store, engine, ids = library
    rev_p = store.latest_revision(ids["Priesthood"])
    rev_h = store.latest_revision(ids["Hebrews"])

    store.add_gather_item(ids["Priesthood"], rev_p.id,
                          "Melchizedek king of Salem brought forth bread.", 0, 46)
    store.add_gather_item(ids["Hebrews"], rev_h.id,
                          "A priest after the order of Melchizedek.", 0, 40)
    assert len(store.list_gather_items()) == 2

    doc = store.gather_into_document("Melchizedek Study")
    text = store.current_text(doc.id)
    assert "king of Salem" in text and "A priest after" in text

    # Provenance: one sources row per gathered passage.
    rev = store.latest_revision(doc.id)
    assert rev.origin == "pull"
    links = store.sources_for(rev.id)
    assert {l.source_doc_id for l in links} == {ids["Priesthood"], ids["Hebrews"]}

    # The tray was emptied by the gather.
    assert store.list_gather_items() == []


def test_gather_empty_tray_raises(library):
    store, engine, ids = library
    with pytest.raises(ValueError):
        store.gather_into_document("Nothing")


def test_remove_gather_item(library):
    store, engine, ids = library
    rev = store.latest_revision(ids["Hebrews"])
    item = store.add_gather_item(ids["Hebrews"], rev.id, "passage", 0, 7)
    store.remove_gather_item(item.id)
    assert store.list_gather_items() == []
