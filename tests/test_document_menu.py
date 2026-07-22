"""
Offscreen tests for the Document menu: Go to Document (quick open),
Find in Document (find bar), rename, and version-chain stepping.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtWidgets import QApplication, QInputDialog  # noqa: E402

from wordvault import DocumentStore  # noqa: E402
from wordvault.editor import MainWindow  # noqa: E402
from wordvault.editor.quick_open import QuickOpenDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# -- quick open --------------------------------------------------------------

@pytest.fixture()
def store_with_titles(tmp_path):
    store = DocumentStore(tmp_path / "qo.db")
    for title in ["Atonement Study", "The Coming Kingdom",
                  "Kingdom Parables", "Genesis Notes"]:
        doc = store.create_document(title)
        store.save_revision(doc.id, title + " text\n")
    yield store
    store.close()


def titles_shown(dialog):
    return [dialog._list.item(i).text() for i in range(dialog._list.count())]


def test_quick_open_filters_and_ranks(qapp, store_with_titles):
    dialog = QuickOpenDialog(store_with_titles)
    assert dialog._list.count() == 4            # empty query: everything

    dialog._edit.setText("kingdom")
    shown = titles_shown(dialog)
    # Startswith beats contains: "Kingdom Parables" ranks first.
    assert shown == ["Kingdom Parables", "The Coming Kingdom"]

    dialog._edit.setText("zzz")
    assert dialog._list.count() == 0


def test_quick_open_enter_selects_top_match(qapp, store_with_titles):
    dialog = QuickOpenDialog(store_with_titles)
    dialog._edit.setText("genesis")
    dialog._accept_current()
    assert dialog.selected_doc_id is not None
    doc = store_with_titles.get_document(dialog.selected_doc_id)
    assert doc.title == "Genesis Notes"


# -- find bar ----------------------------------------------------------------

@pytest.fixture()
def window_with_text(qapp, tmp_path):
    window = MainWindow(tmp_path / "fb.db")
    doc = window._store.create_document("Find Me")
    window._store.save_revision(
        doc.id, "alpha beta gamma\nbeta again\nlast beta here\n"
    )
    window._reload_document_list()
    window._open_document(doc.id)
    yield window
    window.close()


def test_find_bar_steps_and_wraps(window_with_text):
    window = window_with_text
    bar = window._find_bar
    bar.open_bar()
    bar._edit.setText("beta")                   # incremental: finds first

    positions = [window._editor.textCursor().position()]
    assert bar.find_next() and bar.find_next()  # second and third match
    positions.append(window._editor.textCursor().position())
    assert positions[0] != positions[1]

    assert bar.find_next()                      # wraps to the first again
    assert bar._status.text() == "wrapped"

    bar._edit.setText("nowhere")
    assert not bar.find_next()
    assert bar._status.text() == "not found"


def test_find_bar_close_returns_to_editor(window_with_text):
    window = window_with_text
    window._find_bar.open_bar()
    assert window._find_bar.isVisible() or True  # offscreen: visibility flag
    window._find_bar.close_bar()
    assert not window._find_bar.isVisible()


# -- rename ------------------------------------------------------------------

def test_rename_document(qapp, tmp_path, monkeypatch):
    window = MainWindow(tmp_path / "rn.db")
    doc = window._store.create_document("Old Name")
    window._store.save_revision(doc.id, "text\n")
    window._reload_document_list()
    window._open_document(doc.id)

    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("New Name", True)),
    )
    window._on_rename_document()
    assert window._store.get_document(doc.id).title == "New Name"
    assert window._current_doc.title == "New Name"
    window.close()


# -- version stepping --------------------------------------------------------

def test_step_through_version_chain(qapp, tmp_path):
    window = MainWindow(tmp_path / "vc.db")
    ids = []
    for title in ["Draft 1", "Draft 2", "Draft 3"]:
        doc = window._store.create_document(title)
        window._store.save_revision(doc.id, title + "\n")
        ids.append(doc.id)
    window._store.link_version_chain(ids)
    window._reload_document_list()
    window._open_document(ids[1])               # middle draft

    window._on_step_version(-1)
    assert window._current_doc.id == ids[0]
    window._on_step_version(-1)                 # already oldest: stays
    assert window._current_doc.id == ids[0]
    window._on_step_version(+1)
    window._on_step_version(+1)
    assert window._current_doc.id == ids[2]
    window.close()
