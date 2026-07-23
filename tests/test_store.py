"""
Tests for DocumentStore (wordvault/storage/store.py).

All tests run against an in-memory SQLite database, so the suite is fast
and leaves nothing on disk.  A small snapshot_interval is used in several
tests to exercise the snapshot/diff policy without saving 50 revisions.
"""

import pytest

from wordvault import DocumentStore


@pytest.fixture()
def store():
    """A fresh in-memory library for each test."""
    s = DocumentStore(":memory:", snapshot_interval=4)
    yield s
    s.close()


# -- documents --------------------------------------------------------------

def test_create_and_get_document(store):
    doc = store.create_document("First Essay")
    assert doc.title == "First Essay"
    assert doc.uuid  # a uuid was generated
    assert store.get_document(doc.id) == doc
    assert store.get_document_by_uuid(doc.uuid) == doc


def test_get_missing_document_raises(store):
    with pytest.raises(KeyError):
        store.get_document(999)


def test_version_chain_via_parent(store):
    draft1 = store.create_document("Essay draft 1")
    draft2 = store.create_document("Essay draft 2", parent_doc_id=draft1.id)
    assert store.get_document(draft2.id).parent_doc_id == draft1.id


def test_list_documents_chronological(store):
    a = store.create_document("A", created_utc="2020-01-01T00:00:00+00:00")
    b = store.create_document("B", created_utc="2019-01-01T00:00:00+00:00")
    titles = [d.title for d in store.list_documents()]
    assert titles == ["B", "A"]  # oldest first, regardless of insert order


def test_rename_document(store):
    doc = store.create_document("Old Title")
    store.rename_document(doc.id, "New Title")
    assert store.get_document(doc.id).title == "New Title"


# -- revisions --------------------------------------------------------------

def test_first_revision_is_snapshot(store):
    doc = store.create_document("Doc")
    rev = store.save_revision(doc.id, "hello world\n")
    assert rev.kind == "snapshot"
    assert rev.parent_rev_id is None
    assert store.get_text(rev.id) == "hello world\n"


def test_identical_text_is_skipped(store):
    doc = store.create_document("Doc")
    store.save_revision(doc.id, "same text\n")
    assert store.save_revision(doc.id, "same text\n") is None
    assert len(store.list_revisions(doc.id)) == 1


def test_snapshot_interval_policy(store):
    # snapshot_interval=4: replay chains must never reach 4 diffs.
    doc = store.create_document("Doc")
    for i in range(10):
        store.save_revision(doc.id, f"text version {i}\n")
    kinds = [r.kind for r in store.list_revisions(doc.id)]
    # First is a snapshot, and no run of consecutive diffs reaches 4.
    assert kinds[0] == "snapshot"
    run = 0
    for kind in kinds:
        run = run + 1 if kind == "diff" else 0
        assert run < 4


def test_every_historical_state_rebuilds_exactly(store):
    # The core promise: any past state can be reproduced byte-for-byte.
    doc = store.create_document("Doc")
    texts = [f"draft {i}: " + "content " * i + "\n" for i in range(12)]
    revs = [store.save_revision(doc.id, t) for t in texts]
    for rev, expected in zip(revs, texts):
        assert store.get_text(rev.id) == expected


def test_current_text(store):
    doc = store.create_document("Doc")
    assert store.current_text(doc.id) == ""  # no revisions yet
    store.save_revision(doc.id, "one\n")
    store.save_revision(doc.id, "one\ntwo\n")
    assert store.current_text(doc.id) == "one\ntwo\n"


def test_revision_timestamps_and_origin(store):
    doc = store.create_document("Doc")
    rev = store.save_revision(
        doc.id, "imported text\n",
        origin="ingest", created_utc="2001-05-01T12:00:00+00:00",
    )
    assert rev.origin == "ingest"
    assert rev.created_utc == "2001-05-01T12:00:00+00:00"


# -- provenance -------------------------------------------------------------

def test_record_and_read_sources(store):
    essay = store.create_document("Essay")
    notes = store.create_document("Notes")
    notes_rev = store.save_revision(notes.id, "a useful passage\n")
    essay_rev = store.save_revision(essay.id, "quoting: a useful passage\n")

    link = store.record_source(
        essay_rev.id, notes.id, notes_rev.id, excerpt_start=0, excerpt_end=16
    )
    assert link.source_doc_id == notes.id

    found = store.sources_for(essay_rev.id)
    assert len(found) == 1
    assert found[0].source_rev_id == notes_rev.id


# -- tags -------------------------------------------------------------------

def test_tagging(store):
    doc = store.create_document("Doc")
    store.add_tag(doc.id, "Genesis")
    store.add_tag(doc.id, "creation")
    store.add_tag(doc.id, "Genesis")  # duplicate add is a no-op

    names = [t.name for t in store.tags_for(doc.id)]
    assert names == ["Genesis", "creation"]

    assert [d.id for d in store.documents_with_tag("Genesis")] == [doc.id]

    store.remove_tag(doc.id, "Genesis")
    assert [t.name for t in store.tags_for(doc.id)] == ["creation"]


# -- version chains ---------------------------------------------------------

def test_link_version_chain(store):
    a = store.create_document("Draft 1")
    b = store.create_document("Draft 2")
    c = store.create_document("Draft 3")
    store.link_version_chain([a.id, b.id, c.id])

    assert store.get_document(b.id).parent_doc_id == a.id
    assert store.get_document(c.id).parent_doc_id == b.id
    # The whole chain is reachable from ANY member, oldest first.
    for member in (a, b, c):
        assert [d.id for d in store.version_chain(member.id)] == [a.id, b.id, c.id]


def test_chain_cycle_is_rejected(store):
    a = store.create_document("A")
    b = store.create_document("B")
    store.link_version_chain([a.id, b.id])
    with pytest.raises(ValueError):
        store.set_parent_document(a.id, b.id)   # would loop A -> B -> A
    with pytest.raises(ValueError):
        store.set_parent_document(a.id, a.id)   # self-parent


def test_chain_needs_two_distinct_documents(store):
    a = store.create_document("A")
    with pytest.raises(ValueError):
        store.link_version_chain([a.id])
    b = store.create_document("B")
    with pytest.raises(ValueError):
        store.link_version_chain([a.id, b.id, a.id])   # duplicate member


def test_unlinked_document_is_its_own_chain(store):
    a = store.create_document("Loner")
    assert [d.id for d in store.version_chain(a.id)] == [a.id]


# -- spelling log ------------------------------------------------------------

def test_spelling_log_and_summary(store):
    doc = store.create_document("Essay")
    store.log_spelling_fix(doc.id, "becase", "because", "dropped letter", "u")
    store.log_spelling_fix(doc.id, "Becase", "Because", "dropped letter", "u")
    store.log_spelling_fix(None, "seperate", "separate", "vowel swap", "e->a")

    kinds, pairs = store.spelling_summary()
    assert kinds == [("dropped letter", 2), ("vowel swap", 1)]
    assert pairs[0] == ("becase", "because", 2)   # case-folded, most first

    recent = store.spelling_history(2)
    assert len(recent) == 2
    assert recent[0]["typed"] == "seperate"       # newest first


# -- search -----------------------------------------------------------------

def test_search_current_finds_latest_text_only(store):
    if not store.fts_available:
        pytest.skip("SQLite build lacks FTS5")
    doc = store.create_document("Psalms Essay")
    store.save_revision(doc.id, "the shepherd theme\n")
    store.save_revision(doc.id, "the vineyard theme\n")  # replaces shepherd

    hits = store.search_current("vineyard")
    assert [d.id for d, _ in hits] == [doc.id]
    # Old text is out of the *current* index (history search is stage 6).
    assert store.search_current("shepherd") == []


def test_search_matches_title(store):
    if not store.fts_available:
        pytest.skip("SQLite build lacks FTS5")
    doc = store.create_document("Exodus Notes")
    store.save_revision(doc.id, "some body text\n")
    assert [d.id for d, _ in store.search_current("Exodus")] == [doc.id]


# -- persistence to a real file ---------------------------------------------

def test_reopen_from_disk(tmp_path):
    # A store closed and reopened must yield the identical library.
    db = tmp_path / "library.db"
    with DocumentStore(db) as store:
        doc = store.create_document("Persistent")
        store.save_revision(doc.id, "survives a restart\n")
        doc_id = doc.id

    with DocumentStore(db) as store:
        assert store.current_text(doc_id) == "survives a restart\n"
        assert store.get_document(doc_id).title == "Persistent"
