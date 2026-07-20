"""
End-to-end tests for the ingest pipeline (Phases A and B).

Builds real .docx files in a temp folder with python-docx, then runs the
same Ingestor the CLI uses.  Skipped automatically when python-docx is
not installed (the rest of WordVault never requires it).
"""

import pytest

docx = pytest.importorskip("docx")

from wordvault import DocumentStore  # noqa: E402
from wordvault.ingest import Ingestor  # noqa: E402
from wordvault.ingest.extract import extract_text, normalize_text  # noqa: E402

ESSAY = (
    "In the beginning God created the heaven and the earth. And the earth "
    "was without form, and void; and darkness was upon the face of the deep. "
) * 20

OTHER = (
    "The quarterly report shows revenue growth across all divisions with "
    "particular strength in the northern region this year. "
) * 20


def make_docx(path, paragraphs):
    """Write a real .docx file with the given paragraph texts."""
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    d.save(str(path))


@pytest.fixture()
def library(tmp_path):
    """A source folder of five .docx files and an empty library store:
    draft1/draft2 are versions, copy is an exact duplicate of draft1,
    unrelated stands alone, empty has no text."""
    src = tmp_path / "src"
    src.mkdir()
    make_docx(src / "essay_draft1.docx", [ESSAY])
    make_docx(src / "essay_draft2.docx",
              [ESSAY.replace("darkness", "the dark") + " A new closing thought."])
    make_docx(src / "essay_copy_other_name.docx", [ESSAY])  # exact dup of draft1
    make_docx(src / "unrelated.docx", [OTHER])
    make_docx(src / "empty.docx", [])

    store = DocumentStore(tmp_path / "library.db")
    yield src, store
    store.close()


def test_extract_normalizes(tmp_path):
    p = tmp_path / "one.docx"
    make_docx(p, ["Line one  ", "", "Line two"])   # trailing spaces stripped
    assert extract_text(p) == "Line one\n\nLine two\n"
    assert normalize_text("a\r\nb\r") == "a\nb\n"


def test_phase_a_ingests_and_collapses_duplicates(library):
    src, store = library
    stats = Ingestor(store).ingest_folder(src)

    assert stats.files_seen == 5
    assert stats.ingested == 3        # draft1, draft2, unrelated
    assert stats.duplicates == 1      # the exact copy under another name
    assert stats.empty == 1
    assert not stats.errors

    docs = store.ingested_documents()
    assert len(docs) == 3
    # Documents carry their file's path and an ingest-origin revision.
    for doc in docs:
        revs = store.list_revisions(doc.id)
        assert len(revs) == 1 and revs[0].origin == "ingest"

    # The duplicate's path was noted on the surviving document.
    dup_owner = next(d for d in docs if "draft1" in d.original_path)
    assert any("copy_other_name" in p for p in store.ingest_duplicates_for(dup_owner.id))


def test_phase_b_proposes_version_group(library):
    src, store = library
    stats = Ingestor(store, threshold=0.5).ingest_folder(src)

    assert stats.groups_proposed == 1
    gid = store.list_similarity_groups("pending")[0]
    titles = sorted(d.title for d, _ in store.group_members(gid))
    assert titles == ["essay_draft1", "essay_draft2"]   # unrelated stays out


def test_rerun_is_idempotent(library):
    src, store = library
    Ingestor(store).ingest_folder(src)
    stats2 = Ingestor(store).ingest_folder(src)   # run again, same folder

    assert stats2.ingested == 0
    assert stats2.duplicates == 0                 # dup not re-noted either
    assert stats2.skipped_known == 4              # 3 documents + 1 dup path
    assert len(store.ingested_documents()) == 3


def test_limit_allows_trial_run(library):
    src, store = library
    stats = Ingestor(store).ingest_folder(src, limit=1)
    assert stats.ingested == 1
    # Continuing without the limit picks up the rest.
    stats2 = Ingestor(store).ingest_folder(src)
    assert len(store.ingested_documents()) == 3


def test_confirmed_groups_survive_rerun(library):
    src, store = library
    Ingestor(store, threshold=0.5).ingest_folder(src)
    gid = store.list_similarity_groups("pending")[0]
    store.set_group_status(gid, "confirmed")      # the author decided

    Ingestor(store, threshold=0.5).ingest_folder(src)   # detector re-runs
    assert store.list_similarity_groups("confirmed") == [gid]
    assert store.list_similarity_groups("pending") == []  # not re-proposed
