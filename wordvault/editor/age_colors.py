"""
age_colors.py — color text by age (stage 7, DESIGN.md section 8).

The idea: because every revision is stored, we can work out WHEN each
line of the current text first appeared, and tint old material differently
from new — at a glance the author sees which parts of an essay are
long-settled and which are fresh.

Granularity is the LINE, not the character: line-level tracking is fast
even for book-length documents with long histories, and prose reads in
lines anyway.  A line "survives" from revision to revision when difflib
matches it as equal; edited or new lines take the age of the revision
that introduced them.

The computation (line_birth_indices) is pure — lists of strings in, list
of ints out — so it is tested headless.  Only the small color helpers
touch Qt.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from PyQt6.QtGui import QColor

#: The tint of the OLDEST text: a muted archive blue-gray.  Newest text
#: uses the editor's normal text color; everything between interpolates.
OLDEST_COLOR = QColor("#7d8fa9")

#: While time traveling, words that have SINCE been changed get a quiet
#: background wash — wheat, kin to the amber history border, deliberately
#: not bold.  One shade per theme.
CHANGED_WASH_LIGHT = QColor("#f2e7c9")
CHANGED_WASH_DARK = QColor("#4a4232")


def corresponding_line(old_text: str, new_text: str, line: int) -> int:
    """Where line `line` of old_text lives in new_text.

    The view-holding rule for time travel: a scrollbar VALUE is a lie
    across revisions (older drafts have different text above the same
    passage), but the passage's own lines mostly survive from revision
    to revision — so difflib finds the watched line's twin and the view
    follows CONTENT, not pixels.  Lines inside a rewritten region map
    proportionally into their replacement; lines that vanished map to
    the seam where they used to be.  Pure text in, an int out.
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    if not old_lines or not new_lines:
        return 0
    line = max(0, min(line, len(old_lines) - 1))
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if not (i1 <= line < i2):
            continue
        if tag == "equal":
            return j1 + (line - i1)          # the very same line
        if j2 > j1:                          # rewritten: keep proportion
            fraction = (line - i1) / max(i2 - i1, 1)
            return min(j1 + int(fraction * (j2 - j1)), j2 - 1)
        return min(j1, len(new_lines) - 1)   # deleted: land on the seam
    return len(new_lines) - 1


def changed_word_spans(old_text: str,
                       new_text: str) -> list[tuple[int, int]]:
    """Character spans in `old_text` of the words that do NOT survive
    into `new_text` — the material that has since been rewritten or
    removed.

    Word-level (whitespace-split) difflib match: 'equal' words are the
    survivors, 'replace'/'delete' words are the changed ones.  Adjacent
    spans are merged so the caller paints few, long washes rather than
    many single-word ones.  Pure text in, plain ints out — testable
    headless, like line_birth_indices above.
    """
    old_tokens = list(re.finditer(r"\S+", old_text))
    new_words = re.findall(r"\S+", new_text)
    matcher = SequenceMatcher(a=[t.group() for t in old_tokens],
                              b=new_words, autojunk=False)
    spans: list[tuple[int, int]] = []
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag not in ("replace", "delete") or i2 <= i1:
            continue
        start = old_tokens[i1].start()
        end = old_tokens[i2 - 1].end()
        # Merge with the previous span when only whitespace separates
        # them — one calm wash instead of a flicker of small ones.
        if spans and start <= spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    return spans


def line_birth_indices(texts: list[str]) -> list[int]:
    """
    For each line of texts[-1] (the newest state), the index in `texts`
    of the revision that introduced it.

    Walks the history forward, carrying each line's birth index along
    whenever difflib says the line survived unchanged.
    """
    if not texts:
        return []

    # Every line of the first revision was born there (index 0).
    ages = [0] * len(texts[0].splitlines())

    for i in range(1, len(texts)):
        old_lines = texts[i - 1].splitlines()
        new_lines = texts[i].splitlines()
        matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

        new_ages: list[int] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                new_ages.extend(ages[i1:i2])       # lines survived: keep age
            elif tag in ("replace", "insert"):
                new_ages.extend([i] * (j2 - j1))   # new/edited lines born now
            # 'delete': the lines are gone; nothing to carry forward.
        ages = new_ages

    return ages


def age_rank(birth_index: int, revision_count: int) -> float:
    """Birth index -> 0.0 (oldest) … 1.0 (newest)."""
    if revision_count <= 1:
        return 1.0
    return birth_index / (revision_count - 1)


def age_color(rank: float, newest: QColor) -> QColor:
    """Linear blend from OLDEST_COLOR (rank 0) to the normal text color
    (rank 1).  Plain RGB interpolation — subtle is the goal."""
    r = OLDEST_COLOR.red() + (newest.red() - OLDEST_COLOR.red()) * rank
    g = OLDEST_COLOR.green() + (newest.green() - OLDEST_COLOR.green()) * rank
    b = OLDEST_COLOR.blue() + (newest.blue() - OLDEST_COLOR.blue()) * rank
    return QColor(int(r), int(g), int(b))
