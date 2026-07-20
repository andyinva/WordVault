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

from difflib import SequenceMatcher

from PyQt6.QtGui import QColor

#: The tint of the OLDEST text: a muted archive blue-gray.  Newest text
#: uses the editor's normal text color; everything between interpolates.
OLDEST_COLOR = QColor("#7d8fa9")


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
