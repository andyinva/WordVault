"""
wordvault.storage — the persistence layer.

The single entry point is DocumentStore (store.py).  Nothing outside this
package should ever execute SQL against a WordVault database; that rule is
what will later let the store run behind a small server without touching
the editor (DESIGN.md section 3).
"""

from wordvault.storage.store import DocumentStore
from wordvault.storage.walker import RevisionWalker

__all__ = ["DocumentStore", "RevisionWalker"]
