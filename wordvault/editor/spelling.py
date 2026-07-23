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

    def suggestions(self, word: str, limit: int = 5) -> list[str]:
        """Best replacement candidates, most likely first."""
        if self._spell is None:
            return []
        candidates = self._spell.candidates(word.lower()) or set()
        ranked = sorted(
            candidates,
            key=lambda w: self._spell.word_usage_frequency(w), reverse=True,
        )[:limit]
        # Mirror the original word's capitalization.
        if word[:1].isupper():
            ranked = [w.capitalize() for w in ranked]
        return ranked

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
