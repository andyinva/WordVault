"""
walker.py — RevisionWalker: time travel through one document's history.

The walker is the model behind the editor's timeline slider and the
Alt+Left / Alt+Right keys (DESIGN.md section 5).  It holds a position in
the document's chronological revision list and rebuilds text on demand
through the store.  It never mutates anything — viewing history is
read-only; resurrecting an old state is done by the editor appending a
NEW revision (origin='restore') with the old text.

The revision list is captured when the walker is created.  If new
revisions are saved afterwards, call refresh() to see them (the editor
does this whenever an auto-save fires while the timeline is open).
"""

from __future__ import annotations

from typing import Optional

from wordvault.models import Revision
from wordvault.storage.store import DocumentStore


class RevisionWalker:
    """Step backward and forward through a document's revisions."""

    def __init__(self, store: DocumentStore, doc_id: int):
        self._store = store
        self._doc_id = doc_id
        self._revisions: list[Revision] = store.list_revisions(doc_id)
        # Start at the newest revision (index len-1); -1 means "no revisions".
        self._index = len(self._revisions) - 1

    # -- position -----------------------------------------------------------

    @property
    def position(self) -> int:
        """Zero-based index of the current revision (-1 = empty document)."""
        return self._index

    def __len__(self) -> int:
        """Total number of revisions (for the timeline slider's range)."""
        return len(self._revisions)

    def current(self) -> Optional[Revision]:
        """The revision the walker is standing on (None if none exist)."""
        if self._index < 0:
            return None
        return self._revisions[self._index]

    def text(self) -> str:
        """The document's full text at the current position."""
        rev = self.current()
        return self._store.get_text(rev.id) if rev else ""

    # -- movement -----------------------------------------------------------

    def back(self) -> Optional[Revision]:
        """Step one revision older.  Returns the new current revision,
        or None if already at the oldest (position is unchanged then)."""
        if self._index > 0:
            self._index -= 1
            return self.current()
        return None

    def forward(self) -> Optional[Revision]:
        """Step one revision newer.  Returns the new current revision,
        or None if already at the newest (position is unchanged then)."""
        if self._index < len(self._revisions) - 1:
            self._index += 1
            return self.current()
        return None

    def at(self, rev_id: int) -> Revision:
        """Jump directly to a revision by id (timeline click).
        Raises KeyError if the id is not in this document's history."""
        for i, rev in enumerate(self._revisions):
            if rev.id == rev_id:
                self._index = i
                return rev
        raise KeyError(f"Revision {rev_id} is not in document {self._doc_id}")

    def refresh(self) -> None:
        """Re-read the revision list (new revisions may have been saved).
        Keeps the walker on the same revision when it still exists;
        otherwise moves to the newest."""
        current = self.current()
        self._revisions = self._store.list_revisions(self._doc_id)
        self._index = len(self._revisions) - 1
        if current is not None:
            for i, rev in enumerate(self._revisions):
                if rev.id == current.id:
                    self._index = i
                    break
