"""
search.py — SearchEngine: library-wide find and staged replace (stage 6).

Implements DESIGN.md section 7.  Two halves:

  find()             locate every occurrence of a query across a set of
                     documents (plain text, case-insensitive by default,
                     or full regular expressions).  When searching the
                     whole library with plain text, the FTS5 index
                     pre-filters candidate documents so only documents
                     that actually contain the words are scanned.

  plan_replace() +   replace is STAGED, never immediate: plan_replace()
  apply_replace()    returns every proposed change for the author to
                     review (the dialog shows them as a checklist); then
                     apply_replace() writes ONE new revision per affected
                     document (origin='replace').  Because replaces are
                     ordinary revisions, any replace — across hundreds of
                     documents — is inspectable and reversible through
                     normal time travel.

Safety: each plan records a hash of the text it was computed against.
If a document changes between preview and apply (e.g. the author kept
typing), apply_replace() skips it and reports it rather than corrupting
the text with stale offsets.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

from wordvault.storage.store import DocumentStore


@dataclass(frozen=True)
class Match:
    """One occurrence of the query inside one document's current text."""

    doc_id: int
    start: int        # character offsets into the document's current text
    end: int
    line: str         # the (trimmed) line containing the match, for display
    replacement: str  # what this span would become (used by replace preview)


@dataclass
class DocPlan:
    """All proposed changes for one document, from one plan_replace() call."""

    doc_id: int
    title: str
    text_hash: str               # hash of the text the offsets refer to
    matches: list[Match] = field(default_factory=list)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _display_line(text: str, start: int, width: int = 90) -> str:
    """The line containing offset `start`, trimmed for a results list."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end].strip()
    return line[:width] + ("…" if len(line) > width else "")


class SearchEngine:
    """Find and staged-replace over documents' CURRENT text."""

    def __init__(self, store: DocumentStore):
        self._store = store

    # ---------------------------------------------------------------- find --

    def find(
        self,
        query: str,
        doc_ids: Optional[list[int]] = None,
        regex: bool = False,
        case_sensitive: bool = False,
        max_per_doc: int = 500,
    ) -> list[Match]:
        """
        Every occurrence of `query` in the given documents (None = whole
        library).  Returns matches grouped by document in library order.
        """
        if not query:
            return []
        pattern = self._compile(query, regex, case_sensitive)

        matches: list[Match] = []
        for doc in self._scope_documents(query, doc_ids, regex):
            text = self._store.current_text(doc.id)
            count = 0
            for m in pattern.finditer(text):
                if m.start() == m.end():
                    continue  # zero-width regex match: skip, avoid loops
                matches.append(Match(
                    doc_id=doc.id,
                    start=m.start(),
                    end=m.end(),
                    line=_display_line(text, m.start()),
                    replacement="",
                ))
                count += 1
                if count >= max_per_doc:
                    break
        return matches

    # ------------------------------------------------------------- replace --

    def plan_replace(
        self,
        query: str,
        replacement: str,
        doc_ids: Optional[list[int]] = None,
        regex: bool = False,
        case_sensitive: bool = False,
    ) -> list[DocPlan]:
        """
        Stage a replace: compute every proposed change WITHOUT touching
        anything.  Each Match carries its exact replacement text (regex
        group references like \\1 are expanded per match).
        """
        if not query:
            return []
        pattern = self._compile(query, regex, case_sensitive)

        plans: list[DocPlan] = []
        for doc in self._scope_documents(query, doc_ids, regex):
            text = self._store.current_text(doc.id)
            plan = DocPlan(doc_id=doc.id, title=doc.title, text_hash=_hash(text))
            for m in pattern.finditer(text):
                if m.start() == m.end():
                    continue
                new = m.expand(replacement) if regex else replacement
                plan.matches.append(Match(
                    doc_id=doc.id,
                    start=m.start(),
                    end=m.end(),
                    line=_display_line(text, m.start()),
                    replacement=new,
                ))
            if plan.matches:
                plans.append(plan)
        return plans

    def apply_replace(
        self, plans: list[DocPlan], selected: Optional[set[tuple[int, int]]] = None
    ) -> tuple[int, list[str]]:
        """
        Execute a staged replace.

        selected — the (doc_id, start) pairs the author left CHECKED in the
                   preview; None means apply everything in the plans.

        Returns (documents_changed, skipped_titles).  A document whose text
        changed since the preview is skipped (stale offsets), reported by
        title, and can simply be re-previewed.
        """
        changed = 0
        skipped: list[str] = []
        for plan in plans:
            todo = [
                m for m in plan.matches
                if selected is None or (m.doc_id, m.start) in selected
            ]
            if not todo:
                continue

            text = self._store.current_text(plan.doc_id)
            if _hash(text) != plan.text_hash:
                skipped.append(plan.title)   # edited since preview
                continue

            # Splice from the END so earlier offsets stay valid.
            for m in sorted(todo, key=lambda m: m.start, reverse=True):
                text = text[: m.start] + m.replacement + text[m.end :]

            self._store.save_revision(plan.doc_id, text, origin="replace")
            changed += 1
        return changed, skipped

    # ------------------------------------------------------------ internals --

    @staticmethod
    def _compile(query: str, regex: bool, case_sensitive: bool) -> re.Pattern:
        """One code path for both modes: plain text is just an escaped regex."""
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.compile(query if regex else re.escape(query), flags)

    def _scope_documents(
        self, query: str, doc_ids: Optional[list[int]], regex: bool
    ):
        """The documents to scan, in library order.  Whole-library plain-text
        searches are pre-filtered through the FTS index when available —
        only documents containing the words get scanned character by
        character."""
        if doc_ids is not None:
            return [self._store.get_document(d) for d in doc_ids]

        docs = self._store.list_documents()
        if regex or not self._store.fts_available:
            return docs

        # FTS pre-filter: quote the query so FTS operators in the text
        # (AND, OR, *) are treated as literal words, not syntax.
        words = query.split()
        if not words:
            return docs
        fts_query = " ".join('"' + w.replace('"', '""') + '"' for w in words)
        try:
            hits = {d.id for d, _ in self._store.search_current(fts_query)}
        except Exception:
            return docs   # odd query for FTS: fall back to scanning all
        return [d for d in docs if d.id in hits]
