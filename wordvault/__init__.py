"""
WordVault — a version-tracking plain-text writing environment backed by SQLite.

This package currently contains Stage 1 of the roadmap in DESIGN.md:
the storage layer.  Everything here is standard-library only and runs
headless (no GUI), so it can be tested and reused by other tools.

Public API
----------
DocumentStore   open/create a library database; save and fetch revisions
RevisionWalker  step forward and backward through a document's history
Document, Revision, SourceLink, Tag   plain data classes (models)
"""

from wordvault.models import Document, Revision, SourceLink, Tag
from wordvault.storage.store import DocumentStore
from wordvault.storage.walker import RevisionWalker

__version__ = "0.1.0"

__all__ = [
    "DocumentStore",
    "RevisionWalker",
    "Document",
    "Revision",
    "SourceLink",
    "Tag",
    "__version__",
]
