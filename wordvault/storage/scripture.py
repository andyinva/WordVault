"""
scripture.py — Bible reference detection (the scripture index).

Finds references like "John 3:16", "1 Cor. 15:22", "Gen 1:1-5" or
"II Timothy 2:15" in plain text and normalizes them to canonical
(book, chapter, verse) form.  The store keeps one row per cited verse in
the scripture_refs table, refreshed whenever a revision is saved — so
"which essays cite this verse?" and "which documents share verses with
this one?" are instant queries.

This gives the library a second identification signal alongside text
similarity: two essays that quote the same cluster of verses are almost
certainly about the same material, even when the prose differs.

Pure standard library, no database code — the store calls
parse_references() and stores the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Book names and their common abbreviations, all lower-case.  Values are
# the canonical display names.  Single-chapter books (Obadiah, Philemon,
# Jude...) are included; "chapter:verse" citations of them are rare but
# harmless to match.
# ---------------------------------------------------------------------------
_BASE_BOOKS = {
    "genesis": "Genesis", "gen": "Genesis",
    "exodus": "Exodus", "exod": "Exodus", "ex": "Exodus",
    "leviticus": "Leviticus", "lev": "Leviticus",
    "numbers": "Numbers", "num": "Numbers",
    "deuteronomy": "Deuteronomy", "deut": "Deuteronomy", "dt": "Deuteronomy",
    "joshua": "Joshua", "josh": "Joshua",
    "judges": "Judges", "judg": "Judges",
    "ruth": "Ruth",
    "ezra": "Ezra",
    "nehemiah": "Nehemiah", "neh": "Nehemiah",
    "esther": "Esther", "esth": "Esther",
    "job": "Job",
    "psalms": "Psalms", "psalm": "Psalms", "psa": "Psalms", "ps": "Psalms",
    "proverbs": "Proverbs", "prov": "Proverbs",
    "ecclesiastes": "Ecclesiastes", "eccl": "Ecclesiastes",
    "song of solomon": "Song of Solomon", "song of songs": "Song of Solomon",
    "isaiah": "Isaiah", "isa": "Isaiah",
    "jeremiah": "Jeremiah", "jer": "Jeremiah",
    "lamentations": "Lamentations", "lam": "Lamentations",
    "ezekiel": "Ezekiel", "ezek": "Ezekiel",
    "daniel": "Daniel", "dan": "Daniel",
    "hosea": "Hosea", "hos": "Hosea",
    "joel": "Joel",
    "amos": "Amos",
    "obadiah": "Obadiah", "obad": "Obadiah",
    "jonah": "Jonah",
    "micah": "Micah", "mic": "Micah",
    "nahum": "Nahum", "nah": "Nahum",
    "habakkuk": "Habakkuk", "hab": "Habakkuk",
    "zephaniah": "Zephaniah", "zeph": "Zephaniah",
    "haggai": "Haggai", "hag": "Haggai",
    "zechariah": "Zechariah", "zech": "Zechariah",
    "malachi": "Malachi", "mal": "Malachi",
    "matthew": "Matthew", "matt": "Matthew", "mt": "Matthew",
    "mark": "Mark", "mk": "Mark",
    "luke": "Luke", "lk": "Luke",
    "john": "John", "jn": "John",
    "acts": "Acts",
    "romans": "Romans", "rom": "Romans",
    "galatians": "Galatians", "gal": "Galatians",
    "ephesians": "Ephesians", "eph": "Ephesians",
    "philippians": "Philippians", "phil": "Philippians",
    "colossians": "Colossians", "col": "Colossians",
    "titus": "Titus",
    "philemon": "Philemon", "philem": "Philemon",
    "hebrews": "Hebrews", "heb": "Hebrews",
    "james": "James", "jas": "James",
    "jude": "Jude",
    "revelation": "Revelation", "rev": "Revelation",
}

#: Books that come in numbered pairs/triples ("1 Corinthians", "2 Kings",
#: "3 John").  Keys are the base name/abbreviations; the number prefix is
#: added programmatically in Arabic ("1 cor") and Roman ("i cor") forms.
_NUMBERED_BOOKS = {
    "samuel": "Samuel", "sam": "Samuel",
    "kings": "Kings", "kgs": "Kings",
    "chronicles": "Chronicles", "chron": "Chronicles", "chr": "Chronicles",
    "corinthians": "Corinthians", "cor": "Corinthians",
    "thessalonians": "Thessalonians", "thess": "Thessalonians",
    "timothy": "Timothy", "tim": "Timothy",
    "peter": "Peter", "pet": "Peter",
    "john": "John", "jn": "John",
}


def _build_book_map() -> dict[str, str]:
    """key (as typed, lower-case) -> canonical book name."""
    books = dict(_BASE_BOOKS)
    for arabic, roman in (("1", "i"), ("2", "ii"), ("3", "iii")):
        for key, base in _NUMBERED_BOOKS.items():
            canonical = f"{arabic} {base}"
            books[f"{arabic} {key}"] = canonical    # "1 cor"
            books[f"{arabic}{key}"] = canonical     # "1cor"
            books[f"{roman} {key}"] = canonical     # "i cor"
    return books


_BOOKS = _build_book_map()

# Longest keys first so "1 corinthians" wins over plain "corinthians",
# and "song of solomon" over nothing at all.  (?<![A-Za-z0-9]) stops
# "context 3:16" from matching the "ex" inside "context".
_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(re.escape(k) for k in sorted(_BOOKS, key=len, reverse=True))
    + r")\.?\s+(\d{1,3})\s*:\s*(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?",
    re.IGNORECASE,
)

#: Verse ranges longer than this are indexed by their first verse only —
#: "Psalm 119:1-176" should not explode into 176 rows.
RANGE_CAP = 30


@dataclass(frozen=True)
class ScriptureRef:
    """One normalized reference, possibly a range within one chapter."""

    book: str          # canonical name, e.g. "1 Corinthians"
    chapter: int
    verse_start: int
    verse_end: int     # == verse_start for a single verse

    def display(self) -> str:
        if self.verse_end != self.verse_start:
            return f"{self.book} {self.chapter}:{self.verse_start}-{self.verse_end}"
        return f"{self.book} {self.chapter}:{self.verse_start}"

    def verses(self) -> list[tuple[str, int, int]]:
        """Expand to (book, chapter, verse) rows, capped (see RANGE_CAP)."""
        end = self.verse_end
        if end - self.verse_start + 1 > RANGE_CAP:
            end = self.verse_start
        return [(self.book, self.chapter, v)
                for v in range(self.verse_start, end + 1)]


def parse_references(text: str) -> list[ScriptureRef]:
    """Every scripture reference in the text, normalized, de-duplicated,
    in order of first appearance."""
    seen: set[ScriptureRef] = set()
    out: list[ScriptureRef] = []
    for m in _PATTERN.finditer(text):
        book = _BOOKS[" ".join(m.group(1).lower().split())]
        chapter = int(m.group(2))
        start = int(m.group(3))
        end = int(m.group(4)) if m.group(4) else start
        if end < start:            # "John 3:18-16" — take it as one verse
            end = start
        ref = ScriptureRef(book, chapter, start, end)
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out
