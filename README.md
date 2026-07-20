# WordVault

A version-tracking plain-text writing environment backed by SQLite.
Every pause in typing becomes a timestamped revision; the author can walk
backward and forward through the life of a document, pull material from any
other document with provenance, and search the whole library.

See **DESIGN.md** for the full design. This repository currently implements
**Stages 1–9**: the storage layer, the PyQt6 editor, time travel, the
.docx library importer, the version-group review screen, library-wide
search / staged replace / mark-and-gather, the full writing environment
(age coloring, outline, focus mode, tags), encrypted backup / portable
document files, and SQLCipher encryption of the live database.

## Running the editor

```
pip install PyQt6
python -m wordvault                # opens/creates ~/.wordvault/library.db
python -m wordvault my_library.db  # or a specific library file
```

Create a document with **Ctrl+N** and just write — every ~3-second pause
in typing becomes a timestamped revision automatically (identical states
are skipped). The status bar shows the revision count, word count, and
last-save time. **Ctrl+S** forces a revision; switching documents and
closing the window also capture your latest words.

### Time travel

The **History bar** under the editor has one slider stop per revision.
Drag it — or press **Alt+Left** / **Alt+Right** — to walk backward and
forward through every state of the document; the timestamp of the viewed
state is shown beside the slider. History is read-only. To bring an old
state back, click **Restore this version** (or **Ctrl+R**): the old text
is appended as a *new* revision, so nothing is ever rewritten. **Alt+Home**
(or the **Newest** button) jumps back to the present. If you drag into
history with unsaved words on screen, they are saved first — time travel
can never lose your latest writing.

## Importing an existing .docx library

```
pip install python-docx
python tools/ingest_docx.py "C:\Users\Andrew Hopkins\Documents\DocxIndexSearch"
```

Every .docx becomes a document in the editor's library, timestamped with
the *file's* dates so the library is ordered by when the material was
written. Exact duplicates (same words under a different name) are
collapsed to a note. Then the version detector fingerprints everything
and proposes groups of files that look like drafts of the same material —
stored as *pending* proposals for the review screen (stage 5).

Tips: start with `--limit 50` for a trial run; the importer is safe to
re-run any time (already-ingested files are skipped, so an interrupted
run just continues). `--threshold 0.5` proposes looser matches, `0.8`
only near-identical ones.

### Reviewing version groups

In the editor, **Library ▸ Review Version Groups…** (Ctrl+G) opens the
review screen. Pick a group, compare any two drafts side-by-side as a
colored diff, then decide: **Confirm & Link** joins the checked documents
into a version chain (uncheck a document to leave it out), **Reject**
dismisses the group. Undecided groups simply stay in the queue for the
next sitting — nothing forces you to judge all groups at once, and your
decisions survive re-runs of the importer. Linked later versions show a
"↳" marker in the Library list.

### Searching the library

**Library ▸ Search Library…** (Ctrl+Shift+F) searches every document's
current text — word, phrase, or regular expression; scope it to the
current document, its version chain, or the whole library. Double-click
a match to open that document at that exact spot.

To replace, fill in the Replace field and click **Preview replace**:
every proposed change appears as a checklist. Uncheck what should stay,
then **Apply checked replacements** — one new revision per changed
document, so any replace (even across hundreds of documents) can be
inspected and undone through the History slider. A document edited
between preview and apply is skipped and reported, never corrupted.

### Mark and gather

Select a passage in any document and press **Ctrl+M** — it joins the
persistent gather tray. Keep reading, keep marking, across documents and
across days. **Library ▸ Gather Tray…** (Ctrl+Shift+G) shows everything
marked; **Gather into new document** builds a new essay from all the
passages in marking order, each with a provenance record pointing back
to exactly where it came from.

### The writing environment

**Color Text by Age** (View menu, Ctrl+Shift+A): older lines are tinted
a muted blue-gray shading toward the normal text color for the newest —
at a glance you see which parts of an essay are settled and which are
fresh. Computed from the revision history; purely visual.

**Outline** (dockable): Markdown-style headings (`# Chapter`,
`## Section`) become a clickable document map that tracks the cursor.
Structure is read from the plain text, never stored as markup.

**Focus mode** (Ctrl+Shift+H): the classic outliner "hoist" — the editor
shows only the section under the cursor, hiding everything else while
you work on it. Ctrl+Shift+U shows the whole document again. A view
only; the text is untouched.

**Document Info** (dockable): title, position in its version chain
("draft 3 of 5"), dates, revision and word counts, your place in the
text ("word 1,240 of 4,567 — 27% through"), and the document's tags.

**Tags**: Edit tags on any document from the Info panel (comma-
separated, e.g. `Genesis, atonement, book`). The dropdown above the
Library list filters by tag.

### Encrypted backup and portable documents

Requires `pip install cryptography`.

**File ▸ Back Up Library…** writes the whole library into one encrypted
`.wvbackup` file (AES-256-GCM, passphrase-protected, tamper-evident) —
easy to copy to a USB stick or cloud folder. **Restore** shows what a
backup contains (documents, revisions, date) before replacing anything,
and keeps the old library beside it as `.before-restore`. The same
operations exist for scripts and scheduled tasks:

```
python tools/backup_library.py backup "D:\Backups\wv-today.wvbackup"
```

**File ▸ Export Document as .wvdoc…** writes one document — with its
complete revision history — into an encrypted portable file.
**Import .wvdoc…** merges it back by the document's stable identity:
a new library receives the document whole with its original timestamps;
a library that already knows it receives only the newer revisions.
Nothing is ever overwritten.

Warning: there is no passphrase recovery. A forgotten passphrase means
an unreadable file — that is the point of the encryption.

### Encrypting the library itself

Backups protect copies; this protects the live database. Install
SQLCipher support (`pip install sqlcipher3-wheels` on Windows/macOS,
`pip install sqlcipher3-binary` on Linux), then **File ▸ Encrypt
Library…**. From then on WordVault asks for the passphrase at startup;
everything else works exactly as before. The old plaintext file is kept
as `.before-encrypt` until you delete it. **Change Library Passphrase…**
re-keys in place; **Remove Library Encryption…** goes back to plain.
Backups made from an encrypted library remain universal — they can be
restored into a plain or an encrypted library either way.

## Using the storage layer directly

The storage layer needs no GUI and no third-party packages:

```python
from wordvault import DocumentStore, RevisionWalker

with DocumentStore("my_library.db") as store:
    doc = store.create_document("First Essay")
    store.save_revision(doc.id, "In the beginning...")
    store.save_revision(doc.id, "In the beginning was the Word...")

    walker = RevisionWalker(store, doc.id)
    print(walker.text())     # newest text
    walker.back()
    print(walker.text())     # previous state
```

## Layout

```
wordvault/
├── wordvault/
│   ├── __main__.py          # `python -m wordvault` launcher
│   ├── models.py            # Document / Revision / SourceLink dataclasses
│   ├── storage/
│   │   ├── schema.py        # CREATE TABLE statements, schema versioning
│   │   ├── diffs.py         # snapshot/diff encoding (stdlib difflib)
│   │   ├── store.py         # DocumentStore — the only door to the database
│   │   └── walker.py        # RevisionWalker — time travel
│   ├── editor/
│   │   ├── editor_pane.py   # QPlainTextEdit + typing-pause detection
│   │   ├── timeline.py      # history slider (time travel control)
│   │   └── main_window.py   # library dock, auto-save + time-travel wiring
│   └── ingest/
│       ├── extract.py       # .docx → normalized plain text (python-docx)
│       ├── similar.py       # MinHash + LSH near-duplicate detection
│       └── pipeline.py      # Ingestor: Phase A (import) + Phase B (detect)
├── tools/
│   └── ingest_docx.py       # command-line importer
├── tests/                   # pytest suite (headless, no GUI needed)
├── DESIGN.md
└── pyproject.toml
```

## Running the tests

```
pip install -e ".[dev]"
pytest
```

Works identically on Ubuntu and Windows 11; Python 3.10+; no third-party
runtime dependencies in this stage.

## License

MIT
