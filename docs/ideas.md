# Ideas — features for the days ahead

A living checklist of features users might expect from a word
processor, filtered through two sieves: does it fit WordVault's
philosophy (plain text, the vault, formatting at print time), and is
it genuinely easy given the machinery already built. Tick them off as
they land.

Some classics are **deliberately absent**: font pickers, text color,
centering buttons, page-margin dialogs in the editor. Those belong to
.wvfmt print formats — adding them to the editor would betray the
design (see the User Guide, Part I).

## Small comforts — an afternoon each

- [ ] **Selection word count** — select a passage, the status bar
  shows its word count. Writers check this constantly.
- [ ] **Find & Replace in the open document** (Ctrl+H) — the library
  has search-and-replace; the find bar just needs a replace field for
  the single document.
- [ ] **Smart typography as you type** — straight quotes to curly
  ones, `--` to an em dash, `...` to an ellipsis. For an essayist,
  the single most-missed Word behavior. (Care: never touch Markdown
  marker characters.)
- [ ] **Case tools** — UPPERCASE / lowercase / Title Case on the
  selection, in the Edit menu.
- [ ] **Insert today's date** at the cursor.
- [ ] **Quick zoom** — Ctrl+scroll (or keys) to grow/shrink the
  editor font without opening Settings.
- [ ] **Go to line** — the note stamps name line numbers; a jump box
  completes the pair.
- [ ] **Backup reminder** — a gentle status-bar nudge when the last
  backup is older than N days. Cheap insurance for the vault.

## Solid features — a day or two each

- [ ] **Print Preview** — QPrintPreviewDialog wraps the existing
  renderer almost for free. No betrayal of non-WYSIWYG: it is the
  print moment, just without paper. Probably the most-expected
  missing feature.
- [x] **Export as .docx / PDF / .md / .txt** — the reverse of import:
  headings, bold, italic, lists back into a Word file for people who
  ask for one. The md/txt halves are trivial; docx is the real day.
  *(Shipped: Document ▸ Export As, with a round-trip test proving
  exporter and importer are exact inverses. PDF was already covered
  by File ▸ Print.)*
- [ ] **Words written today** — because the vault holds timestamped
  revisions, WordVault can compute "today: +412 words" retroactively
  and exactly — a feature Word cannot honestly offer. Writers with
  goals love it.
- [ ] **Distraction-free mode** (F11) — hide every dock and bar; just
  the page and the title header.
- [x] **Dark mode** — expected everywhere now; a Qt palette swap plus
  care with the age colors and the blue/amber mode borders.
  *(Shipped: Settings checkbox, applied live, Fusion + dark palette
  with dark counterparts for the title banner, notes tint, history
  amber, and a readable karaoke light.)*
- [ ] **Document templates** — File ▸ New from Template: an essay
  skeleton, a sermon outline, a chapter opening — plain .md files in
  a templates folder, personal copies editable like print formats.

## Bigger, but worthy of the list

- [ ] **Copy as formatted** — selection to the clipboard as rich
  text, so pasting into an email keeps bold and italics.
- [ ] **Reading time and readability statistics** in Document Info.
- [ ] **Tag-scoped library search** — "search only the Book:
  Sufferings chapters."

## Already promised elsewhere

- [ ] **F4 — Subject and Scripture indexes** in the Book Formatter
  (porting the BibleCanon detector and vocabulary rules to the
  paginator; see tools/index_reference/).
- [ ] **F5 — KDP cover creator** (ebook front image + paperback wrap
  with computed spine; specs verified from Amazon first).

*Suggested first three: smart typography, Print Preview, and words
written today — two things everyone expects, plus one thing only
WordVault can do.*
