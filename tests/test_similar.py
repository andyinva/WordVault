"""
Tests for the MinHash near-duplicate detector (wordvault/ingest/similar.py).

Pure standard library — these run everywhere, no python-docx needed.
"""

from wordvault.ingest.similar import MinHasher, cluster

# A paragraph of realistic prose to build variations from.
BASE = (
    "In the beginning God created the heaven and the earth. And the earth "
    "was without form, and void; and darkness was upon the face of the deep. "
    "And the Spirit of God moved upon the face of the waters. And God said, "
    "Let there be light: and there was light. And God saw the light, that it "
    "was good: and God divided the light from the darkness. "
) * 8  # long enough that shingle sampling engages realistically

UNRELATED = (
    "The quarterly report shows revenue growth across all divisions with "
    "particular strength in the northern region where new distribution "
    "agreements have expanded the customer base significantly this year. "
) * 8


def test_identical_texts_score_one():
    h = MinHasher()
    assert MinHasher.estimate(h.signature(BASE), h.signature(BASE)) == 1.0


def test_light_edit_scores_high():
    # A draft with a changed sentence should still look like a version.
    edited = BASE.replace("Let there be light", "Let light come to be", 1)
    h = MinHasher()
    score = MinHasher.estimate(h.signature(BASE), h.signature(edited))
    assert score > 0.6


def test_unrelated_texts_score_low():
    h = MinHasher()
    score = MinHasher.estimate(h.signature(BASE), h.signature(UNRELATED))
    assert score < 0.2


def test_signatures_are_deterministic():
    # Same seed => same signature, across runs and machines (needed so
    # re-running the detector proposes the same groups).
    assert MinHasher().signature(BASE) == MinHasher().signature(BASE)


def test_cluster_groups_versions_and_leaves_singletons_out():
    h = MinHasher()
    draft2 = BASE.replace("darkness", "the dark", 3)
    signatures = {
        1: h.signature(BASE),
        2: h.signature(draft2),      # version of 1
        3: h.signature(UNRELATED),   # unrelated singleton
    }
    groups = cluster(signatures, threshold=0.5)

    assert len(groups) == 1
    members = [doc_id for doc_id, _ in groups[0]]
    assert members == [1, 2]          # oldest first
    scores = dict(groups[0])
    assert scores[1] == 1.0           # the reference member
    assert scores[2] > 0.5


def test_cluster_empty_and_single():
    assert cluster({}) == []
    assert cluster({1: MinHasher().signature(BASE)}) == []


def test_short_documents_do_not_crash():
    h = MinHasher()
    sig_short = h.signature("just three words")
    sig_empty = h.signature("")
    assert len(sig_short) == h.num_perm
    assert len(sig_empty) == h.num_perm
