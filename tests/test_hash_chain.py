"""
Tests for the library hash chain (the private stamps): every revision
links to all before it, tampering breaks the braid visibly, old
libraries are backfilled, and the anchors table keeps the public-stamp
bookkeeping.  Storage-only — no Qt.
"""

from wordvault import DocumentStore


def _store(tmp_path):
    store = DocumentStore(tmp_path / "chain.db")
    a = store.create_document("Essay A")
    b = store.create_document("Essay B")
    store.save_revision(a.id, "first words of essay a")
    store.save_revision(b.id, "first words of essay b")
    store.save_revision(a.id, "first words of essay a, then more")
    return store, a, b


def test_fresh_saves_braid_and_verify_passes(tmp_path):
    store, _a, _b = _store(tmp_path)
    assert not store.chain_needs_backfill()
    ok, bad, checked = store.verify_chain()
    assert ok and bad is None and checked == 3
    head = store.chain_head()
    assert head and len(head) == 64


def test_every_save_moves_the_head(tmp_path):
    store, a, _b = _store(tmp_path)
    before = store.chain_head()
    store.save_revision(a.id, "yet more words arrive")
    assert store.chain_head() != before


def test_altering_a_revision_breaks_the_braid(tmp_path):
    store, _a, _b = _store(tmp_path)
    victim = store._conn.execute(
        "SELECT id FROM revisions ORDER BY id LIMIT 1").fetchone()["id"]
    store._conn.execute(
        "UPDATE revisions SET payload = 'forged words' WHERE id = ?",
        (victim,))
    store._conn.commit()
    ok, bad, _checked = store.verify_chain()
    assert not ok and bad == victim


def test_removing_a_revision_breaks_the_braid(tmp_path):
    store, _a, b = _store(tmp_path)
    middle = store._conn.execute(
        "SELECT id FROM revisions ORDER BY id LIMIT 1 OFFSET 1"
    ).fetchone()["id"]
    store._conn.execute("DELETE FROM revisions WHERE id = ?", (middle,))
    store._conn.commit()
    ok, _bad, _checked = store.verify_chain()
    assert not ok                      # the gap cannot hide


def test_backfill_braids_an_old_library(tmp_path):
    store, a, _b = _store(tmp_path)
    # Simulate a pre-chain library: strip every link.
    store._conn.execute("UPDATE revisions SET chain_hash = NULL")
    store._conn.commit()
    assert store.chain_needs_backfill()
    # A save during the un-braided state must NOT invent a lone link.
    store.save_revision(a.id, "saved before the backfill ran")
    assert store.chain_needs_backfill()

    seen = []
    filled = store.backfill_chain(lambda done, total: seen.append(done))
    assert filled == 4
    assert seen[-1] == 4
    assert not store.chain_needs_backfill()
    ok, _bad, checked = store.verify_chain()
    assert ok and checked == 4


def test_anchor_bookkeeping_round_trips(tmp_path):
    store, _a, _b = _store(tmp_path)
    head = store.chain_head()
    anchor_id = store.add_anchor(head, "/backups/anchor-1.txt.ots")
    anchors = store.list_anchors()
    assert len(anchors) == 1
    assert anchors[0]["chain_head"] == head
    assert anchors[0]["status"] == "pending"
    store.set_anchor_status(anchor_id, "confirmed")
    assert store.list_anchors()[0]["status"] == "confirmed"
