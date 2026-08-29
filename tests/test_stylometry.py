"""
Headless tests for the stylometry engine: the fingerprint must be
stable for one voice, must separate a genuinely different voice, must
survive intruders in its own training corpus (the chicken-and-egg
build), and must explain itself in plain language.
"""

import random

from wordvault.stylometry import (
    MIN_DOC_WORDS,
    StyleProfile,
    build_profile,
    delta,
    explain,
    extract_features,
    typicality,
    verdict,
)


def _voice_a(rng, sentences=60):
    """A plain, modern voice: short sentences, 'the/and/of' heavy."""
    words = ["the", "and", "of", "faith", "hope", "work", "day",
             "light", "word", "grace", "to", "a", "in", "is", "was"]
    out = []
    for _ in range(sentences):
        n = rng.randint(6, 12)
        out.append(" ".join(rng.choice(words) for _ in range(n)) + ".")
    return " ".join(out)


def _voice_b(rng, sentences=60):
    """An archaic, ornate voice: long sentences, 'upon/thus/thee',
    semicolons everywhere."""
    words = ["upon", "thus", "thee", "thou", "hath", "whereby",
             "dominion", "prophecy", "kingdom", "moreover", "unto",
             "wherein", "shall", "ye", "doth"]
    out = []
    for _ in range(sentences):
        n = rng.randint(25, 40)
        sentence = " ".join(rng.choice(words) for _ in range(n))
        out.append(sentence + "; " + rng.choice(words) + ".")
    return " ".join(out)


def _corpus(maker, count, seed):
    rng = random.Random(seed)
    return [maker(rng) for _ in range(count)]


def test_short_text_yields_no_features():
    assert extract_features("too short " * 10) == {}
    assert len("word " * MIN_DOC_WORDS) > 0  # sanity


def test_own_documents_score_consistent():
    texts = _corpus(_voice_a, 30, seed=1)
    profile, outliers = build_profile([extract_features(t) for t in texts])
    assert outliers == []
    fresh = _voice_a(random.Random(99))
    d = delta(profile, extract_features(fresh))
    assert verdict(profile, d) in ("consistent", "borderline")
    assert typicality(profile, d) >= 40


def test_a_foreign_voice_is_atypical():
    texts = _corpus(_voice_a, 30, seed=2)
    profile, _ = build_profile([extract_features(t) for t in texts])
    foreign = _voice_b(random.Random(7))
    d = delta(profile, extract_features(foreign))
    assert verdict(profile, d) == "atypical"
    assert typicality(profile, d) <= 10


def test_intruders_in_the_corpus_are_excluded_by_the_second_round():
    """The chicken-and-egg build: MacDonald and Newton were already in
    the vault, so the profile must first be built WITH them and then
    shed them as outliers."""
    own = _corpus(_voice_a, 28, seed=3)
    intruders = _corpus(_voice_b, 2, seed=4)
    features = [extract_features(t) for t in own + intruders]
    profile, outliers = build_profile(features)
    assert set(outliers) == {28, 29}
    assert profile.outliers_excluded == 2
    assert profile.docs_used == 28


def test_explanation_names_the_deviating_habits():
    texts = _corpus(_voice_a, 30, seed=5)
    profile, _ = build_profile([extract_features(t) for t in texts])
    foreign = extract_features(_voice_b(random.Random(11)))
    lines = explain(profile, foreign)
    assert lines, "an atypical document must be explained"
    joined = " ".join(lines)
    assert "your norm" in joined


def test_profile_round_trips_through_json():
    texts = _corpus(_voice_a, 25, seed=6)
    profile, _ = build_profile([extract_features(t) for t in texts])
    clone = StyleProfile.from_json(profile.to_json())
    assert clone.means == profile.means
    assert clone.calibration == profile.calibration
    assert clone.docs_used == profile.docs_used


def test_small_corpus_warns_about_itself():
    texts = _corpus(_voice_a, 5, seed=8)
    profile, _ = build_profile([extract_features(t) for t in texts])
    assert profile.too_small
