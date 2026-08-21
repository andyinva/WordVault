"""
spelling.py — spell checking for the editor.

Wraps the optional `pyspellchecker` package (pip install pyspellchecker)
behind a small class the highlighter and context menu use.  Without the
package installed, is_available() is False and everything else quietly
does nothing — spelling is a convenience, never a requirement.

Design points:
  * A PERSISTENT USER DICTIONARY at ~/.wordvault/user_dictionary.txt
    (one word per line) holds the author's additions — and is pre-seeded
    with the Bible book names WordVault already knows, so "Melchizedek"
    country is not a sea of red squiggles from day one... (book names at
    least; the author adds the rest of the names once each).
  * Results are cached per word: checking a book-length document costs
    one dictionary lookup per DISTINCT word.
  * Words with digits, ALL-CAPS tokens (acronyms), and Markdown marker
    characters are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

#: Tokenizer for prose words; apostrophes stay inside ("God's", "don't").
WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")

_USER_DICT = Path.home() / ".wordvault" / "user_dictionary.txt"


def _seed_words() -> set[str]:
    """Words WordVault already knows are legitimate: Bible book names."""
    from wordvault.storage.scripture import _BASE_BOOKS, _NUMBERED_BOOKS

    words: set[str] = set()
    for name in list(_BASE_BOOKS.values()) + list(_NUMBERED_BOOKS.values()):
        words.update(w.lower() for w in name.split())
    return words


def skeleton(word: str) -> str:
    """A word's CONSONANT SKELETON — the bones that survive phonetic
    misspelling.  Corpus analysis of this author's errors showed they
    follow sound: vowels wobble, doubled letters collapse, s/z and
    c/k trade places — but the consonant frame stays true.  So
    'jeprodising', 'jeoprodising', and 'jeoprodizing' all reduce to
    the same skeleton as 'jeopardizing' (jprtsng), and a skeleton
    index finds the word ordinary edit-distance search cannot reach.

    Reductions: lowercase; ph->f; c,q,ck->k; z,x->s; d->t (voicing
    pairs); collapse doubles; keep the first letter, drop vowels
    (a e i o u y) after it."""
    w = word.lower()
    w = w.replace("ph", "f").replace("ck", "k")
    w = re.sub(r"[cq]", "k", w)
    w = re.sub(r"[zx]", "s", w)
    w = w.replace("d", "t")
    w = re.sub(r"(.)\1+", r"\1", w)          # doubled letters collapse
    if not w:
        return ""
    return w[0] + re.sub(r"[aeiouy]", "", w[1:])


class Spelling:
    """Cached spell checking with a persistent user dictionary."""

    def __init__(self):
        try:
            from spellchecker import SpellChecker
            self._spell = SpellChecker()
        except ImportError:
            self._spell = None
        self._cache: dict[str, bool] = {}     # word (lower) -> is known
        self._user_words: set[str] = set()
        #: typed (lower) -> (corrected, times) — the author's own error
        #: history, fed by MainWindow from the spelling log.  The best
        #: clue of all: a word misspelled once is misspelled the same
        #: way again, and its correction is already on record.
        self._history: dict[str, tuple[str, int]] = {}
        self._skeletons: dict[str, list] | None = None   # lazy index

        if self._spell is not None:
            self._user_words = _seed_words()
            try:
                _USER_DICT.parent.mkdir(parents=True, exist_ok=True)
                if _USER_DICT.exists():
                    self._user_words.update(
                        w.strip().lower()
                        for w in _USER_DICT.read_text(encoding="utf-8").split("\n")
                        if w.strip()
                    )
            except OSError:
                pass  # no user dictionary is not a reason to fail

    def is_available(self) -> bool:
        return self._spell is not None

    # -- checking -----------------------------------------------------------

    def is_misspelled(self, word: str) -> bool:
        """True when the word is unknown to both the dictionary and the
        author.  Digits, acronyms, and 1-letter tokens are never flagged."""
        if self._spell is None or len(word) < 2:
            return False
        if word.isupper() or any(ch.isdigit() for ch in word):
            return False
        key = word.lower().strip("'")
        if not key:
            return False
        cached = self._cache.get(key)
        if cached is not None:
            return not cached
        known = key in self._user_words or not self._spell.unknown([key])
        self._cache[key] = known
        return not known

    def misspelled_spans(self, line: str) -> list[tuple[int, int]]:
        """(start, end) offsets of every misspelled word in one line —
        what the highlighter underlines."""
        return [
            (m.start(), m.end())
            for m in WORD_RE.finditer(line)
            if self.is_misspelled(m.group())
        ]

    # -- fixing -------------------------------------------------------------

    def common_misspellings(self) -> dict[str, str]:
        """typed -> corrected for ~2,600 CLASSIC English misspellings
        (bundled from Wikipedia's community list via the MIT-licensed
        myint/misspellings dataset — see wordvault/data/).  The second
        well of suggestions: the author's own history answers first,
        the collective history of English spellers answers next."""
        if not hasattr(self, "_common"):
            self._common = {}
            data = (Path(__file__).resolve().parents[1]
                    / "data" / "common_misspellings.txt")
            try:
                for line in data.read_text(encoding="utf-8").split("\n"):
                    if line and not line.startswith("#") and "->" in line:
                        typed, _, fix = line.partition("->")
                        self._common[typed.strip()] = fix.strip()
            except OSError:
                pass          # a missing data file is not a failure
        return self._common

    def set_history(self, pairs: dict[str, tuple[str, int]]) -> None:
        """Feed the author's typed->corrected history (from the
        spelling log).  Invalidates the skeleton index so past
        corrections join it."""
        self._history = dict(pairs)
        self._skeletons = None

    def _skeleton_index(self) -> dict[str, list]:
        """skeleton -> [(rank, word)] over the WHOLE known vocabulary:
        the standard dictionary, the personal dictionary, and every
        word the author has ever corrected TO.  Built lazily once
        (a second's work, then instant) — this is what lets a
        far-off phonetic misspelling find its word."""
        if self._skeletons is not None:
            return self._skeletons
        index: dict[str, list] = {}

        def put(word: str, rank: float) -> None:
            index.setdefault(skeleton(word), []).append((rank, word))

        frequencies = getattr(getattr(self._spell, "word_frequency", None),
                              "dictionary", {}) or {}
        for word, count in frequencies.items():
            if len(word) > 2 and "'" not in word:
                put(word, float(count))
        boost = (max(frequencies.values()) if frequencies else 1.0) * 10
        for word in self._user_words:
            put(word, boost)                  # the author's words outrank
        for corrected, _n in self._history.values():
            put(corrected.lower(), boost * 2)  # proven corrections most
        for mates in index.values():
            mates.sort(reverse=True)
        self._skeletons = index
        return index

    def suggestions(self, word: str, limit: int = 6) -> list[str]:
        """Best replacement candidates, most likely first — drawing on
        three wells, strongest first:

        1. the author's OWN history: this exact misspelling was fixed
           before, so its correction leads;
        2. sound-alikes: words sharing the consonant skeleton — how
           'jeprodising' finds 'jeopardizing' though it is too many
           edits away for ordinary suggestion search (Aug 2026);
        3. the classic edit-distance candidates, frequency-ranked.
        """
        if self._spell is None:
            return []
        key = word.lower().strip("'")
        ordered: list[str] = []

        past = self._history.get(key)
        if past:
            ordered.append(past[0].lower())

        common = self.common_misspellings().get(key)
        if common and common not in ordered:
            ordered.append(common)      # the classics, known in advance

        for _rank, mate in self._skeleton_index().get(skeleton(key), [])[:4]:
            if mate != key and mate not in ordered:
                ordered.append(mate)

        candidates = self._spell.candidates(key) or set()
        for mate in sorted(candidates,
                           key=self._spell.word_usage_frequency,
                           reverse=True):
            if mate not in ordered:
                ordered.append(mate)

        ordered = ordered[:limit]
        # Mirror the original word's capitalization.
        if word[:1].isupper():
            ordered = [w.capitalize() for w in ordered]
        return ordered

    # -- the dictionary dialog's questions ----------------------------------

    def is_personal(self, word: str) -> bool:
        """Is this one of the author's own added words?"""
        return word.lower().strip("'") in self._user_words

    def is_standard(self, word: str) -> bool:
        """Does the STANDARD dictionary know it (personal words aside)?"""
        if self._spell is None:
            return False
        return not self._spell.unknown([word.lower().strip("'")])

    def personal_words(self) -> list[str]:
        """The author's dictionary, alphabetical."""
        return sorted(self._user_words)

    def prefix_matches(self, prefix: str, limit: int = 25) -> list[str]:
        """STANDARD-dictionary words beginning with `prefix`, most
        common first — the dictionary dialog's completion, so typing
        'jeo' surfaces jeopardy and its family (Aug 2026: the list
        used to show only personal words, which knew Jeremiah but
        not Jeopardy).  Uses a lazily-built sorted word list with a
        binary-searched prefix range: instant at any size."""
        if self._spell is None or not prefix:
            return []
        if not hasattr(self, "_sorted_words"):
            frequencies = getattr(
                getattr(self._spell, "word_frequency", None),
                "dictionary", {}) or {}
            self._sorted_words = sorted(frequencies)
            self._word_freq = frequencies
        import bisect

        prefix = prefix.lower()
        lo = bisect.bisect_left(self._sorted_words, prefix)
        hi = bisect.bisect_left(self._sorted_words, prefix + "￿")
        span = self._sorted_words[lo:hi]
        span.sort(key=lambda w: self._word_freq.get(w, 0), reverse=True)
        return span[:limit]

    def add_to_dictionary(self, word: str) -> None:
        """Remember a word forever (persisted in the user dictionary)."""
        key = word.lower().strip("'")
        if not key or key in self._user_words:
            return
        self._user_words.add(key)
        self._cache[key] = True
        try:
            with open(_USER_DICT, "a", encoding="utf-8") as fh:
                fh.write(key + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Error-pattern analysis (the "spelling habits" watcher).
#
# Corpus analysis of this author's 30-million-word archive showed the
# errors follow SOUND, not fingers: two-thirds of substitutions are
# vowel-for-vowel (the unstressed "uh" the ear cannot spell), and the
# most-dropped letters are the weakly-heard ones (-ing g, silent u).
# These helpers classify each observed correction so the editor can keep
# a running mirror of the author's habits.
# ---------------------------------------------------------------------------

_VOWELS = set("aeiou")


def classify_error(typed: str, corrected: str) -> tuple[str, str]:
    """
    (kind, detail) describing the single edit between a typo and its fix.

    Kinds: 'vowel swap', 'wrong letter', 'dropped letter', 'added letter',
    'swapped letters', or 'other' (more than one edit apart — e.g. a
    whole different word was chosen).
    """
    t, c = typed.lower().strip("'"), corrected.lower().strip("'")
    if len(t) == len(c) - 1:                      # a letter was dropped
        for i in range(len(c)):
            if t[:i] + c[i] + t[i:] == c:
                return "dropped letter", c[i]
    if len(t) == len(c) + 1:                      # a letter was added
        for i in range(len(t)):
            if t[:i] + t[i + 1:] == c:
                return "added letter", t[i]
    if len(t) == len(c):
        diffs = [i for i in range(len(t)) if t[i] != c[i]]
        if len(diffs) == 1:
            i = diffs[0]
            if t[i] in _VOWELS and c[i] in _VOWELS:
                return "vowel swap", f"{t[i]}->{c[i]}"
            return "wrong letter", f"{t[i]}->{c[i]}"
        if (len(diffs) == 2 and diffs[1] == diffs[0] + 1
                and t[diffs[0]] == c[diffs[1]] and t[diffs[1]] == c[diffs[0]]):
            return "swapped letters", c[diffs[0]] + c[diffs[1]]
    return "other", ""


def extract_corrections(old_text, new_text, is_misspelled):
    """
    Mine spelling fixes out of an edit: word pairs where a MISSPELLED old
    word was replaced, in place, by a well-spelled new word.  Used at
    save time to catch corrections made by hand (not via the menu).

    is_misspelled — callable(word) -> bool (injected so this stays pure
    and testable without a dictionary).
    """
    from difflib import SequenceMatcher

    old_words = WORD_RE.findall(old_text)
    new_words = WORD_RE.findall(new_text)
    matcher = SequenceMatcher(a=old_words, b=new_words, autojunk=False)

    fixes: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue  # only 1:1, in-place word replacements count
        for old_w, new_w in zip(old_words[i1:i2], new_words[j1:j2]):
            if (old_w.lower() != new_w.lower()
                    and is_misspelled(old_w) and not is_misspelled(new_w)):
                fixes.append((old_w, new_w))
    return fixes


def apply_correction_to_text(text: str, typed: str, corrected: str):
    """
    Fix every other whole-word occurrence of a just-corrected misspelling
    ("pages ahead" AND behind — the whole document).

    Words are bursty: a rare word that appears once (a proper noun above
    all) is very likely to appear again nearby, so one correction predicts
    the need for more.  Case handling: a correction that is itself
    capitalized (a proper noun like Machpelah) is used verbatim; a
    lowercase correction mirrors each occurrence's capitalization.

    Returns (new_text, replacements_made).
    """
    if typed.lower() == corrected.lower():
        return text, 0
    pattern = re.compile(rf"\b{re.escape(typed)}\b", re.IGNORECASE)

    def repl(match: re.Match) -> str:
        occurrence = match.group()
        if corrected[:1].isupper():
            return corrected                     # proper noun: verbatim
        if occurrence[:1].isupper():
            return corrected.capitalize()        # mirror sentence case
        return corrected

    return pattern.subn(repl, text)


#: One shared instance — the dictionary load is not free, do it once.
_instance: Optional[Spelling] = None


def get_spelling() -> Spelling:
    global _instance
    if _instance is None:
        _instance = Spelling()
    return _instance
