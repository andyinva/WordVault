"""
indexes.py — the book's back matter: the Subject Index and the
Scripture Index, with TRUE page numbers.

This is the marriage promised in stage F4: the detection rules from
Andrew's Word index builder (tools/index_reference/) joined to
WordVault's own paginator.  His tool planted hidden XE field markers
and needed Word's F9 to look up pages; here the pages come straight
from the print layout (renderer.collect_blocks), so the indexes are
correct by construction — no Word, no field codes, no refresh step.

What was ported faithfully from the original:

  * the controlled vocabulary (vocabulary.json): a headword maps to a
    plain list of triggers, or to {"triggers": [...], "max": n,
    "scope": "paragraph"|"chapter"|"document"} — triggers are
    case-insensitive substrings, or regular expressions when prefixed
    "re:";
  * occurrence caps: at most `max` marked paragraphs per scope (his
    standard run was max 2 per chapter), so a common word cannot
    flood the index;
  * paragraph granularity: many mentions in one paragraph count once;
  * canonical Scripture ordering: Genesis before Exodus, chapter and
    verse numerically — his zero-padded sort keys, now simply how the
    entries are sorted.

What was replaced: his BibleCanon — WordVault's own scripture parser
(wordvault.storage.scripture) already knows the 66 books and their
abbreviations, and one canon in a codebase is enough.

The scanning half of this module is pure Python; only
build_back_matter touches Qt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wordvault.formatter.book import BookProject, BookProjectError
from wordvault.storage.scripture import book_number, parse_references

#: Andrew's standard density controls (his usual command line was
#: --subject-scope chapter --subject-max 2); per-term settings in the
#: vocabulary file override these.
DEFAULT_MAX = 2
DEFAULT_SCOPE = "chapter"

_VALID_SCOPES = {"paragraph", "chapter", "document"}


class VocabEntry:
    """One subject headword with its trigger patterns and optional cap
    (ported from the Word index builder — same semantics)."""

    def __init__(self, headword: str, triggers, max_count=None, scope=None):
        self.headword = headword
        self.patterns = [self._compile(t) for t in triggers]
        self.max_count = max_count
        self.scope = scope if scope in _VALID_SCOPES else None

    @staticmethod
    def _compile(trigger: str):
        if trigger.startswith("re:"):
            return re.compile(trigger[3:], re.IGNORECASE)
        return re.compile(re.escape(trigger), re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.patterns)


def load_vocabulary(path: str | Path) -> list[VocabEntry]:
    """Read a vocabulary.json (both forms; see module docstring).
    Every failure names the problem — the Formatter shows it as-is."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BookProjectError(f"Cannot read vocabulary: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BookProjectError(
            f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BookProjectError(
            f"{path.name}: a vocabulary is a JSON object of "
            f"headword -> triggers")

    entries = []
    for headword, value in data.items():
        if isinstance(value, dict):
            entries.append(VocabEntry(headword, value.get("triggers", []),
                                      value.get("max"), value.get("scope")))
        else:
            entries.append(VocabEntry(headword, value))
    return entries


def collect_index_entries(blocks, vocabulary):
    """Scan the laid-out body and gather both indexes' raw material.

    blocks: (text, page, heading_level) triples from
    renderer.collect_blocks — already in page order.  A level-1
    heading starts a new CHAPTER (the bucket the chapter-scope caps
    are measured in).  Returns (scripture, subjects):

      scripture: {book: {(chapter, verse_display): sorted pages}}
      subjects:  {headword: sorted pages}
    """
    scripture: dict = {}
    subjects: dict = {}
    chapter_id = 0
    cap_counts: dict = {}       # (headword, bucket) -> marked paragraphs

    for text, page, level in blocks:
        if level == 1:
            chapter_id += 1

        # --- Scripture: every reference, deduplicated per paragraph ---
        seen_here = set()
        for ref in parse_references(text):
            display = (f"{ref.chapter}:{ref.verse_start}"
                       + (f"-{ref.verse_end}"
                          if ref.verse_end != ref.verse_start else ""))
            key = (ref.chapter, ref.verse_start, ref.verse_end)
            if key in seen_here:
                continue        # repeats in one paragraph count once
            seen_here.add(key)
            pages = scripture.setdefault(ref.book, {}).setdefault(
                (ref.chapter, ref.verse_start, ref.verse_end, display), [])
            if not pages or pages[-1] != page:
                pages.append(page)

        # --- Subjects: headings are titles, not discussion — skipped ---
        if level or vocabulary is None:
            continue
        for entry in vocabulary:
            if not entry.matches(text):
                continue
            cap = entry.max_count if entry.max_count is not None \
                else DEFAULT_MAX
            scope = entry.scope or DEFAULT_SCOPE
            if scope == "chapter":
                bucket = (entry.headword, chapter_id)
            elif scope == "document":
                bucket = (entry.headword,)
            else:                       # paragraph: no cross-cap at all
                bucket = None
            if bucket is not None:
                if cap is not None and cap_counts.get(bucket, 0) >= cap:
                    continue
                cap_counts[bucket] = cap_counts.get(bucket, 0) + 1
            pages = subjects.setdefault(entry.headword, [])
            if not pages or pages[-1] != page:
                pages.append(page)

    return scripture, subjects


def _pages_text(pages) -> str:
    return ", ".join(str(p) for p in pages)


def build_back_matter(fmt, project: BookProject, blocks):
    """The back-matter QTextDocument: Scripture Index (canonical book
    order, verses numeric) and/or Subject Index (alphabetical), per
    the project's checkboxes.  None when neither is wanted.

    blocks come from renderer.collect_blocks on the laid-out body, so
    every page number here is where the printer truly puts the words.
    """
    want_subject = bool(project.sections.get("subject_index"))
    want_scripture = bool(project.sections.get("scripture_index"))
    if not (want_subject or want_scripture):
        return None

    vocabulary = None
    if want_subject:
        if not project.vocabulary_path.strip():
            raise BookProjectError(
                "The Subject Index needs a vocabulary file — choose "
                "one with the Formatter's 'Subject Vocabulary…' button "
                "(a vocabulary.json from the Word Index Creator works "
                "as-is).")
        vocabulary = load_vocabulary(project.vocabulary_path)

    scripture, subjects = collect_index_entries(blocks, vocabulary)

    # Qt only from here down (the scan above is testable anywhere).
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextCursor, QTextDocument

    from wordvault.formatter.frontmatter import _write

    family = fmt.body.font or "Georgia"
    document = QTextDocument()
    cursor = QTextCursor(document)
    first = True

    def heading(text: str) -> None:
        nonlocal first
        _write(cursor, text, family=family, size_pt=16.0, first=first,
               top_margin_pt=6.0, page_break=True)
        first = False

    def line(text: str, *, indent: bool = False, bold: bool = False,
             size: float = 9.5) -> None:
        nonlocal first
        _write(cursor, text, family=family, size_pt=size, first=first,
               align=Qt.AlignmentFlag.AlignLeft,
               top_margin_pt=2.0, left_margin_pt=14.0 if indent else 0.0,
               bold=bold)
        first = False

    if want_scripture:
        heading("Scripture Index")
        for book in sorted(scripture, key=book_number):
            line(book, bold=True, size=10.5)
            for (chapter, v1, v2, display), pages in sorted(
                    scripture[book].items()):
                line(f"{display} — {_pages_text(pages)}", indent=True)
        if not scripture:
            line("(no Scripture references found)")

    if want_subject:
        heading("Subject Index")
        for headword in sorted(subjects, key=str.casefold):
            line(f"{headword} — {_pages_text(subjects[headword])}")
        if not subjects:
            line("(no vocabulary terms found)")

    return document
