"""
similar.py — near-duplicate detection with MinHash + LSH (ingest Phase B).

The problem (DESIGN.md section 6): among ~6,000 documents, find the ones
that are versions of the same material — WITHOUT comparing all ~18 million
pairs of full texts.

The technique, in plain language:
  1. Break each document into overlapping word 5-grams ("shingles").
     Two drafts of the same essay share most of their shingles.
  2. MinHash: run 64 different hash functions over a document's shingle
     set and keep only each function's MINIMUM value.  Those 64 numbers
     are the document's "signature".  The mathematical property that makes
     this work: the probability that two documents agree at one signature
     position equals their Jaccard similarity (share of common shingles).
     So comparing 64 numbers estimates the similarity of whole documents.
  3. LSH (locality-sensitive hashing): cut each signature into 16 bands of
     4 numbers.  Documents identical in ANY band become a candidate pair.
     Near-duplicates almost surely share a band; unrelated documents
     almost surely don't — so only a tiny fraction of pairs is ever
     compared directly.
  4. Candidate pairs whose estimated similarity clears the threshold are
     clustered into groups with union-find.

Everything is standard library — no numpy, no datasketch.  To keep pure
Python fast enough, shingles are SAMPLED: only shingles whose base hash
falls in 1/8 of the hash space are used (an unbiased estimator, since the
same shingles survive sampling in every document).  Very short documents
fall back to using all shingles.
"""

from __future__ import annotations

import hashlib
import random
from typing import Dict, Iterable, List, Set, Tuple

# A Mersenne prime comfortably above 64-bit hash values, for the classic
# universal-hash family h(x) = (a*x + b) mod P.
_PRIME = (1 << 89) - 1

# Sampling: keep shingles whose base hash has these low bits zero (1/8).
_SAMPLE_BITS = 3


class MinHasher:
    """Computes MinHash signatures and similarity estimates."""

    def __init__(self, num_perm: int = 64, shingle_words: int = 5, seed: int = 7):
        self.num_perm = num_perm
        self.shingle_words = shingle_words
        # One (a, b) pair per hash function, from a seeded RNG so that
        # signatures are comparable across runs and across machines.
        rng = random.Random(seed)
        self._a = [rng.randrange(1, _PRIME) for _ in range(num_perm)]
        self._b = [rng.randrange(0, _PRIME) for _ in range(num_perm)]

    # -- shingling ----------------------------------------------------------

    def _base_hashes(self, text: str) -> Set[int]:
        """Word-shingle the text and hash each shingle to a 64-bit int.
        Lower-cased and whitespace-split: capitalization and layout changes
        should not make two drafts look different."""
        words = text.lower().split()
        n = self.shingle_words
        if len(words) < n:
            # Degenerate/short document: one shingle of whatever is there.
            shingles: Iterable[str] = [" ".join(words)] if words else [""]
        else:
            shingles = (" ".join(words[i : i + n]) for i in range(len(words) - n + 1))

        hashes = set()
        for s in shingles:
            # blake2b(8 bytes) — fast, stable across platforms and runs
            # (Python's built-in hash() is salted per process: unusable here).
            h = int.from_bytes(
                hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big"
            )
            hashes.add(h)
        return hashes

    def signature(self, text: str) -> Tuple[int, ...]:
        """The document's MinHash signature: num_perm minimum hash values."""
        base = self._base_hashes(text)

        # Sample 1/8 of the shingle space for speed (see module docstring);
        # fall back to the full set when the sample would be too thin.
        sampled = {h for h in base if h & ((1 << _SAMPLE_BITS) - 1) == 0}
        if len(sampled) >= 16:
            base = sampled

        # For each hash function, the minimum over all shingles.
        sig = []
        for a, b in zip(self._a, self._b):
            sig.append(min((a * h + b) % _PRIME for h in base))
        return tuple(sig)

    @staticmethod
    def estimate(sig1: Tuple[int, ...], sig2: Tuple[int, ...]) -> float:
        """Estimated Jaccard similarity: fraction of agreeing positions."""
        agree = sum(1 for x, y in zip(sig1, sig2) if x == y)
        return agree / len(sig1)


def candidate_pairs(
    signatures: Dict[int, Tuple[int, ...]], bands: int = 16
) -> Set[Tuple[int, int]]:
    """
    LSH banding: return pairs of ids that share at least one identical band.
    With 64 hashes in 16 bands of 4, pairs at ~0.5+ similarity are very
    likely candidates; unrelated pairs are very unlikely to collide.
    """
    if not signatures:
        return set()
    num_perm = len(next(iter(signatures.values())))
    rows = num_perm // bands

    pairs: Set[Tuple[int, int]] = set()
    for band in range(bands):
        buckets: Dict[Tuple[int, ...], List[int]] = {}
        for doc_id, sig in signatures.items():
            key = sig[band * rows : (band + 1) * rows]
            buckets.setdefault(key, []).append(doc_id)
        for members in buckets.values():
            if len(members) > 1:
                members.sort()
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        pairs.add((members[i], members[j]))
    return pairs


def cluster(
    signatures: Dict[int, Tuple[int, ...]],
    threshold: float = 0.6,
    bands: int = 16,
) -> List[List[Tuple[int, float]]]:
    """
    Group near-duplicate documents.

    Returns a list of groups; each group is [(doc_id, score), ...] where
    score is the estimated similarity to the group's FIRST member (lowest
    id = ingested earliest = oldest file, since ingest inserts in file-date
    order).  Only groups with 2+ members are returned.
    """
    # Union-find over confirmed-similar candidate pairs.
    parent: Dict[int, int] = {doc_id: doc_id for doc_id in signatures}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path halving
            x = parent[x]
        return x

    for id1, id2 in candidate_pairs(signatures, bands):
        if MinHasher.estimate(signatures[id1], signatures[id2]) >= threshold:
            parent[find(id1)] = find(id2)

    # Collect members per root.
    groups: Dict[int, List[int]] = {}
    for doc_id in signatures:
        groups.setdefault(find(doc_id), []).append(doc_id)

    result: List[List[Tuple[int, float]]] = []
    for members in groups.values():
        if len(members) < 2:
            continue  # a document all by itself is not a version group
        members.sort()  # oldest (lowest id) first — the reference member
        ref_sig = signatures[members[0]]
        result.append(
            [
                (m, 1.0 if m == members[0] else MinHasher.estimate(ref_sig, signatures[m]))
                for m in members
            ]
        )
    # Deterministic output order: by first member id.
    result.sort(key=lambda g: g[0][0])
    return result
