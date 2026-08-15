# The WordVault User Guide

*A professional writer's open-source friend.*

This guide is in two halves. Part I explains the **philosophy** — the
handful of convictions everything else follows from. The remaining
parts walk through every feature **in detail**. If you only want the
quick orientation, press F1 instead; this document is for sitting down
with.

---

## Part I — The Philosophy

### Where WordVault came from

WordVault was born from a real library: thousands of essay documents
accumulated over years of writing, many of them the *same* essay saved
under different names — `Glory2.docx`, `Glory2-final.docx`,
`Glory2-final-revised.docx`. Every writer knows this pile. It exists
because ordinary word processors treat a document as a *file*, and a
file holds only one moment of a work's life. To keep an old state you
must copy it, name it, and manage it yourself — forever.

WordVault turns that upside down. A document here is the **whole
history of a piece of writing**, and the program keeps that history
for you, automatically, from the first sentence on.

### Nothing is ever lost

The first conviction: **writing is never destroyed**. Every time you
pause typing, WordVault records the state of the document as a new
*revision* — quietly, without being asked. Nothing you do afterwards
can erase what came before. Even "Restore this version" does not
rewrite the past: it takes the old state and appends it as the
*newest* revision, so history only ever grows.

This changes how deleting feels. Cut a paragraph without fear: it
still exists in every draft that contained it, one slider-drag away.
The safety net is not a feature you invoke — it is the ground you
stand on.

### The library, not files

The second conviction: your writing lives in **one library**, a
single SQLite database, not in a folder of files. The library is the
sole source of truth. Because everything is in one place, WordVault
can do things a pile of files cannot: search every essay you have
ever written in an instant, notice that two documents are versions of
the same essay, index every Scripture reference across the whole
body of work, and assemble any set of essays into a book.

Your old .docx files are not abandoned — they are *imported*, their
text and basic formatting carried in, their version relationships
detected and chained. The originals stay untouched wherever they
were.

### Plain text now, formatting at the end

The third conviction: **writing and typesetting are different jobs,
done at different times**. In WordVault you write plain text with a
few Markdown conventions (`# ` for a heading, `**bold**`, `*italic*`)
— light enough to type without thinking, and the editor styles them
on screen for comfort. But no fonts, margins, or page decisions live
in the text itself. Those belong to **print formats** (.wvfmt files),
applied only at the moment of printing. You will not see what the
page looks like until you print it — and that is deliberate. The
screen is for thinking; the format file is for the press. The same
essay can be printed as a Letter-size study paper today and a 6×9
book chapter tomorrow, without touching a word of it.

### Essays first, books from essays

The fourth conviction: **the essay is the unit of thought, and a book
is an assembly of essays**. Each chapter you write is a document with
its own history, its own notes, its own place in search results. A
book is a *recipe* — an ordered list of pointers into the library,
saved as a small project file. The book is built fresh from the
current text of its chapters every time, so revising an essay
automatically revises every book that contains it.

---

## Part II — Everyday Writing

### The window

Top to bottom: the **title header** (the document's name in serif
type, with *draft 12 of 87* and its date after it — always answering
"what am I looking at?"); the **editor**, where the text scrolls
beneath that fixed header; the **notes pane** below a draggable
divider; and the **History timeline** along the bottom. Around the
edges sit dockable panels — the Library list, Outline, Document Info,
and Library Info — each of which can be hidden or shown from the View
menu, and the window remembers your whole arrangement between
sessions.

A **blue border** marks the pane that will receive your typing — the
editor or the notes — so a glance tells you where words will land.

### You never save

There is no Save button to remember. When you stop typing for a few
seconds (the pause length is a Settings knob), the current state
becomes a revision. Switching documents, opening the Formatter,
closing the program — each captures pending words first. The status
bar's right corner shows the time of the last capture.

### Writing with Markdown conventions

- `# Heading`, `## Section`, `### Subsection` — headings (Ctrl+1,
  Ctrl+2, Ctrl+3 set them; Ctrl+0 removes)
- `**bold**` (Ctrl+B), `*italic*` (Ctrl+I)
- `> ` a quotation block; `- ` a bullet item; `1. ` a numbered item —
  and Enter continues a list automatically (Enter on an empty item
  ends it)
- A blank line separates paragraphs

The editor styles all of this on screen (a display courtesy — the
stored text is exactly what you typed). **View ▸ Markdown Styling**
turns the styling off if you prefer raw text.

### The notes pane

Below the divider is a scratchpad that belongs to the open document.
Notes save themselves, travel with the document, and never appear in
the text or its revisions — scaffolding, not masonry.

**Notes know their place.** Start a note (type on an empty line) and
it is stamped with where your cursor stood in the text, like
`▸ line 143 (The trust is not always…): `. Double-click a stamped
line later and the editor jumps back to that spot. The quoted words
help you find the passage even after line numbers drift.

### Seeing the document

- **Outline panel** — your `#` headings as a clickable map.
- **View ▸ Focus Current Section** (Ctrl+Shift+H) hides everything
  but the section you are working on; Ctrl+Shift+U shows all again.
- **View ▸ Color Text by Age** (Ctrl+Shift+A) — older lines in muted
  blue-gray, the newest in full color: what is settled, what is
  fresh.
- **View ▸ Line Numbers** — a classic gutter, for when notes say
  "line 143".
- **Document Info panel** — dates, drafts, word count, your position.

### Spelling, and your habits

**View ▸ Check Spelling** underlines doubtful words; right-click for
suggestions or *Add to dictionary* (the dictionary is seeded with the
names of the books of the Bible). WordVault also *watches how you
fix things*: every correction is classified (vowel swap, dropped
letter, swapped letters…) and **Help ▸ My Spelling Habits** shows the
running mirror. When the same fix has been seen enough times,
**View ▸ Auto-correct Repeated Fixes** applies it as you type — your
own personal autocorrect, learned from your own hands. Fixing a
misspelling once also offers to fix it everywhere in the document, as
a single undoable step.

---

## Part III — Time Travel

### The timeline

The History bar under the editor has one stop per revision: oldest at
the left, newest at the right. Drag the slider, click the **◀ ▶**
buttons beside it, or use Alt+Left / Alt+Right. Alt+Home jumps to the
newest.

Stepping into history shows the **end of the document** — the growing
edge, where each revision's changes appear — so stepping back through
drafts plays the essay's growth like a film in reverse. Scroll to any
passage and further steps hold that place; return to the end and the
view follows the end again.

### Reading the past

An old revision is **read-only**: the text wears an amber border and
a parchment tint, and the timeline's **Newest** and **Restore this
version** buttons light up blue — the way back. You can click into
old text (a cursor appears), select, and **copy**: paste into the
notes pane right away, or into the live text after clicking Newest.
The past can be quoted, never edited.

### Restoring

**Restore this version** (Ctrl+R) takes the old state you are viewing
and appends it as a brand-new revision. The intervening drafts remain
in history — restoration is a step forward, not an erasure.

### Version chains

When your old .docx files were imported, WordVault detected documents
that are versions of one another (`Glory2`, `Glory2-final`…) and
proposed **version groups** — confirm them in Library ▸ Review
Version Groups (Ctrl+G). Confirmed chains let Ctrl+Alt+Left / Right
step between the drafts of an essay that lived as separate files, and
the chain is noted in the Library list.

---

## Part IV — The Library

### Getting writing in

- **Library ▸ Import .docx Folder…** (Ctrl+Shift+I) walks a folder of
  Word documents into the library — text, headings, bold and italic
  preserved as Markdown; near-duplicate detection groups probable
  versions for review. Already-imported files are skipped, so re-runs
  are safe. Archive copies of the originals can be kept alongside.
- **tools/import_markdown.py** loads a folder of .md files, one
  document each (its partner **tools/split_book_docx.py** carves a
  compiled book .docx back into chapter Markdown, dropping title
  page, TOC, and index fields).
- **File ▸ Import .wvdoc** merges a document exported from another
  computer, history and all.

### Finding things

**Library ▸ Search Library…** (Ctrl+Shift+F) searches every document
(full-text indexed, so it is fast at any size), with sortable date
columns and centered excerpts. Within a document, Ctrl+F. **Ctrl+P**
is the quick-open: type a few letters of any title. Search can also
**replace across the library** — changes are staged and applied
document by document, each as a normal revision (so even a botched
replace is time-travelable).

### Gathering

Select a passage and **Mark for Gather** (Ctrl+M); do this across any
documents, then **Library ▸ Gather Tray…** (Ctrl+Shift+G) builds a
new document from the marked passages — each carrying a provenance
link to where it came from. This is how new essays grow out of old
ones without copy-paste amnesia.

### Tags

**Document ▸ Edit Tags…** attaches labels; the Library panel can
filter by them. The Book Formatter maintains `Book: <title>` tags
automatically for chapters of a saved book project.

### Scripture references

Every save re-indexes the document's Bible references (all 66 books,
chapter-and-verse parsing). **Document ▸ Documents Sharing Verses…**
(Ctrl+Shift+V) finds every essay citing the same passages — the
library remembers what you have written about Romans 8 even when you
do not.

### Keeping it safe

- **Library ▸ Back Up Library…** writes one encrypted file (AES-256);
  Restore brings it back.
- **Export as .wvdoc** carries one document, with full history,
  encrypted, to another machine.
- **Settings** can encrypt the live library itself (SQLCipher): the
  database on disk becomes unreadable without the passphrase asked at
  startup.

**There is no passphrase recovery.** A forgotten passphrase means the
file stays locked forever; that is what makes the protection real.

---

## Part V — Printing and Formats

### The idea

Formatting is a costume the text puts on at the door. **File ▸ Print
Document…** (Ctrl+Shift+P) asks one question — *which format?* — and
each choice is annotated with what it will do (byline, page numbers,
mirror margins…). The document itself remains innocent of fonts and
margins.

### .wvfmt files

A format is a small, readable TOML file. Your personal copies live in
`~/.wordvault/formats` (that is `C:\Users\<you>\.wordvault\formats`
on Windows) — **edit them freely; they are yours**. The shipped
masters live in the program's own `formats/` folder and should be
left alone: untouched personal copies upgrade automatically with new
releases, edited ones are never overwritten.

A format can set: page size (Letter, Legal, A4, A5, B5, or **6x9**,
the KDP book trim), margins — including Word-style **mirror margins**
with inside/outside edges and gutter — body and heading styles (font,
size, spacing, alignment, indents, page-break-before), quotation and
list styles, a **byline** (`{author} — {date}` after the title),
and running **headers and footers** with `{page}`, `{pages}`,
`{title}`, `{author}`, `{date}`. Mistakes in a format file are
reported by name when it loads, never silently guessed at. The full
specification is in `docs/format-file.md`.

Shipped formats: **Essay** (study papers), **Book Chapter**,
**Manuscript (double-spaced)** for submissions, and **KDP 6x9 Book**
(Georgia 11pt justified, mirror margins, measured from a real book
manuscript).

---

## Part VI — Making a Book

### The Formatter

**Library ▸ Book Formatter…** (Ctrl+Shift+B) opens the assembler:
your library on the left (with a filter box), the book's chapters in
order on the right, Add / Remove / Move Up / Move Down between them.
**Add All by Tag…** pulls in every essay carrying a chosen tag in one
motion — tag essays as book ideas form, gather them when the book
becomes real. Saving the project stamps the chapters with a
`Book: <title>` tag (and un-stamps removed ones), so membership shows
in the Library.

The recipe saves as a **.wvbook** file — pointers, never text. Every
build re-reads the library, so the book is always as current as its
chapters. The Formatter reopens your last project by itself.

### The sections

Checkboxes choose what the book includes, in book order:

- **Title page** — the title large and centered, "By <author>"
  beneath.
- **Copyright page** — fill in **Copyright Details…**: ISBN, year,
  edition, rights line, and the Scripture-translation notice (KJV
  needs none, being public domain; most modern translations require
  a credit line). Optionally a **QR code** at the foot of the page
  holding the book's title, author, ISBN, and the exact .wvfmt text
  used to print it — the book physically carries the recipe for its
  own layout, with a caption saying so. (Needs the free `qrcode`
  package: `pip install qrcode`.)
- **Table of contents** — every chapter and section heading with its
  *true* page number, read from the same layout the printer paints.
  There is no refresh step, and there cannot be a stale number: the
  body's page numbering restarts at 1 after the front matter, so the
  Contents' own length never shifts the numbers it reports.
- *(Coming: subject index and scripture index as back matter, and a
  KDP cover creator.)*

Front-matter pages print silently — no headers or page numbers — as
real books do; chapter page numbers begin at 1; mirror margins keep
alternating correctly straight through.

### Living with a book in progress

- **Document ▸ Previous / Next Chapter in Book** (Ctrl+Alt+Up/Down)
  walks the chapters in order — twelve essays read like one book,
  while every edit lands in exactly one place. The status bar shows
  "Chapter 4 of 12".
- **Create Draft Document** assembles the chapters into a single
  library document — a read-through proof for judging flow. It is an
  *output*: make fixes in the chapter essays, then create a fresh
  draft. (Editing the draft itself would create two versions of the
  truth, which is why chapter edits never sync *from* a draft.)
- **Build Book PDF…** produces the print-ready file — KDP accepts it
  directly as a paperback interior.

---

## Part VII — Settings

**Help ▸ Settings…** holds the everyday knobs: **Author name** (fills
`{author}` in print formats), **auto-save pause**, **editor font
size**, how far back **File ▸ Recent** remembers (25 unless you say
otherwise), whether WordVault **reopens the last document at
startup** (on by default), and **library encryption**.

---

## Appendix — Keyboard shortcuts

| Keys | Does |
| --- | --- |
| Ctrl+N / Ctrl+W | New document / close document |
| Ctrl+P | Quick-open by title |
| Ctrl+F / Ctrl+Shift+F | Find in document / search the library |
| Ctrl+B, Ctrl+I | Bold, italic |
| Ctrl+1..3, Ctrl+0 | Heading level, remove heading |
| Ctrl+M | Mark selection for gather |
| Ctrl+Shift+G | Gather tray |
| Ctrl+G | Review version groups |
| Alt+Left / Alt+Right / Alt+Home | Step through history / jump newest |
| Ctrl+R | Restore the viewed old version |
| Ctrl+Alt+Left / Right | Previous / next draft in a version chain |
| Ctrl+Alt+Up / Down | Previous / next chapter of the book |
| Ctrl+Shift+A | Color text by age |
| Ctrl+Shift+H / Ctrl+Shift+U | Focus section / unfocus |
| Ctrl+Shift+V | Documents sharing these verses |
| Ctrl+Shift+P | Print document |
| Ctrl+Shift+I | Import a .docx folder |
| Ctrl+Shift+B | Book Formatter |
| F1 / Shift+F1 | Quick help / this guide |

---

*WordVault is open source. The design document (DESIGN.md), this
guide, and all the code live in the repository — improvements
welcome.*
