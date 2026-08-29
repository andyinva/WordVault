# The .wvfmt Print Format File

*The contract between WordVault (which reads these files) and the
WordVault Formatter (which will create them). Version 1.*

## Philosophy

WordVault documents are plain Markdown — no hidden codes, ever. All
print styling lives in small, separate **format definition files**
(`.wvfmt`), chosen by name at print time. WordVault is deliberately
non-WYSIWYG: the formatted page is first seen on paper (or via a
Print-to-PDF printer). Format files are created by hand or by the
Formatter app's pick-from-a-list choices; WordVault never edits them.

A `.wvfmt` is a few hundred bytes of TOML — small enough to travel in a
QR code, which is how Format Cards carry a document's formatting on a
printed page.

## Location

WordVault reads every `*.wvfmt` in `~/.wordvault/formats/`. On first
use, the starter formats shipped with WordVault (Essay, Book Chapter,
Manuscript) are copied there; the author's edits are never overwritten.
Invalid files are skipped by the print chooser; loading one directly
reports exactly what is wrong (`FormatError`).

## File structure (TOML)

```toml
[format]
name = "Essay"                    # shown in the print chooser

[page]
size = "Letter"                   # Letter | Legal | A4 | A5 | B5 | 6x9
                                  # ("6x9" is the Amazon KDP paperback
                                  #  trim, 6 x 9 inches)
duplex = true                     # optional: the format itself asks the
                                  # printer for two-sided (long-edge
                                  # flip); printers without duplex
                                  # ignore it, PDFs are unaffected
margins_mm = [25, 20, 25, 20]     # shorthand: top, right, bottom, left, mm

# OR the full Word-style margins table (either one, not both):
[page.margins]
unit = "in"                       # "mm" (default) or "in"
top = 0.7
bottom = 0.5
# normal mode:      left / right
# mirror mode:      inside / outside (+ optional gutter)
inside = 1.2                      # spine side — left edge of odd
outside = 0.7                     # (right-hand) pages, right of even
gutter = 0                        # extra binding space added to inside

[body]                            # the default paragraph style
font = "Georgia"
size_pt = 11.5
line_spacing = 1.35               # multiple of single spacing
align = "justify"                 # left | right | center | justify
first_line_indent_mm = 6
space_after_pt = 4

[heading1]                        # also heading2 .. heading6
size_pt = 20
bold = true
align = "center"
page_break_before = true          # start a fresh page (book chapters)
space_before_pt = 18
space_after_pt = 14

[quote]                           # "> quoted" lines
italic = true
indent_mm = 10

[list]                            # "- bullets" and "1. numbered" items
indent_mm = 8
```

## Page furniture and generated content

```toml
[header]                          # drawn in the top margin, every page
left = ""
center = "{title}"
right = ""
size_pt = 9                       # optional: font, bold, italic too

[footer]                          # drawn in the bottom margin
center = "Page {page} of {pages}"

[byline]                          # ONE generated block after the first
text = "{author} — {date}"        # heading (or leading the text when the
italic = true                     # document has no opening heading);
align = "center"                  # takes any style key
```

**Variables** (filled at print time): `{title}` (the document's name),
`{author}` (from WordVault Settings), `{date}` (the printing date),
and — in headers/footers only — `{page}` and `{pages}`. An unknown
variable is a load-time error; `{page}` in a byline is too (a byline
prints once).

Headers, footers, and mirrored margins all switch printing to
WordVault's own paginator, which draws each page's text slice and
furniture at that page's margins.

## Mirror margins

With `inside`/`outside` given, pages alternate exactly as in Word's
"Mirror margins": page 1 is a right-hand page carrying
`inside + gutter` on its LEFT edge and `outside` on its right; page 2
mirrors. The text column width is constant, so the layout never
reflows between pages — WordVault paginates the document itself and
paints each page at its own offset.

## Style keys (any style section)

| key | type | meaning |
|---|---|---|
| `font` | string | font family name |
| `size_pt` | number | font size in points |
| `bold`, `italic` | boolean | face styling |
| `align` | string | left / right / center / justify |
| `line_spacing` | number | line height multiple (1.0 = single; any decimal — 1.12 works) |
| `line_height_pt` | number | EXACT leading in points (Word's "Exactly 14 pt"); outranks `line_spacing` — the finest line-spacing control |
| `first_line_indent_mm` | number | paragraph first-line indent |
| `indent_mm` | number | left margin of the whole block |
| `space_before_pt`, `space_after_pt` | number | vertical gaps |
| `page_break_before` | boolean | start a new page before this element |

## Inheritance rules

Every style section INHERITS from `[body]`: set only what differs.
A missing `headingN` falls back to the nearest shallower defined heading
(heading3 uses heading2's style if heading3 is absent), or to an
automatically bolder/larger body when no headings are defined at all.
`[body]` itself falls back to built-in defaults (Georgia 11pt, left,
1.3 spacing).

## Validation

Unknown sections, unknown keys, wrong value types, unsupported page
sizes, and malformed margins are all load-time errors with messages
naming the file, section, and key. A format that loads is a format that
prints.

## What the renderer consumes

The Markdown conventions WordVault already writes: `#`–`######`
headings, `> ` quotes, `- ` bullets, `1. ` numbered items (renumbered
sequentially per list), `**bold**` / `*italic*` / `***both***` inline
runs, and blank-line paragraph separation (consecutive plain lines join
into one paragraph). Everything else prints as body text.
