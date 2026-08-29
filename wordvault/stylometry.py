"""
stylometry.py — the writer's DNA: a measurable fingerprint of style.

Stylometry is the study that settled which Federalist Papers Madison
wrote and unmasked Robert Galbraith as J.K. Rowling.  Its central
insight: every writer leaves habits they do not consciously control,
and the humblest are the strongest — the little FUNCTION WORDS ("of",
"and", "upon", "which") whose rates nobody thinks about and so nobody
can fake.  Add sentence rhythm, punctuation habits, word length, and
vocabulary richness, and a corpus of essays distills to a profile.

The mathematics is Burrows' Delta, the classic of the field: express
every feature as a z-score against the author's own corpus (how many
standard deviations from THEIR normal), and the mean absolute z-score
of a document is its distance from the author's voice.  The profile
also remembers how the author's OWN documents score (the calibration
quantiles), so a verdict is always relative to the writer's real
range, never to an arbitrary threshold.

Three honest cautions, built in rather than footnoted:
* The score is a SIMILARITY, not a probability of authorship.
* Topic pulls on style; function words resist it best, which is why
  they dominate the feature set.
* A profile needs a real corpus (MIN_CORPUS_DOCS documents) — one
  built from three essays would give only false confidence.

Everything here is pure (text in, numbers out) and dependency-free.
The window supplies the documents and owns all UI.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: Where the personal profile lives — beside the library and formats.
PROFILE_PATH = Path.home() / ".wordvault" / "style_profile.json"

#: Function words: frequent, topic-proof, habit-revealing.  The list
#: mixes the modern core with the archaic register (unto, thee, hath)
#: because writing steeped in the KJV has habits there too.
FUNCTION_WORDS = (
    "the of and to a in that it is was he for on are as with his they "
    "i at be this have from or one had by but not what all were we "
    "when your can said there an each which she do how their if will "
    "up other about out then them these so some her would like him "
    "into time has more could who its now than been who am my no "
    "also may must might should shall upon thus therefore moreover "
    "however although whereas hence yet nor because while during "
    "against between through under over after before within without "
    "unto thee thou ye hath doth shalt whom whose wherein whereby"
).split()

#: Documents shorter than this give unstable rates: skipped in builds.
MIN_DOC_WORDS = 200

#: Below this many usable documents, the profile warns about itself.
MIN_CORPUS_DOCS = 20

#: Iterative build: documents farther than this (mean |z|) from the
#: first-round profile are excluded from the second — so a handful of
#: foreign texts in the corpus cannot pollute the final fingerprint.
OUTLIER_DELTA = 2.5

_PUNCT = (";", ":", ",", "!", "?", "—")


# ---------------------------------------------------------------- features --


def extract_features(text: str) -> dict:
    """One document's raw measurements, or {} when too short.

    Keys: "w:<word>" (per 1,000 words), "p:<mark>" (per 1,000 words),
    "sent_mean"/"sent_sd" (sentence length in words), "word_len"
    (mean letters), "ttr" (unique words in the first 1,000 — capped
    so long documents aren't unfairly 'poorer' than short ones).
    """
    words = re.findall(r"[A-Za-z']+", text.lower())
    total = len(words)
    if total < MIN_DOC_WORDS:
        return {}
    per_k = 1000.0 / total

    features: dict = {}
    counts: dict = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    for fw in FUNCTION_WORDS:
        features[f"w:{fw}"] = counts.get(fw, 0) * per_k

    for mark in _PUNCT:
        features[f"p:{mark}"] = text.count(mark) * per_k

    sentences = [len(s.split()) for s in re.split(r"[.!?]+", text)
                 if s.strip()]
    if len(sentences) >= 2:
        features["sent_mean"] = statistics.mean(sentences)
        features["sent_sd"] = statistics.pstdev(sentences)

    features["word_len"] = sum(len(w) for w in words) / total
    features["ttr"] = len(set(words[:1000])) / min(total, 1000)
    return features


# ----------------------------------------------------------------- profile --


@dataclass
class StyleProfile:
    """The distilled fingerprint: each feature's (mean, sd) across the
    author's corpus, plus the calibration — how the author's own
    documents score against it — and the build's paper trail."""

    means: dict = field(default_factory=dict)      # feature -> mean
    sds: dict = field(default_factory=dict)        # feature -> sd
    calibration: dict = field(default_factory=dict)  # "p50"/"p90"/"p99"
    docs_used: int = 0
    words_total: int = 0
    outliers_excluded: int = 0
    created_utc: str = ""
    version: int = 1

    @property
    def too_small(self) -> bool:
        return self.docs_used < MIN_CORPUS_DOCS

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "StyleProfile":
        return cls(**json.loads(text))


def delta(profile: StyleProfile, features: dict) -> float:
    """Burrows' Delta: the document's mean absolute z-score across the
    profile's features — its distance from the author's voice.  Each
    |z| is capped at 10 so one wild feature cannot drown the rest."""
    zs = []
    for name, mean in profile.means.items():
        if name not in features:
            continue
        sd = profile.sds.get(name, 0.0)
        if sd <= 1e-9:
            continue                     # a feature with no variance says nothing
        zs.append(min(abs((features[name] - mean) / sd), 10.0))
    return statistics.mean(zs) if zs else 0.0


def build_profile(feature_sets: list[dict],
                  word_counts: list[int] | None = None,
                  ) -> tuple[StyleProfile, list[int]]:
    """Distill a corpus into a profile, in two rounds.

    The chicken-and-egg problem: the corpus may already contain
    foreign texts (a stray MacDonald or Newton pulled in by import).
    Round one profiles EVERYTHING; documents farther than
    OUTLIER_DELTA from that profile are excluded and round two
    profiles the rest.  Since the great majority of a writer's vault
    is their own writing, the intruders cannot drag the averages far
    — and they stand out sharply once the profile settles.

    Returns (profile, indexes_of_excluded_outliers).
    """
    usable = [(i, f) for i, f in enumerate(feature_sets) if f]

    def distill(pairs) -> StyleProfile:
        profile = StyleProfile()
        names = set()
        for _i, f in pairs:
            names.update(f)
        for name in names:
            values = [f[name] for _i, f in pairs if name in f]
            if len(values) >= 2:
                profile.means[name] = statistics.mean(values)
                profile.sds[name] = statistics.pstdev(values)
        profile.docs_used = len(pairs)
        return profile

    if not usable:
        return StyleProfile(created_utc=_now()), []

    first = distill(usable)
    scored = [(i, f, delta(first, f)) for i, f in usable]
    kept = [(i, f) for i, f, d in scored if d <= OUTLIER_DELTA]
    outliers = [i for i, _f, d in scored if d > OUTLIER_DELTA]
    if len(kept) < 2:                    # a tiny corpus: keep everything
        kept, outliers = usable, []

    profile = distill(kept)
    profile.outliers_excluded = len(outliers)
    profile.created_utc = _now()
    if word_counts:
        profile.words_total = sum(
            word_counts[i] for i, _f in kept if i < len(word_counts))

    # Calibration: how the author's own (kept) documents score.  A new
    # document is then judged against the writer's REAL range.
    own = sorted(delta(profile, f) for _i, f in kept)
    if own:
        profile.calibration = {
            "p50": _quantile(own, 0.50),
            "p90": _quantile(own, 0.90),
            "p99": _quantile(own, 0.99),
        }
    return profile, outliers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(int(q * len(sorted_values)), len(sorted_values) - 1)
    return sorted_values[index]


# ----------------------------------------------------------------- verdict --


def verdict(profile: StyleProfile, doc_delta: float) -> str:
    """"consistent" / "borderline" / "atypical", judged against the
    author's own calibration — not an arbitrary threshold."""
    cal = profile.calibration or {}
    if doc_delta <= cal.get("p90", 1.0):
        return "consistent"
    if doc_delta <= cal.get("p99", 2.0):
        return "borderline"
    return "atypical"


def typicality(profile: StyleProfile, doc_delta: float) -> int:
    """Roughly: 'this document is more typical of you than N% of your
    own essays' — the honest way to phrase a likeness number."""
    cal = profile.calibration or {}
    p50, p90, p99 = (cal.get("p50", 0.8), cal.get("p90", 1.3),
                     cal.get("p99", 2.0))
    if doc_delta <= p50:
        return 90
    if doc_delta <= p90:
        # linear between the median (90) and the 90th percentile (50)
        span = max(p90 - p50, 1e-9)
        return int(90 - 40 * (doc_delta - p50) / span)
    if doc_delta <= p99:
        span = max(p99 - p90, 1e-9)
        return int(50 - 40 * (doc_delta - p90) / span)
    return max(0, int(10 - 5 * (doc_delta - p99)))


def explain(profile: StyleProfile, features: dict,
            top: int = 5) -> list[str]:
    """WHY a document deviates, in plain language — the part that
    makes the number useful.  The `top` largest z-scores, worded."""
    deviations = []
    for name, mean in profile.means.items():
        sd = profile.sds.get(name, 0.0)
        if name not in features or sd <= 1e-9:
            continue
        z = (features[name] - mean) / sd
        if abs(z) >= 1.5:
            deviations.append((abs(z), z, name, features[name], mean))
    deviations.sort(reverse=True)

    lines = []
    for _a, z, name, value, mean in deviations[:top]:
        direction = "more" if z > 0 else "less"
        if name.startswith("w:"):
            lines.append(
                f"the word “{name[2:]}” appears far {direction} often "
                f"than your norm ({value:.1f} vs {mean:.1f} per 1,000 "
                f"words)")
        elif name.startswith("p:"):
            lines.append(
                f"“{name[2:]}” used far {direction} than your norm "
                f"({value:.1f} vs {mean:.1f} per 1,000 words)")
        elif name == "sent_mean":
            pct = int(abs(value - mean) / max(mean, 1e-9) * 100)
            longer = "longer" if z > 0 else "shorter"
            lines.append(f"sentences run about {pct}% {longer} than "
                         f"your norm ({value:.0f} vs {mean:.0f} words)")
        elif name == "sent_sd":
            lines.append(f"sentence lengths vary {direction} than "
                         f"your norm")
        elif name == "word_len":
            lines.append(f"words average {direction} letters than "
                         f"your norm ({value:.1f} vs {mean:.1f})")
        elif name == "ttr":
            richer = "richer" if z > 0 else "plainer"
            lines.append(f"vocabulary is {richer} than your norm")
    return lines
