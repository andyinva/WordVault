# WordVault Help

## Part 1 — The Concept

**WordVault never forgets what you wrote.**

An ordinary word processor keeps only the latest version of a document —
every earlier wording is gone the moment you save over it. WordVault
works differently. Every time you pause typing for a few seconds, it
quietly records the state of your document, with the date and time, in a
database called your **library**. Nothing is ever erased or overwritten;
new states are only ever *added*. Think of it as a vault where every
stage of every essay you have ever written is kept safe.

Because the whole history is kept, you can **travel in time**: slide
back through a document and watch it as it was an hour ago, last month,
or in its first draft — and bring any old wording back without losing
anything written since.

**Documents are plain text.** WordVault stores your words only — no
fonts, no margins, no formatting codes. Formatting is a separate job for
a separate tool, applied later when a piece is ready for output. This
keeps your writing clean, portable, and readable forever.

**Versions are connected.** Many writers save draft after draft under
different file names. WordVault finds files that are really drafts of
the same essay and, with your approval, links them into a **version
chain** — one essay, with its whole life story attached.

**Provenance is remembered.** When you pull a passage from one essay
into another, WordVault records exactly where it came from. Your new
work always knows its sources.

**Your words stay yours.** The library can be encrypted with a
passphrase so nobody else can read it, and one-file encrypted backups
protect it against loss.

## Part 2 — Using WordVault

### Writing

Press **Ctrl+N** to create a document, then just write. There is no save
button to remember: every few seconds of stillness becomes a saved
revision automatically (the status bar shows the last save time).
**Ctrl+S** saves immediately if you want the reassurance.

Light formatting lives right in the text as simple marks the editor
displays nicely: **Ctrl+B** makes the selection `**bold**`, **Ctrl+I**
makes it `*italic*`, **Ctrl+1/2/3** turn the current line into a heading
(`# `, `## `, `### ` — Ctrl+0 removes it), **Ctrl+Shift+L** toggles a
bullet list and **Ctrl+Shift+Q** a quote. Enter inside a list continues
it; Enter on an empty item ends it. These marks are how formatting
survives into the future Formatter — the text itself stays plain.

### Going back in time

The **History bar** under the editor has one stop per revision. Drag the
slider, or press **Alt+Left** and **Alt+Right**, to step through the
document's past — each state is shown read-only with its date and time.
To bring an old state back, click **Restore this version** (Ctrl+R): it
returns as a brand-new revision, so nothing is lost. **Alt+Home** jumps
back to the present.

### The Library panel

Every document lives in the list on the left; double-click to open one.
The dropdown above the list filters by **tag** — you can tag any
document (topic, series, status) from the Document Info panel's
**Edit tags…** button. A "↳" before a title means it is a later draft in
a confirmed version chain.

### Finding things

**Ctrl+P** (Document ▸ Go to Document) opens a document by typing part
of its title — the list narrows as you type, Enter opens the top match.
**Ctrl+F** finds text within the current document: a slim bar appears
under the editor, searching as you type; Enter jumps to the next match,
Shift+Enter to the previous, Esc closes it.

**Ctrl+Shift+F** searches every document in the library instantly —
word, phrase, or pattern. Double-click a result to jump straight to it.
To change wording everywhere, fill in the Replace field and click
**Preview replace**: you see every proposed change first and can
uncheck any of them before applying. Applied replacements are ordinary
revisions — reversible like everything else.

### Collecting material for a new essay

While reading any document, select a passage and press **Ctrl+M** — it
is added to the **gather tray**. Mark as many passages as you like, in
as many documents as you like, over as many days as you like. Then open
**Library ▸ Gather Tray…** (Ctrl+Shift+G) and click **Gather into new
document**: all your marked passages become a new essay, each one
remembering where it came from.

### Reviewing version groups

After importing an old file collection, **Ctrl+G** opens the review
screen. WordVault proposes groups of files that look like drafts of the
same essay; you compare them side by side and **Confirm** (link them
into a chain) or **Reject**. There is no hurry — the queue waits between
sittings.

### Seeing your document clearly

- **View ▸ Color Text by Age** (Ctrl+Shift+A): older lines appear in a
  muted blue-gray, the newest in full color — see at a glance what is
  settled and what is fresh.
- **Outline panel**: lines starting with `#` (like `# Chapter One` or
  `## Section A`) become a clickable map of the document.
- **View ▸ Focus Current Section** (Ctrl+Shift+H): hides everything but
  the section you are working on. **Ctrl+Shift+U** shows it all again.
- **Document Info panel**: dates, drafts, word count, and your place in
  the text.
- **View ▸ Typewriter Scrolling**: holds the line you are typing at a
  fixed height — like a typewriter's print line — so text scrolls up
  past it instead of piling at the bottom of the window. Drag the small
  blue handle on the editor's left edge to place the line where you
  like it.

### Keeping your work safe

- **File ▸ Back Up Library…** writes everything into one encrypted file.
  Keep a recent one on a USB stick or cloud drive.
- **Help ▸ Settings…** can turn on **library encryption**: the library
  file itself becomes unreadable without your passphrase, which
  WordVault asks for at startup.
- **Export Document as .wvdoc…** carries a single document — with its
  full history — to another computer; **Import** merges it back.

**Important:** encrypted files have no passphrase recovery. Choose a
passphrase you will remember; a forgotten passphrase means the file
stays locked forever. That is what makes the protection real.
