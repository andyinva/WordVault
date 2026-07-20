# WordVault — Design Document

*A version-tracking plain-text writing environment backed by SQLite.*
*Python 3.11+ · PyQt6 · Open source (GitHub) · Runs on Ubuntu Linux and Windows 11*

---

## 1. Overview

WordVault is a distraction-free text editor that records the complete history of
everything the author writes. Every pause in typing produces a timestamped
revision in a SQLite database, so the author can move backward and forward
through the life of a document, see the age of any passage by color, pull
material from any other document with full provenance, and search or
search-and-replace across the entire library.

A companion ingest tool imports an existing library of `.docx` files
(6,000+ files, many of which are near-duplicate versions of the same material
under different names), detects which files are versions of one another, and
distills them into connected version chains inside the database.

Formatting is deliberately excluded from the writing stage. Documents are plain
UTF-8 text. A separate formatting application (future project) will consume the
finished text for output styling.

## 2. Goals and non-goals

**Goals**

- Never lose a word: append-only revision history with UTC timestamps.
- Fast, simple time travel: slider/keys to walk revisions forward and back.
- Distill a large legacy docx library into de-duplicated version chains.
- Powerful search and search-and-replace across every stored document.
- Visual cues: color text by age; always-visible document/position info panel.
- One-file encrypted backup and restore; encrypted single-document files that
  open directly in the editor and merge back into the database later.
- Formatting kept fully external: shareable Format Card QR codes (produced by
  the future WordVault Formatter) reconstruct formatted output from plain text.
- Clean OOP layering so the storage engine can later run as a server.
- Per-user database with a path to full encryption (SQLCipher).
- Cross-platform: identical behavior on Ubuntu and Windows 11.
- Heavily commented code throughout, suitable for other contributors.

**Non-goals (for now)**

- No rich-text formatting in the editor (separate future app).
- No shared multi-user database server on day one (the design allows it later).
- No word-per-row storage — history is captured as revisions, not word records.

## 3. Architecture

Three layers, one repository. The editor never touches SQL; everything goes
through the `DocumentStore` API. That single seam is what lets the storage
layer later become a local server (FastAPI over the same class) without any
change to the editor.

```
wordvault/
├── wordvault/
│   ├── models/          # Plain data classes: Document, Revision, SourceLink
│   ├── storage/         # DocumentStore, schema, migrations, FTS index
│   │   ├── store.py     #   public API — the ONLY entry point to the DB
│   │   ├── schema.py    #   CREATE TABLE statements + migrations
│   │   ├── diffs.py     #   snapshot/diff encode & decode (difflib)
│   │   └── search.py    #   FTS5 queries, regex search, replace engine
│   ├── ingest/          # docx import + version-detection ("distiller")
│   │   ├── extract.py   #   python-docx → plain text + file dates
│   │   ├── similar.py   #   fingerprinting & clustering of near-duplicates
│   │   └── review.py    #   data model for accept/reject grouping decisions
│   ├── editor/          # PyQt6 GUI
│   │   ├── main_window.py
│   │   ├── editor_pane.py    # QPlainTextEdit subclass
│   │   ├── timeline.py       # revision slider / history navigation
│   │   ├── age_colors.py     # text-age highlighting
│   │   ├── info_panel.py     # QDockWidget with document stats
│   │   └── search_dialog.py  # library-wide search & replace UI
│   └── __main__.py      # `python -m wordvault`
├── tools/
│   └── ingest_docx.py   # command-line one-shot importer
├── tests/               # pytest; storage layer is fully testable headless
├── README.md
├── DESIGN.md            # this file
└── pyproject.toml
```

**Key classes**

| Class | Responsibility |
|---|---|
| `DocumentStore` | Open/create DB; save & fetch revisions; list documents; search; replace. |
| `Document` | Identity, title, creation time, parent link (version chains). |
| `Revision` | One captured state: timestamp, kind (`snapshot`/`diff`), payload. |
| `RevisionWalker` | Rebuilds text at any point in history; steps forward/back. |
| `Distiller` | Groups ingested files into version chains via similarity scores. |
| `SearchEngine` | FTS5 + regex search; staged, previewable replace. |
| `EditorWindow` | PyQt6 shell wiring the pieces together. |

## 4. Data model (SQLite)

```sql
-- One row per logical document. Version chains are linked lists via parent_doc_id.
documents (
    id            INTEGER PRIMARY KEY,
    uuid          TEXT NOT NULL UNIQUE,   -- stable identity across export/import/merge
    title         TEXT NOT NULL,
    created_utc   TEXT NOT NULL,          -- ISO 8601, always UTC
    parent_doc_id INTEGER REFERENCES documents(id),  -- earlier version of same material
    original_path TEXT,                   -- source .docx path, if ingested
    original_mtime TEXT                   -- file date used for chronological ordering
);

-- Append-only history. Never updated, never deleted.
revisions (
    id            INTEGER PRIMARY KEY,
    doc_id        INTEGER NOT NULL REFERENCES documents(id),
    created_utc   TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('snapshot','diff')),
    payload       TEXT NOT NULL,          -- full text, or unified diff vs parent
    parent_rev_id INTEGER REFERENCES revisions(id),
    origin        TEXT NOT NULL DEFAULT 'typing'
                  -- 'typing' | 'ingest' | 'replace' | 'pull'
);

-- Provenance for material pulled from other documents.
sources (
    id             INTEGER PRIMARY KEY,
    target_rev_id  INTEGER NOT NULL REFERENCES revisions(id),
    source_doc_id  INTEGER NOT NULL REFERENCES documents(id),
    source_rev_id  INTEGER NOT NULL REFERENCES revisions(id),
    excerpt_start  INTEGER,               -- character offsets in the source revision
    excerpt_end    INTEGER
);

-- Latest full text of every document, kept current for instant search.
-- FTS5 gives fast library-wide full-text search with ranking and snippets.
CREATE VIRTUAL TABLE doc_text USING fts5(
    title, body, content=''
);

-- Distiller working tables: candidate version groups awaiting user review.
similarity_groups (
    id          INTEGER PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'pending'   -- 'pending' | 'confirmed' | 'rejected'
);
similarity_members (
    group_id    INTEGER NOT NULL REFERENCES similarity_groups(id),
    doc_id      INTEGER NOT NULL REFERENCES documents(id),
    score       REAL NOT NULL              -- similarity to group centroid, 0–1
);

-- Lightweight organization for the library view (GrandView-style categories).
tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);
document_tags (
    doc_id  INTEGER NOT NULL REFERENCES documents(id),
    tag_id  INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (doc_id, tag_id)
);
```

Notes:

- **Snapshots vs diffs.** Most revisions store a unified diff against their
  parent (small). Every Nth revision (default N=50) stores a full snapshot so
  rebuilding any historical state never replays more than 50 diffs. `difflib`
  from the standard library produces and applies the diffs — no dependency.
- **`doc_text` is derived data.** It is rebuilt from the newest revision
  whenever a document changes, so search always reflects current text. History
  search (searching *old* revisions) walks revisions on demand — slower but rare.
- **Document format.** Plain UTF-8 text, LF line endings internally
  (normalized on ingest and on paste). Optionally Markdown by convention —
  the editor treats it as plain text; the future formatting app can interpret it.

## 5. Revision capture and time travel

**Capture policy** — practical, not per-keystroke:

- A revision is committed when the author pauses typing for ~3 seconds
  (configurable), on manual save, on focus loss, and on document close.
- Identical consecutive states are skipped (hash comparison).
- Result: fine-grained history (typically one revision per sentence or two)
  with tiny storage cost, and no perceptible editor lag.

**Time travel**

- `RevisionWalker` exposes `at(revision_id)`, `back()`, `forward()`.
- UI: a timeline slider beneath the editor plus `Alt+Left` / `Alt+Right`.
  The title bar shows the timestamp of the state being viewed.
- Viewing history is read-only. To resurrect an old state, the author clicks
  **Restore**, which appends the old text as a *new* revision (`origin='typing'`)
  — history is never rewritten, so redo/undo across time always works.
- Version chains extend time travel across documents: stepping back past the
  first revision of a document offers to continue into its `parent_doc_id`.

## 6. Ingesting and distilling the docx library

Source: `C:\Users\Andrew Hopkins\Documents\DocxIndexSearch` — 6,000+ `.docx`
files, many being versions of the same material under different names.

**Phase A — Extract (automatic)**

1. Walk the folder tree; for each `.docx`, extract plain text with
   `python-docx` (paragraph text only; formatting discarded by design).
2. Record file created/modified times; normalize whitespace and line endings.
3. Create one `documents` row + one `snapshot` revision per file
   (`origin='ingest'`), timestamped with the file's own dates so the library
   is ordered by when the material was actually written.
4. Exact duplicates (identical text hash) are collapsed immediately: one
   document, with the duplicate paths noted.

**Phase B — Detect versions (automatic)**

Goal: find files that are near-duplicates or successive drafts, even under
different filenames.

- Compute a **MinHash fingerprint** over word 5-gram shingles for every
  document (the `datasketch` library, or a small hand-rolled implementation —
  ~60 lines). Fingerprints make all-pairs comparison of 6,000 documents
  feasible in seconds via locality-sensitive hashing, instead of ~18 million
  full text comparisons.
- Candidate pairs above a similarity threshold (default Jaccard ≥ 0.6) are
  clustered into `similarity_groups`. Borderline pairs (0.4–0.6) are kept in a
  low-confidence list rather than discarded.
- Within each group, members are ordered by file date to propose a draft
  sequence: oldest = original, each later file's `parent_doc_id` pointing to
  the previous one.

**Phase C — Review and distill (human-in-the-loop)**

Automation proposes; the author decides. A review screen in the editor lists
each pending group with titles, dates, similarity scores, and a side-by-side
diff of any two members. The author can:

- **Confirm** — the chain is linked via `parent_doc_id`; the newest member
  becomes the "live" document, the older ones become its history (their
  snapshots are appended as early revisions of the chain).
- **Split / re-order** — drag members out of a group or change the sequence.
- **Reject** — members remain independent documents.

Nothing is deleted during distillation: every ingested text remains reachable
as a revision. "Distilling" means connecting and ordering, not discarding.

**Practicality note.** Phase A and B are one-time batch scripts
(`tools/ingest_docx.py`) that run unattended. Phase C is spread over time —
the review queue is persistent, so the author can confirm a few groups per
sitting. Expect the 6,000 files to distill to a much smaller set of chains.

## 7. Search and replace (library-wide)

Opened from the editor with `Ctrl+Shift+F`, scoped to: current document,
current version chain, or entire library.

**Search**

- Backed by the FTS5 `doc_text` index: word and phrase queries with ranking
  and highlighted snippets, effectively instant across the whole library.
- A regex mode runs Python `re` over candidate documents (FTS pre-filters the
  candidates when the pattern contains literal words, keeping regex fast).
- Results panel lists document title, date, snippet; Enter opens the document
  at the match. An option includes historical revisions in the search.

**Replace — staged and safe**

1. Author enters find/replace terms and scope, then hits **Preview**.
2. The engine produces a checklist of every proposed change, grouped by
   document, each shown in context. Individual changes can be unchecked.
3. **Apply** writes one new revision per affected document
   (`origin='replace'`), all sharing a batch id.
4. Because replaces are ordinary revisions, any replace — across hundreds of
   documents — is fully inspectable and reversible through normal time travel.

## 8. Editor UI (PyQt6)

Several features below are modernized from the 1980s DOS "thought processors"
(ThinkTank, MaxThink, GrandView): the outline pane, focus mode, mark-and-gather,
and tags.

- **Editor pane** — `QPlainTextEdit` subclass. Handles plain text only;
  built-in undo/redo covers the current session, the revision system covers
  everything beyond it.
- **Age coloring** — toggleable. Each character's "birth revision" is derived
  from the diff history; text is tinted on a gradient (oldest: muted blue-gray
  → newest: full-strength foreground) using extra selections. Implementation:
  computed lazily for the visible viewport only, so large documents stay fast.
- **Timeline** — slider + timestamp label; keyboard stepping; markers for
  snapshots and for revisions that pulled in outside material.
- **Info panel** — dockable, showing: title, version-chain position
  (e.g., "draft 3 of 5"), created/last-edited timestamps, word count,
  cursor position as *word X of Y* and percentage through the document,
  revision count, and provenance of the passage under the cursor.
- **Outline pane** — a dockable document map built from Markdown-style
  headings in the plain text. Shows the document's structure as a tree,
  marks the cursor's position in it, and jumps on click. This is the classic
  outliner tree, derived from the text rather than stored as structure.
- **Focus (hoist) mode** — MaxThink-style hoisting: pick a heading (or any
  selection) and the editor shows only that section, hiding the rest until
  un-focused. Ideal for working on one part of a long essay. Purely a view —
  the stored text is untouched.
- **Mark and gather** — mark passages in any number of documents (they queue
  up in a persistent "gather tray"), then **Gather** creates a new document
  from all marked passages in one step, writing a `sources` provenance row
  for each. The primary tool for distilling material out of the legacy
  library into new work.
- **Library view** — searchable document list, grouped by version chain,
  ordered chronologically, filterable by tag (topic, series, status, …).
- **Pull from another document** — split view: open any other document
  read-only beside the current one, select text, **Pull** inserts it and
  records a `sources` row. Pulled text briefly shows in a distinct color.
  Deliberately a *copy*, not a live link (clones would tangle the append-only
  history) — but an **Update from source** command diffs a pulled passage
  against its origin and offers to bring in later changes.

## 9. Security and multi-user

- **Now:** one SQLite file per user (e.g., `~/.wordvault/andrew.db`),
  protected by OS file permissions. Separation between users is physical —
  separate files — which is simpler and stronger than row-level access control
  in a shared database.
- **Later:** SQLCipher (via `sqlcipher3` bindings) encrypts the entire
  database file with a passphrase-derived key. `DocumentStore` gains a
  `passphrase` parameter; nothing else changes.
- **Later still:** a small FastAPI server wrapping `DocumentStore` with token
  authentication, one encrypted database per account. Runs on the same PC for
  speed (localhost), or remotely. The editor talks to a `RemoteDocumentStore`
  with the same method signatures — the seam designed in Section 3.

## 10. Backup, restore, and portable document files

Both file types below share one **encrypted envelope**: payload → zlib
compression → AES-256-GCM encryption (key derived from a passphrase with
scrypt), using the `cryptography` library. GCM gives tamper detection for
free — a corrupted or altered backup fails loudly at restore time, never
silently.

**Whole-library backup — `.wvbackup`**

- **Backup** (menu item or `python -m wordvault backup`): the store runs
  SQLite's `VACUUM INTO` to produce a clean, compacted copy of the database,
  then wraps it in the encrypted envelope with a header recording schema
  version, document/revision counts, and creation time. One passphrase, one
  portable file — easy to copy to a USB stick or cloud folder.
- **Restore**: decrypt, verify integrity, then either replace the current
  database (with confirmation) or restore alongside it for inspection.
  The header lets the restore screen show what's inside before committing.
- The editor can prompt for a periodic backup (e.g., weekly) — cheap insurance.

**Single-document file — `.wvdoc`**

A portable, encrypted container for one document: a JSON payload holding the
document's metadata (including its `uuid`), its revision history (or, at the
author's option, just the latest snapshot), and any `sources` provenance.
Uses the same encrypted envelope.

- **Export**: save the current document to a `.wvdoc` for safekeeping,
  transport, or sharing.
- **Open directly**: the editor can open a `.wvdoc` in *detached mode* —
  full editing and time travel, with new revisions accumulating inside the
  file itself. No database required, useful on a machine that isn't yours.
- **Import / merge**: loading a `.wvdoc` into a database matches on `uuid`.
  Unknown document → created whole, original timestamps preserved. Known
  document → new revisions are appended in timestamp order; nothing is
  overwritten, consistent with the append-only rule.

## 11. Format QR codes (WordVault Formatter interop)

Formatting never enters the editor's text. Instead, the future **WordVault
Formatter** produces a **Format Card**: a QR code containing everything needed
to turn a given plain text into its formatted output. Cards are reusable
across documents, shareable with other people, and printable on books and
essays so a viewer tool can scan the code and reconstruct the formatted
document from the plain text.

**The capacity constraint shapes the design.** A QR code tops out at ~3 KB of
binary data, so the card cannot embed per-word formatting. It holds a compact
**stylesheet keyed to document structure**, which compresses very well:

```
FormatCard (CBOR, zlib-compressed, then QR-encoded)
├── card_id, card_version, name          -- e.g., "Essay – Book Layout v2"
├── page:    size, margins, columns
├── styles:  named style definitions
│            (font family/size/weight, spacing, alignment, indents)
├── rules:   structure → style mappings
│            e.g., "heading level 1 → Style:Title",
│                  "paragraph → Style:Body", "blockquote → Style:Quote"
├── overrides (optional): character-offset ranges → style,
│            for spot formatting a rule can't express
└── binding (optional): document uuid + content hash (SHA-256)
             -- pins the card to one exact revision for faithful reconstruction
```

- **Generic cards** omit the binding: they are pure stylesheets, applicable to
  any document — this is what makes cards shareable and reusable.
- **Bound cards** include the uuid + content hash of a specific revision:
  scan the code on a printed book, obtain the matching plain text (from a
  database, a `.wvdoc`, or a published file), verify the hash, and the viewer
  reassembles the formatted document exactly as it was printed.
- Structure detection (headings, paragraphs, quotes) works from the plain
  text itself — another reason the Markdown-by-convention option in Section 4
  is attractive: it makes structure explicit without being "formatting codes."
- If a card with many overrides exceeds QR capacity, the Formatter splits it
  across a numbered multi-QR sequence, or falls back to printing a short URL/
  fingerprint that identifies a card file. Expected case: a compressed
  stylesheet is a few hundred bytes — one code.
- Implementation: `qrcode` library to generate, `pyzbar` or `opencv` to scan.
  The card format gets its own small spec file in the repo
  (`docs/format-card.md`) so other tools can implement it independently —
  the viewer tool need not be written by us.

**Division of labor**: the editor stores text and can *display* a document's
associated cards; only the Formatter creates or edits cards. The editor's
database gains one small table:

```sql
format_cards (
    id          INTEGER PRIMARY KEY,
    card_id     TEXT NOT NULL UNIQUE,    -- matches card_id inside the QR payload
    name        TEXT NOT NULL,
    payload     BLOB NOT NULL,           -- the card itself (canonical copy)
    doc_uuid    TEXT                     -- NULL for generic cards
);
```

## 12. Cross-platform notes

- Pure-Python dependencies only (`PyQt6`, `python-docx`, optionally
  `datasketch`); everything installs with `pip` on Ubuntu and Windows 11.
- All paths through `pathlib`; all timestamps stored UTC, displayed local.
- Line endings normalized to LF in storage regardless of platform.
- The database file is portable between operating systems as-is.

## 13. Roadmap

| Stage | Deliverable | Usable result |
|---|---|---|
| 1 | `storage` package + full pytest suite (no GUI) | Library others can build on |
| 2 | Minimal editor: open, type, auto-revision, reopen | Daily-usable safe editor |
| 3 | Timeline slider + restore | Time travel |
| 4 | `tools/ingest_docx.py` Phases A & B | Legacy library imported |
| 5 | Review screen (Phase C) + library view | Distillation begins |
| 6 | Library-wide search, staged replace, mark-and-gather | Research power tool |
| 7 | Age coloring, info panel, outline pane, focus mode, tags | Full writing environment |
| 8 | Encrypted backup/restore (`.wvbackup`) + `.wvdoc` export/import | Data safety & portability |
| 9 | SQLCipher encryption of the live database | Secure single-user |
| 10 | Format Card spec (`docs/format-card.md`) + card storage table | Formatter interop ready |
| 11 | FastAPI server + remote store | Optional client/server |

Each stage is independently useful and shippable — good for GitHub
contributors and for keeping the project practical.

## 14. Coding standards

- Object-oriented throughout; one class per responsibility (Section 3 table).
- Generous comments: every module has a header comment explaining its role;
  every non-obvious block is commented, in plain language.
- Type hints on all public methods; `pytest` tests required for the storage
  and ingest layers (they run headless, no GUI needed).
- GitHub: MIT license, issues for each roadmap stage, CI running the test
  suite on both Ubuntu and Windows.
