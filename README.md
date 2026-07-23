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

Right in the editor: **Library ▸ Import .docx Folder…** (Ctrl+Shift+I)
— pick a folder, watch the progress, read the report. The import is
incremental (already-imported files are skipped), so after adding a new
subdirectory just run it again on the same folder and only the new files
come in. You can also choose to keep a copy of every imported file in an
**archive folder** (`~/.wordvault/ingested_originals`), each named
`<document id> - <filename>` so the source of any document is easy to
find.

The same importer as a command line, for scripting:

```
pip install python-docx
python tools/ingest_docx.py "C:\path\to\essays" --archive "D:\IngestedOriginals"
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

### The scripture index

Every document's text is scanned for Bible references — "John 3:16",
"1 Cor. 15:22", "Gen 1:1-5", "II Timothy 2:15" all count — and the cited
verses are indexed automatically on every save. This gives the library a
second identification signal beside text similarity: essays citing the
same verses are about the same material even when the prose differs.

**Library ▸ Documents Sharing Verses…** (Ctrl+Shift+V) ranks the other
documents by how many citations they share with the open one, showing a
sample of the shared verses; double-click to open. The Document Info
panel shows how many verses the open document cites.

Documents imported before this feature need one backfill pass:

```
python tools/reindex_library.py
```

### Markdown formatting from Word

Documents remain plain text, but plain text can carry structure by
convention — Markdown. The importer now translates the structural part
of Word formatting as it extracts:

| Word | Markdown |
|---|---|
| Heading 1–6, Title/Subtitle | `#` … `######` |
| **bold**, *italic* runs | `**bold**`, `*italic*` |
| List Bullet / List Number styles | `- item` / `1. item` |
| Quote styles | `> quoted text` |

Fonts, sizes, colors and margins are aesthetics, not structure, and are
deliberately dropped — the future WordVault Formatter will map the
Markdown back to Word styles for output. The outline pane already reads
the `#` headings. To recover formatting for documents ingested earlier
(their originals must still exist):

```
python tools/reindex_library.py --formatting
```

Each changed document gains one new revision; the plain version stays
one step back in its history. (`--plain` on the ingest tool disables
Markdown extraction if ever wanted.)

### Reviewing version groups

In the editor, **Library ▸ Review Version Groups…** (Ctrl+G) opens the
review screen. Pick a group, compare any two drafts side-by-side as a
colored diff, then decide: **Confirm & Link** joins the checked documents
into a version chain (uncheck a document to leave it out), **Reject**
dismisses the group. Undecided groups simply stay in the queue for the
next sitting — nothing forces you to judge all groups at once, and your
decisions survive re-runs of the importer. Linked later versions show a
"↳" marker in the Library list.

### Everyday conveniences

**File**: Close Document (Ctrl+W), a **Recent** submenu of the last ten
documents, and **Print Document…** (Ctrl+Shift+P) with Page Setup for
sending the open document to a local printer (or PDF). Library-level
operations — backup, restore, encryption — live under **Library** where
they belong. **View**: toggles for **Line Numbers** and **Check
Spelling** (needs `pip install pyspellchecker`) — misspelled words get
red squiggles, right-click offers corrections and "Add to dictionary";
the dictionary is pre-seeded with Bible book names and your additions
persist in `~/.wordvault/user_dictionary.txt`. A **Library Info** panel
below Document Info shows counts, file size, and the library's location.
Search result snippets center on the matched word, so the word you
searched for is always visible in its snippet.

### The Document menu

Everything about the *open* document in one place: **Go to Document…**
(Ctrl+P, type-ahead over all titles), **Find in Document** (Ctrl+F,
incremental find bar with wrap-around), **Rename**, **Edit Tags…**,
**Previous/Next Version** (Ctrl+Alt+Left/Right walks a confirmed version
chain), **Documents Sharing Verses…**, and **Export as .wvdoc…**. The
Library menu keeps collection-wide actions; File keeps library-level
operations (backup, restore, encryption).

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

**Markdown styling and commands**: the stored text stays plain, but the
editor displays the conventions nicely — headings larger and bold,
`**bold**` shown bold, `*italic*` shown italic, quote and list markers
tinted, the marker characters dimmed (View ▸ Markdown Styling to
toggle). The Edit menu types the conventions for you: **Ctrl+B** bold,
**Ctrl+I** italic, **Ctrl+1/2/3** heading levels (Ctrl+0 removes),
**Ctrl+Shift+L** bullet list, **Ctrl+Shift+Q** quote — plus the standard
Undo/Redo/Cut/Copy/Paste. Pressing Enter in a list or quote continues it
(numbered lists count up); Enter on an empty item ends it. Pasting from
Word keeps the words and drops the formatting automatically.

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
