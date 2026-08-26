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

### The vault: one place, not a pile of files

The second conviction: your writing lives in **the vault** — one
place, not a folder of files. Technically the vault is a single SQL
database (SQLite, the most widely deployed database engine in the
world, storing everything in one ordinary file you can copy and back
up). But "vault" says what it *means*: everything you have written,
every draft of it, held together in one guarded place. The vault is
the sole source of truth. Because everything is in it, WordVault can
do what a pile of files cannot: search every essay you have ever
written in an instant, notice that two documents are versions of the
same essay, index every Scripture reference across the whole body of
work, and assemble any set of essays into a book.

Your old .docx files are not abandoned — they are *imported*, their
text and basic formatting carried in, their version relationships
detected and chained. The originals stay untouched wherever they
were.

### The editor is a window into the vault

The third conviction follows from the second, and it is the one that
makes everything else work: **the editor is not a workspace beside
the vault — it is a window into it.** A word processor holds a copy
of your document in memory while the "real" one sits in a file;
saving means overwriting one with the other, and everything between
saves exists nowhere but RAM. WordVault has no such gap. The document
you are editing is *in the vault at all times*: it enters the vault
at birth (typed new, opened from a file, or imported), and from that
first second every pause of your fingers flows straight into it as a
revision.

This is why all the advantages of the design are simply *there* while
you write, with nothing to invoke: the timeline can step through
history because history is beneath the text; search finds the
sentence you wrote a minute ago because the vault already holds it;
notes, tags, and scripture indexing attach to something permanent;
the Book Formatter reads chapters that are always current; and a
power cut costs you at most a few seconds of typing. There is no
"unsaved work" because there is no state of existence outside the
vault for work to be lost from.

### Plain text now, formatting at the end

The fourth conviction: **writing and typesetting are different jobs,
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

The fifth conviction: **the essay is the unit of thought, and a book
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
`▸ line 143 (The trust is not always…): ` — the quoted words are the
start of the *sentence* under your cursor, so a long paragraph's many
thoughts each get their own address. The stamp is a link: **click
it** and the editor jumps back to that sentence (double-clicking
anywhere in the line works too). Clicking in the note's own words
just edits them, as any text. And the jump *searches for the quoted
words*, so it still finds the passage after editing has moved it off
its old line number.

### Seeing the document

- **Outline panel** — your `#` headings as a clickable map.
- **View ▸ Focus Current Section** (Ctrl+Shift+H) hides everything
  but the section you are working on; Ctrl+Shift+U shows all again.
- **View ▸ Color Text by Age** (Ctrl+Shift+A) — older lines in muted
  blue-gray, the newest in full color: what is settled, what is
  fresh.
- **View ▸ Line Numbers** — a classic gutter, for when notes say
  "line 143".
- **Document Info panel** — dates, drafts, word count, your position,
  and **Time writing**: the actual hours your hands were on this
  document. Only active writing counts — pauses up to a minute
  between keystrokes are the thinking inside sentences and count;
  longer gaps mean you were away and add nothing. An essay left open
  overnight gains not a second. The clock banks with every autosave
  and only ever grows.

### Hearing your writing

The **🔊 Read** button in the status bar (or Edit ▸ Read Aloud,
Ctrl+Shift+R) reads the document to you in the system's digital
voice — the selection if you have one, otherwise from the start of
the *sentence* under your cursor to the end of the document. Click
again to stop. Markdown markers are silent: you hear the words, not
the typography. As the voice reads, **the word being spoken lights
up** in the text and the view drifts along to keep it on screen —
follow with your eyes, stop the voice, and you know exactly where
you were. (The moving light needs a recent Qt; without it, reading
simply proceeds unlit.) The pace is yours: **Reading speed** in
Help ▸ Settings… runs from 50% (half speed, for careful proofing)
to 150% (a brisk skim), with 100% the voice's natural rate. Hearing a sentence
catches what the eye forgives — the doubled word, the rhythm that
stumbles. (On Ubuntu this needs the standard speech system:
`sudo apt install speech-dispatcher`.)

### Spelling, and your habits

**View ▸ Check Spelling** underlines doubtful words — in the text
*and in the notes pane*, which shares the same dictionary and offers
the same right-click suggestions; right-click for
suggestions or *Add to dictionary* (the dictionary is seeded with the
names of the books of the Bible). Suggestions draw on four wells,
strongest first: your **own history** (a misspelling fixed even once
leads with its proven correction ever after), the **common classics**
(~2,600 famous English misspellings ship with WordVault — recieve,
seperate, teh — answered instantly, courtesy of Wikipedia's
community list), **sound-alikes** (words
are indexed by their consonant skeleton, so a phonetic try like
"jeprodising" finds "jeopardizing" even though it is too many
letter-edits away for ordinary spellcheck search — vowels wobble,
the bones stay true), and the classic close-spellings.
**Help ▸ Spelling Dictionary…** is the word desk: type any word and
see at once whether it is known (yours or the standard dictionary's),
whether you have stumbled over it before and what you corrected it
to, what it might *be* if unknown — and add it to your dictionary on
the spot. The matching list even lets your errors serve as lookup
keys: your past fixes appear as "typed → corrected", so typing
"jep" surfaces *jeprodising → jeopardizing* — your own misspelling,
pointing at its word. WordVault also *watches how you
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

While stepping through time the view **holds your place**. Go to a
passage and every step back or forward keeps it on screen, so you can
watch one paragraph's history without repositioning. If the passage
did not yet exist in an older draft, the view rests on the seam where
it would later be born. Two special stops: at the document's **end**
(the growing edge), the view follows the end from step to step,
playing the essay's growth like a film in reverse; and arriving back
at **Newest** always returns you — scroll and cursor both — to the
exact spot where you left the live document. A trip into history is
an excursion: it ends where it began.

### Reading the past

An old revision is **read-only**: the text wears an amber border and
a parchment tint, and the timeline's **Newest** and **Restore this
version** buttons light up blue — the way back. You can click into
old text (a cursor appears), select, and **copy**: paste into the
notes pane right away, or into the live text after clicking Newest.
The past can be quoted, never edited.

Old text also carries a quiet **wheat wash** on the words that have
since been rewritten or removed — what you are reading that did *not*
survive into today's draft. Near the newest revision, almost nothing
is washed; the farther back you step, the more of the page carries
it: a glance tells you how much the essay has moved since that day.

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

- **File ▸ Open File (docx, md, txt)** brings in a *single* outside
  file: it is converted to WordVault's conventions (the docx path
  uses the full importer below), saved into the vault as a new
  document — title from its first heading, dates from the file's own
  best evidence — and opened for editing at once. Protected by
  revisions from its first second; open deliberately, since the
  vault keeps everything.
- **Library ▸ Import .docx Folder…** (Ctrl+Shift+I) walks a folder of
  Word documents into the library, converting real Word formatting to
  the Markdown conventions: headings and titles, bold and italic
  (underline becomes italic — emphasis preserved), bullet and
  numbered lists whether made with styles *or* the ribbon buttons,
  quotations (the Quote styles and indented paragraphs alike),
  hyperlinks as "text (address)", and table text flattened to one
  line per row so no words are lost. Paragraphs are always separated
  by a blank line. Near-duplicate detection groups probable versions
  for review; already-imported files are skipped, so re-runs are
  safe; archive copies of the originals can be kept alongside.
- **Library ▸ Refresh Formatting from Originals…** re-reads every
  imported document's original .docx with the *current* converter.
  Documents whose text improves get one new revision each — the old
  text stays one step back in history. It also **verifies dates**:
  Word records created/modified *inside* every docx, and those
  records outrank filesystem dates (which every copy or sync can
  reset to copy-day). Stored dates that disagree with the file's own
  record are corrected, so the library's chronology reflects when
  the writing was actually written. Run it after any WordVault
  update that improves the importer.
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

### The Wastebasket

"Nothing is ever lost" and "I opened that file by mistake" meet in
the **Wastebasket**: deletion as banishment, never destruction.
**Document ▸ Move to Wastebasket…** (after a confirmation) makes a
document vanish from the library list, searches, quick-open, Recent,
tags, and the Formatter — for every daily purpose it is gone. But
nothing is severed: **Library ▸ Wastebasket…** lists the banished,
and **Restore** brings one back whole — text, history, notes, and
tags — ten minutes or ten years later. There is deliberately no
destroy button; at the size of text, eternal mercy is cheap.

(Its small sibling: **Edit ▸ Delete Selection** removes highlighted
text *without touching the clipboard* — Cut's quiet twin, for when
what you copied earlier must stay copied.)

#### What deletion reveals about the vault

The Wastebasket is a good place to watch the vault's principles at
work, because "delete" is where they are tested.

In a folder of files, deleting is simple: a file is an island, and
removing it disturbs nothing else. In the vault, a document is not an
island — it is a knot in a web. Its revisions hang beneath it. Notes
are pinned to it. Tags point at it. Passages gathered *out* of it
into other essays carry provenance links back *into* it. It may sit
in a version chain beside its own earlier drafts, be listed as a
chapter in a book project, and be indexed by every Scripture verse it
cites. A true deletion would have to cut every one of those threads —
and each cut would quietly falsify something else: a gathered passage
that no longer knows where it came from, a book that has lost a
chapter, a verse index pointing at nothing.

So the vault does what it always does: it **adds a fact instead of
destroying one**. Banishing a document writes a single small truth —
*banished on this date* — and every list, search, and menu simply
declines to show what carries that mark. The web is untouched
underneath. That is why Restore is perfect and instant: there is
nothing to reassemble, only a mark to lift. And it is the same move
the vault makes everywhere — "Restore this version" adds a revision
rather than rewriting history; a search-and-replace saves new
revisions rather than editing old ones; even the spelling watcher
only ever appends to its log. Append a fact, never subtract one:
that is the whole design, visible in a wastebasket.

It also explains what would otherwise seem stubborn — why there is
no "empty wastebasket." Destruction is the one operation that cannot
be appended, and a vault holding thirty years of essays in less
space than a single photograph never needs it. The confirmation
question you answer when banishing is honest for the same reason: it
does not warn "this cannot be undone," because in WordVault, it can.

### Leaving the vault

**Document ▸ Export As** sends the open document out: as a **.docx**
with real Word styles rebuilt (the importer's exact reverse —
headings, bold, italics, lists, and quotes all survive the round
trip), as **.md** (the text exactly as stored), or as **.txt**
(Markdown markers stripped — the words without the typography). It
exports what is *on screen*, so while time traveling you can export
an old draft as that old draft. For a PDF, use File ▸ Print with any
format. The fourth entry, **.wvdoc**, is different in kind: it
carries the document *with its entire revision history*, encrypted,
for merging into another WordVault — the others export a moment; it
exports the whole life.

### Keeping it safe

- **Library ▸ Back Up Library…** writes one encrypted file (AES-256);
  Restore brings it back.
- **Export as .wvdoc** carries one document, with full history,
  encrypted, to another machine.
- **Settings** can encrypt the live library itself (SQLCipher): the
  vault on disk becomes unreadable without the passphrase asked at
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

**Formats can be learned by example.** File ▸ **Learn Print Format
from .docx…** reads a Word document you admire — its page size,
margins (mirror margins included), body and heading styles, and
whether it numbers its pages — asks what to call the result, and
writes a validated .wvfmt into your personal formats folder, ready
in the print chooser at once. The learned file says in its comments
where it came from, and is yours to tune like any other.

Shipped formats: **Essay** (study papers), **Essay Draft** (the
paper-saver: half-inch margins, 10pt type, tight spacing, two-sided
printing requested by the format itself — for drafts you mark up),
**Book Chapter**, **Manuscript (double-spaced)** for submissions,
and **KDP 6x9 Book** (Georgia 11pt justified, mirror margins,
measured from a real book manuscript).

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
- **Scripture Index** — every Bible reference in the book, in
  canonical order (Genesis before Exodus, verses numeric), each with
  the pages where it is cited. Found by WordVault's own reference
  parser; needs nothing from you.
- **Subject Index** — headwords from a controlled vocabulary
  (choose the vocabulary.json with **Subject Vocabulary…**; the Word
  Index Creator's file works unchanged). Triggers are
  case-insensitive substrings, or regular expressions prefixed
  `re:`; per-term caps — like "at most 2 pages per chapter" — keep
  common words from flooding the index, exactly as in the original
  tool.
- Index pages sit after the last chapter and **continue the body's
  page numbering**, as book back matter does. Their page numbers are
  read from the same layout the printer paints — like the table of
  contents, they cannot go stale.
- *(Coming: a KDP cover creator.)*

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
`{author}` in print formats), **auto-save pause**, the **editor font**
(any font installed on this system — display only, since printed
pages take their fonts from .wvfmt files; a family the other platform
lacks falls back to its nearest look-alike) and its **size**, the
**notes pane's own font and size** (marginalia may suit a smaller,
plainer face), how far
back **File ▸ Recent** remembers (25 unless you say
otherwise), whether WordVault **reopens the last document at
startup** (on by default), **Dark mode** (the whole window, applied
the moment you click OK — same dress on Windows and Ubuntu), the
**Enter key** (by default Enter *starts a new paragraph*: it adds the
blank line itself, leaving the cursor ready to write on — in the
vault a paragraph is a line and a blank line makes the next one, so
this is one keystroke doing exactly what two used to; Shift+Enter is
always a plain single return, lists still continue their markers, and
"Plain return" restores the old behavior — note that a first-line
*indent* is a printing matter, set by `first_line_indent` in a
`.wvfmt`, never by tabs in the text), **Disabled keys** (check any of
Pg Up, Pg Dn, Home, End, or Insert and the editor simply ignores that
key — for keyboards where a stray press keeps throwing the view
across the document, or where Insert silently flips overwrite mode;
the keys still work everywhere else in the program), **Highlight the
line being edited** (a gentle full-width wash under the cursor's line
— a calm blue-gray on the white page, its counterpart in dark mode —
on by default, and it politely steps aside in history views), and
**library encryption**.

### Personal extensions

A copy of WordVault can grow abilities its owner adds by hand. At
startup the program looks in the personal folder
`~/.wordvault/extensions/` and loads any Python file there that
defines a `register(window)` function — typically to add a button to
the timeline bar with `window.add_extension_button(text, tooltip,
callback)`. Most copies have no such folder, and see nothing: no
feature is shipped, hidden, or disabled. An extension is ordinary
Python running with the program's own powers, so only place files
there that you wrote or have read and trust — and a broken one is
skipped with a note on the console, never allowed to stop WordVault
from starting.

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
