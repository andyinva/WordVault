"""
Offscreen tests for the version-group review screen (stage 5).

Same pattern as test_editor_smoke.py: runs the real dialog against a
temporary database with Qt's offscreen platform; skipped when PyQt6 is
not installed.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault import DocumentStore  # noqa: E402
from wordvault.editor.review import ReviewDialog, diff_as_html  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def store_with_groups(tmp_path):
    """Two pending groups: (a, b) drafts and (c, d) drafts."""
    store = DocumentStore(tmp_path / "review.db")
    docs = {}
    for name, text in [
        ("a", "the first draft of the essay\n"),
        ("b", "the second draft of the essay\n"),
        ("c", "notes on another topic\n"),
        ("d", "more notes on another topic\n"),
    ]:
        doc = store.create_document(name)
        store.save_revision(doc.id, text, origin="ingest")
        docs[name] = doc
    g1 = store.create_similarity_group([(docs["a"].id, 1.0), (docs["b"].id, 0.8)])
    g2 = store.create_similarity_group([(docs["c"].id, 1.0), (docs["d"].id, 0.7)])
    yield store, docs, g1, g2
    store.close()


def test_dialog_lists_pending_groups(qapp, store_with_groups):
    store, docs, g1, g2 = store_with_groups
    dialog = ReviewDialog(store)
    assert dialog._group_list.count() == 2
    # First group auto-selected; its two members fill the table.
    assert dialog._members.rowCount() == 2
    assert dialog._members.item(0, 0).text() == "a"


def test_confirm_links_checked_members(qapp, store_with_groups):
    store, docs, g1, g2 = store_with_groups
    dialog = ReviewDialog(store)
    dialog._group_list.setCurrentRow(0)   # group 1: a, b
    dialog._on_confirm()

    assert store.get_document(docs["b"].id).parent_doc_id == docs["a"].id
    assert store.list_similarity_groups("confirmed") == [g1]
    assert store.list_similarity_groups("pending") == [g2]
    assert dialog._group_list.count() == 1   # queue moved on


def test_unchecking_splits_member_out(qapp, store_with_groups):
    store, docs, g1, g2 = store_with_groups
    dialog = ReviewDialog(store)
    dialog._group_list.setCurrentRow(0)
    # Uncheck "b": with only one member left the chain is refused, so
    # nothing links and the group stays pending (per the dialog's message).
    dialog._members.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog._checked_doc_ids() == [docs["a"].id]


def test_reject_leaves_documents_independent(qapp, store_with_groups):
    store, docs, g1, g2 = store_with_groups
    dialog = ReviewDialog(store)
    dialog._group_list.setCurrentRow(0)
    dialog._on_reject()

    assert store.get_document(docs["b"].id).parent_doc_id is None
    assert store.list_similarity_groups("rejected") == [g1]
    assert dialog._group_list.count() == 1


def test_diff_html_marks_changes(qapp):
    html_out = diff_as_html("old", "line one\nline two\n",
                            "new", "line one\nline 2\n")
    assert "line two" in html_out and "line 2" in html_out
    assert "#b22222" in html_out and "#1a7f1a" in html_out  # red + green

    same = diff_as_html("x", "same\n", "y", "same\n")
    assert "identical" in same
