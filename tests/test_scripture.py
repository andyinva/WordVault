"""
Tests for the scripture-reference parser and the verse index.

All storage-level, standard library only — runs everywhere.
"""

import pytest

from wordvault import DocumentStore
from wordvault.storage.scripture import parse_references


def refs(text):
    """Shorthand: parsed references as display strings."""
    return [r.display() for r in parse_references(text)]


# -- the parser --------------------------------------------------------------

def test_common_forms():
    assert refs("As John 3:16 says...") == ["John 3:16"]
    assert refs("compare 1 Cor. 15:22 and Gen 1:1-5") == [
        "1 Corinthians 15:22", "Genesis 1:1-5",
    ]
    assert refs("see II Timothy 2:15") == ["2 Timothy 2:15"]
    assert refs("in romans 8:28 we read") == ["Romans 8:28"]     # lowercase
    assert refs("Ps 23:1, and Psalm 23:1 again") == ["Psalms 23:1"]  # merged


def test_ranges_and_dashes():
    assert refs("Matthew 24:3-14") == ["Matthew 24:3-14"]
    assert refs("Matthew 24:3–14") == ["Matthew 24:3-14"]        # en dash
    # A backwards range degrades to the first verse, not an error.
    assert refs("John 3:18-16") == ["John 3:18"]


def test_non_references_do_not_match():
    assert refs("we met at 3:16pm near the exit") == []
    assert refs("the context 3:16 of the word") == []   # "ex" inside a word
    assert refs("version 2:1 of the program") == []
    assert refs("") == []


def test_verse_expansion_and_cap():
    (ref,) = parse_references("Genesis 1:1-3")
    assert ref.verses() == [
        ("Genesis", 1, 1), ("Genesis", 1, 2), ("Genesis", 1, 3),
    ]
    # A huge range indexes only its first verse (RANGE_CAP).
    (big,) = parse_references("Psalm 119:1-176")
    assert big.verses() == [("Psalms", 119, 1)]


# -- the index in the store --------------------------------------------------

@pytest.fixture()
def library():
    store = DocumentStore(":memory:")
    ids = {}
    for title, text in [
        ("Atonement A", "On sacrifice: Lev 16:2 and Hebrews 9:12, "
                        "with Romans 3:25 in view.\n"),
        ("Atonement B", "Hebrews 9:12 again, alongside Romans 3:25 "
                        "and 1 John 2:2.\n"),
        ("Kingdom",     "The kingdom parables of Matthew 13:31-33.\n"),
    ]:
        doc = store.create_document(title)
        store.save_revision(doc.id, text)
        ids[title] = doc.id
    yield store, ids
    store.close()


def test_index_refreshes_on_save(library):
    store, ids = library
    assert store.verses_for(ids["Kingdom"]) == [
        "Matthew 13:31", "Matthew 13:32", "Matthew 13:33",
    ]
    # Editing the document re-derives its verse rows.
    store.save_revision(ids["Kingdom"], "Now about Luke 15:4 instead.\n")
    assert store.verses_for(ids["Kingdom"]) == ["Luke 15:4"]


def test_documents_sharing_verses_ranked(library):
    store, ids = library
    matches = store.documents_sharing_verses(ids["Atonement A"])
    assert [(d.title, n) for d, n in matches] == [("Atonement B", 2)]
    assert store.shared_verses(ids["Atonement A"], ids["Atonement B"]) == [
        "Hebrews 9:12", "Romans 3:25",
    ]


def test_documents_citing(library):
    store, ids = library
    citing = store.documents_citing("Hebrews", 9, 12)
    assert {d.title for d in citing} == {"Atonement A", "Atonement B"}
    # Chapter-level query.
    assert [d.title for d in store.documents_citing("Matthew", 13)] == ["Kingdom"]


def test_reindex_backfill(library):
    store, ids = library
    # Simulate a pre-feature document: wipe its rows, then backfill.
    store._conn.execute("DELETE FROM scripture_refs WHERE doc_id = ?",
                        (ids["Kingdom"],))
    assert store.verses_for(ids["Kingdom"]) == []
    count = store.reindex_scripture(ids["Kingdom"])
    assert count == 3
    assert len(store.verses_for(ids["Kingdom"])) == 3
