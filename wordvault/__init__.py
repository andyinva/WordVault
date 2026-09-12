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

#: The program's version, shown in the window title.  Bump the number
#: and refresh the date together when cutting a release.
#:
#: This line is also how every installed copy learns that a new version
#: exists: Help > Check for Updates downloads this file from GitHub's
#: main branch and compares the number.  So bumping it and pushing IS
#: publishing a release (pyproject.toml reads the number from here too).
__version__ = "1.2"
RELEASE_DATE = "September 12, 2026"

#: The motto that follows the version everywhere it appears.
TAGLINE = "A professional writer's open-source friend"

#: Where friends download WordVault (used by Help > Share WordVault).
REPO_URL = "https://github.com/andyinva/WordVault"

__all__ = [
    "DocumentStore",
    "RevisionWalker",
    "Document",
    "Revision",
    "SourceLink",
    "Tag",
    "__version__",
    "RELEASE_DATE",
    "TAGLINE",
]
