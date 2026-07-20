"""
diffs.py — snapshot/diff encoding for revision payloads.

Why this exists (DESIGN.md section 4, "Snapshots vs diffs"):
Most revisions differ from their parent by a sentence or two.  Storing the
full text every time would waste space, so most revisions store only a
*delta* — instructions for turning the parent's text into the new text.
Every Nth revision stores a full snapshot so that rebuilding any historical
state never replays more than N deltas.

Delta format
------------
We do NOT use unified-diff text: the standard library can *produce* unified
diffs but cannot *apply* them, and hand-rolling a patch applier is fragile.
Instead a delta is a small JSON list of operations over the parent's lines:

    ["=", i1, i2]        keep parent lines i1..i2 (Python slice semantics)
    ["+", [line, ...]]   insert these literal lines

The operations are produced by difflib.SequenceMatcher, are trivially and
exactly reversible into the new text, and survive any content (unicode,
missing trailing newline, empty documents) because splitlines(keepends=True)
preserves every byte of the original.

Both functions are pure — no database, no I/O — which makes them easy to
test exhaustively (see tests/test_diffs.py).
"""

from __future__ import annotations

import difflib
import json


def make_delta(old: str, new: str) -> str:
    """
    Build a delta string that transforms `old` into `new`.

    The delta is a JSON-encoded list of operations (see module docstring).
    apply_delta(old, make_delta(old, new)) == new  holds for ALL strings.
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    # autojunk=False: the default heuristic can misbehave on texts with many
    # repeated lines (blank lines are common in prose); we want exactness.
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    ops: list = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # Reference the parent's lines by index — cheap, no text stored.
            ops.append(["=", i1, i2])
        elif tag == "delete":
            # Deleted lines simply do not appear in the output; store nothing.
            continue
        else:  # "replace" or "insert" — store the new lines literally.
            ops.append(["+", new_lines[j1:j2]])

    # ensure_ascii=False keeps non-English text human-readable in the DB.
    return json.dumps(ops, ensure_ascii=False)


def apply_delta(old: str, delta: str) -> str:
    """Reconstruct the new text from the parent text and a delta string."""
    old_lines = old.splitlines(keepends=True)

    parts: list[str] = []
    for op in json.loads(delta):
        if op[0] == "=":
            # ["=", i1, i2] — copy the referenced slice of the parent.
            parts.extend(old_lines[op[1]:op[2]])
        else:
            # ["+", [lines]] — literal insertion.
            parts.extend(op[1])

    return "".join(parts)
