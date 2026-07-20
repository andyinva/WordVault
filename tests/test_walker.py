"""
Tests for RevisionWalker (wordvault/storage/walker.py) — the time-travel
model behind the editor's timeline slider.
"""

import pytest

from wordvault import DocumentStore, RevisionWalker


@pytest.fixture()
def store():
    s = DocumentStore(":memory:", snapshot_interval=3)
    yield s
    s.close()


@pytest.fixture()
def doc_with_history(store):
    """A document with five known states."""
    doc = store.create_document("Doc")
    texts = [f"state {i}\n" for i in range(5)]
    for t in texts:
        store.save_revision(doc.id, t)
    return doc, texts


def test_starts_at_newest(store, doc_with_history):
    doc, texts = doc_with_history
    walker = RevisionWalker(store, doc.id)
    assert walker.text() == texts[-1]
    assert walker.position == len(texts) - 1


def test_back_and_forward(store, doc_with_history):
    doc, texts = doc_with_history
    walker = RevisionWalker(store, doc.id)

    # Walk all the way back, checking every state on the way.
    for expected in reversed(texts[:-1]):
        walker.back()
        assert walker.text() == expected

    # At the oldest state, back() refuses and stays put.
    assert walker.back() is None
    assert walker.text() == texts[0]

    # Walk forward again to the newest.
    for expected in texts[1:]:
        walker.forward()
        assert walker.text() == expected

    # At the newest state, forward() refuses and stays put.
    assert walker.forward() is None
    assert walker.text() == texts[-1]


def test_jump_to_revision(store, doc_with_history):
    doc, texts = doc_with_history
    revs = store.list_revisions(doc.id)
    walker = RevisionWalker(store, doc.id)

    walker.at(revs[2].id)
    assert walker.text() == texts[2]

    with pytest.raises(KeyError):
        walker.at(99999)


def test_empty_document(store):
    doc = store.create_document("Empty")
    walker = RevisionWalker(store, doc.id)
    assert len(walker) == 0
    assert walker.current() is None
    assert walker.text() == ""
    assert walker.back() is None
    assert walker.forward() is None


def test_refresh_sees_new_revisions_and_keeps_position(store, doc_with_history):
    doc, texts = doc_with_history
    walker = RevisionWalker(store, doc.id)
    walker.back()          # stand on state 3
    standing_on = walker.current().id

    store.save_revision(doc.id, "state 5 arrives\n")  # new revision appears
    walker.refresh()

    assert len(walker) == 6                    # walker sees the new one
    assert walker.current().id == standing_on  # but did not move


def test_restore_pattern_appends_not_rewrites(store, doc_with_history):
    # "Restore" = append the old text as a NEW revision; history intact.
    doc, texts = doc_with_history
    walker = RevisionWalker(store, doc.id)
    walker.back()
    walker.back()          # viewing state 2
    old_text = walker.text()

    store.save_revision(doc.id, old_text, origin="restore")

    history = store.list_revisions(doc.id)
    assert len(history) == 6                       # nothing was rewritten
    assert store.current_text(doc.id) == old_text  # newest state == restored
    assert history[-1].origin == "restore"
