"""
book.py — the BookProject: everything the Formatter needs to rebuild a
book, saved as a .wvbook file.

A book is an ASSEMBLY, not a document.  The chapters live in the
WordVault library (referenced here by their stable uuids, never by
copying text — the library remains the single source of truth, so a
chapter edited in WordVault is automatically current at the next
build).  The project file records only the recipe: which chapters, in
what order, under which print format, with which sections switched on,
and the copyright-page details.

The file format is plain JSON — human-readable, diff-friendly, and
stdlib-only, in the same spirit as the TOML .wvfmt files.  No Qt is
imported here so the model is testable on any machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Bumped only when an older Formatter could MISREAD a newer file.
FILE_VERSION = 1

#: The sections a book may include, in the order they appear in the
#: finished PDF.  Each is a checkbox in the Formatter window.
SECTION_KEYS = (
    "title_page",
    "copyright",        # copyright page (ISBN, year, rights)
    "toc",              # table of contents
    "subject_index",    # back matter
    "scripture_index",  # back matter
)


class BookProjectError(Exception):
    """A .wvbook file could not be read — always says why."""


@dataclass
class ChapterRef:
    """One chapter: a pointer into the library plus the title to show.

    The uuid is the durable link (doc ids can change across restores;
    uuids never do).  The title is stored too so a project file remains
    readable as text even away from its library."""

    uuid: str
    title: str


@dataclass
class CopyrightInfo:
    """The fields printed on the copyright page (stage F2 renders it)."""

    isbn: str = ""
    year: str = ""
    edition: str = ""
    rights: str = "All rights reserved."
    #: Bible-translation credit line, e.g. the NKJV notice.  KJV needs
    #: none (public domain); most modern translations require one.
    scripture_notice: str = ""


@dataclass
class BookProject:
    """The whole recipe for one book."""

    title: str = ""
    author: str = ""
    format_name: str = "Book Chapter"        # a .wvfmt, chosen by name
    chapters: list[ChapterRef] = field(default_factory=list)
    #: Which optional sections to include (see SECTION_KEYS).
    sections: dict[str, bool] = field(
        default_factory=lambda: {key: False for key in SECTION_KEYS}
    )
    copyright: CopyrightInfo = field(default_factory=CopyrightInfo)
    #: Controlled-vocabulary file for the subject index (stage F4).
    vocabulary_path: str = ""

    # -- persistence ----------------------------------------------------

    def to_json(self) -> str:
        """Serialize; stable key order so saved files diff cleanly."""
        payload = {
            "wordvault_book": FILE_VERSION,
            "title": self.title,
            "author": self.author,
            "format": self.format_name,
            "chapters": [
                {"uuid": c.uuid, "title": c.title} for c in self.chapters
            ],
            "sections": {k: bool(self.sections.get(k)) for k in SECTION_KEYS},
            "copyright": {
                "isbn": self.copyright.isbn,
                "year": self.copyright.year,
                "edition": self.copyright.edition,
                "rights": self.copyright.rights,
                "scripture_notice": self.copyright.scripture_notice,
            },
            "vocabulary_path": self.vocabulary_path,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BookProject":
        """Read a .wvbook file; every failure names the problem (the
        same courtesy the .wvfmt loader extends)."""
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise BookProjectError(f"Cannot read {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BookProjectError(
                f"{path.name} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(raw, dict) or "wordvault_book" not in raw:
            raise BookProjectError(
                f"{path.name} is not a WordVault book project "
                "(missing the 'wordvault_book' marker)"
            )
        if raw["wordvault_book"] > FILE_VERSION:
            raise BookProjectError(
                f"{path.name} was written by a newer WordVault "
                f"(file version {raw['wordvault_book']}, "
                f"this program reads up to {FILE_VERSION})"
            )

        project = cls(
            title=str(raw.get("title", "")),
            author=str(raw.get("author", "")),
            format_name=str(raw.get("format", "Book Chapter")),
            vocabulary_path=str(raw.get("vocabulary_path", "")),
        )
        for entry in raw.get("chapters", []):
            if not isinstance(entry, dict) or "uuid" not in entry:
                raise BookProjectError(
                    f"{path.name}: each chapter needs a 'uuid'"
                )
            project.chapters.append(
                ChapterRef(uuid=str(entry["uuid"]),
                           title=str(entry.get("title", "")))
            )
        # Unknown section keys are ignored (an older file in a newer
        # program); missing ones default to off.
        stored = raw.get("sections", {})
        project.sections = {
            key: bool(stored.get(key, False)) for key in SECTION_KEYS
        }
        cp = raw.get("copyright", {})
        project.copyright = CopyrightInfo(
            isbn=str(cp.get("isbn", "")),
            year=str(cp.get("year", "")),
            edition=str(cp.get("edition", "")),
            rights=str(cp.get("rights", "All rights reserved.")),
            scripture_notice=str(cp.get("scripture_notice", "")),
        )
        return project
