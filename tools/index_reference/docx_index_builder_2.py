#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docx_index_builder.py
=====================

Rebuilds the **Scripture** and **Subject** indexes in a Word (.docx) manuscript
by regenerating every ``XE`` index-entry field from scratch.

Why this exists
---------------
A Word index is generated from hidden ``{ XE "entry" }`` field markers scattered
through the body text.  When you add new material you normally have to hand-mark
every new term and verse.  This tool removes that chore: it deletes all existing
``XE`` markers and rebuilds them in one pass, so after editing you just run the
script again and the index data is current.

What it does
------------
* **Scripture** references (e.g. ``2 Corinthians 3:7-11``) are detected
  automatically and routed to the Scripture index via the ``\\f "b"`` flag.
  Each entry carries a *hidden* sort key (Word's ``display;sortkey`` collating
  trick) so the index sorts in canonical/numeric order while printing only the
  clean reference -- e.g. ``Genesis;01:3\\:7;003.007`` shows as ``Genesis`` /
  ``3:7`` but sorts by ``01`` / ``003.007``.
* **Subject** terms are matched against a controlled-vocabulary file
  (``vocabulary.json``) and routed to the Subject index via ``\\f "a"``.
* Existing ``{ INDEX }`` fields are left untouched.  NEW in this version:
  if the manuscript has no ``{ INDEX \\f "b" }`` (Scripture) or
  ``{ INDEX \\f "a" }`` (Subject) field at all, the build step now APPENDS
  the missing index section(s) at the end of the document -- a page break,
  a "Scripture Index" / "Subject Index" heading, and the INDEX field itself.
  Without this, a manuscript that was never hand-indexed in Word would get
  all its XE markers but display no index, because F9 can only refresh
  fields that already exist; it cannot create them.
* After running, open the document in Word and press **Ctrl+A** then **F9**
  to build/repaginate both indexes (and the table of contents).

Design notes
------------
* Markers are placed at *paragraph* granularity: each term/verse found in a
  paragraph produces ONE marker appended to that paragraph.  Word indexes by
  page, so this puts the entry on the right page while collapsing repeats
  (a term mentioned five times in one paragraph yields one page number, not
  five).  This avoids the over-indexing that Word's AutoMark produces.
* The operation is idempotent: every run strips all XE markers first, then
  rebuilds, so repeated runs converge to the same result.

Requirements
------------
* Python 3.8+
* lxml          ->  pip install lxml      (works on Ubuntu and Windows 11)

Typical use
-----------
    # 1. Seed a vocabulary file from the terms already in the manuscript:
    python docx_index_builder.py init-vocab book.docx -o vocabulary.json

    # 2. (Edit vocabulary.json by hand to taste.)

    # 3. Rebuild both indexes into a new file:
    python docx_index_builder.py build book.docx -v vocabulary.json -o book_indexed.docx

    # 4. Open book_indexed.docx in Word -> Ctrl+A -> F9.

    # Optional: just see what WOULD be tagged, no file written:
    python docx_index_builder.py report book.docx -v vocabulary.json

Capping subject density
-----------------------
A generated index can over-list a common word.  Two controls fix that:

  * Globally, from the command line --
        build book.docx -v vocabulary.json -o out.docx \\
              --subject-scope chapter --subject-max 1
    means "each subject term is marked at most once per chapter".

  * Per term, in vocabulary.json, by giving an object instead of a list --
        "Glory": { "triggers": ["glory"], "max": 1, "scope": "chapter" }
    A per-term setting overrides the command-line default, so you can leave
    most terms uncapped and rein in only the noisy handful.  Scope may be
    "paragraph" (default, no limit), "chapter", or "document".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from collections import OrderedDict, defaultdict

try:
    from lxml import etree
except ImportError:  # pragma: no cover - friendly message for a missing dep
    sys.stderr.write(
        "This tool needs the 'lxml' package.\n"
        "Install it with:  pip install lxml\n"
    )
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Word / OOXML namespace plumbing
# ---------------------------------------------------------------------------
# Every WordprocessingML element lives in this namespace.  We keep the full
# Clark-notation prefix ("{...}tag") in one constant so element creation and
# lookups stay readable.
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# The xml:space attribute used to preserve the spaces around field codes.
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def w(tag: str) -> str:
    """Return a fully-qualified WordprocessingML tag name, e.g. w('r') -> '{...}r'."""
    return W + tag


def local_name(tag: str) -> str:
    """Strip the namespace from a Clark-notation tag: '{...}pStyle' -> 'pStyle'."""
    return tag.split("}")[-1]


# ===========================================================================
# 1.  The biblical canon: book numbering, name variants, detection regex
# ===========================================================================
class BibleCanon:
    """
    Knows the 66 books of the KJV canon, their two-digit ordering prefix
    (so the Scripture index sorts in biblical order rather than alphabetically),
    and how to recognise their names in running prose.
    """

    # Canonical order.  Each tuple is (canonical_name, [alternate spellings]).
    # The list index + 1 gives the book number used in the sort key.
    _BOOKS = [
        ("Genesis", ["Gen"]),
        ("Exodus", ["Exod", "Exo"]),
        ("Leviticus", ["Lev"]),
        ("Numbers", ["Num"]),
        ("Deuteronomy", ["Deut", "Deu"]),
        ("Joshua", ["Josh"]),
        ("Judges", ["Judg"]),
        ("Ruth", []),
        ("1 Samuel", ["I Samuel", "1 Sam", "First Samuel"]),
        ("2 Samuel", ["II Samuel", "2 Sam", "Second Samuel"]),
        ("1 Kings", ["I Kings", "1 Kgs", "First Kings"]),
        ("2 Kings", ["II Kings", "2 Kgs", "Second Kings"]),
        ("1 Chronicles", ["I Chronicles", "1 Chron", "1 Chr"]),
        ("2 Chronicles", ["II Chronicles", "2 Chron", "2 Chr"]),
        ("Ezra", []),
        ("Nehemiah", ["Neh"]),
        ("Esther", ["Esth"]),
        ("Job", []),
        ("Psalms", ["Psalm", "Pslm", "Ps"]),
        ("Proverbs", ["Prov"]),
        ("Ecclesiastes", ["Eccl", "Eccles"]),
        ("Song of Solomon", ["Song of Songs", "Canticles", "Song"]),
        ("Isaiah", ["Isa"]),
        ("Jeremiah", ["Jer"]),
        ("Lamentations", ["Lam"]),
        ("Ezekiel", ["Ezek"]),
        ("Daniel", ["Dan"]),
        ("Hosea", ["Hos"]),
        ("Joel", []),
        ("Amos", []),
        ("Obadiah", ["Obad"]),
        ("Jonah", []),
        ("Micah", ["Mic"]),
        ("Nahum", ["Nah"]),
        ("Habakkuk", ["Hab"]),
        ("Zephaniah", ["Zeph"]),
        ("Haggai", ["Hag"]),
        ("Zechariah", ["Zech"]),
        ("Malachi", ["Mal"]),
        ("Matthew", ["Matt"]),
        ("Mark", []),
        ("Luke", []),
        ("John", []),
        ("Acts", []),
        ("Romans", ["Rom"]),
        ("1 Corinthians", ["I Corinthians", "1 Cor", "First Corinthians"]),
        ("2 Corinthians", ["II Corinthians", "2 Cor", "Second Corinthians"]),
        ("Galatians", ["Gal"]),
        ("Ephesians", ["Eph"]),
        ("Philippians", ["Phil", "Php"]),
        ("Colossians", ["Col"]),
        ("1 Thessalonians", ["I Thessalonians", "1 Thess", "1 Thes"]),
        ("2 Thessalonians", ["II Thessalonians", "2 Thess", "2 Thes"]),
        ("1 Timothy", ["I Timothy", "1 Tim", "First Timothy"]),
        ("2 Timothy", ["II Timothy", "2 Tim", "Second Timothy"]),
        ("Titus", ["Tit"]),
        ("Philemon", ["Philem", "Phlm"]),
        ("Hebrews", ["Heb"]),
        ("James", ["Jas"]),
        ("1 Peter", ["I Peter", "1 Pet", "First Peter"]),
        ("2 Peter", ["II Peter", "2 Pet", "Second Peter"]),
        ("1 John", ["I John", "First John"]),
        ("2 John", ["II John", "Second John"]),
        ("3 John", ["III John", "Third John"]),
        ("Jude", []),
        ("Revelation", ["Revelations", "Rev", "Apocalypse"]),
    ]

    def __init__(self):
        # name (lowercased) -> (book_number, canonical_name)
        self._lookup = {}
        for i, (canon, alts) in enumerate(self._BOOKS, start=1):
            for name in [canon] + alts:
                self._lookup[name.lower()] = (i, canon)
        self._reference_re = self._build_reference_regex()

    def _build_reference_regex(self) -> "re.Pattern":
        """
        Build one big regex that matches a scripture reference in prose, e.g.
        'John 5:19', '2 Corinthians 3:7-11', 'Leviticus 23', 'Acts 3:22, 23'.

        Book alternatives are sorted longest-first so that '1 John' wins over
        'John' and 'Song of Solomon' wins over 'Song'.
        """
        names = sorted(self._lookup.keys(), key=len, reverse=True)
        # Escape each name and allow flexible internal whitespace.
        book_alt = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names)
        # chapter, then an optional ":verse(s)" part with ranges/lists.
        verses = r"\d{1,3}(?:\s*[-\u2013]\s*\d{1,3})?(?:\s*,\s*\d{1,3}(?:\s*[-\u2013]\s*\d{1,3})?)*"
        pattern = (
            r"\b(?P<book>" + book_alt + r")"
            r"\.?\s+"                       # optional '.' after an abbreviation
            r"(?P<chap>\d{1,3})"
            r"(?:\s*:\s*(?P<verses>" + verses + r"))?"
        )
        return re.compile(pattern, re.IGNORECASE)

    def resolve(self, raw_book: str):
        """Map any recognised spelling to (number, canonical_name) or None."""
        key = re.sub(r"\s+", " ", raw_book.strip()).lower()
        return self._lookup.get(key)

    def find_references(self, text: str, allow_chapter_only: bool = True):
        """
        Yield ScriptureReference objects for every reference found in `text`.
        """
        for m in self._reference_re.finditer(text):
            info = self.resolve(m.group("book"))
            if not info:
                continue
            number, canon = info
            verses = m.group("verses")
            if verses is None and not allow_chapter_only:
                continue
            yield ScriptureReference(number, canon, int(m.group("chap")), verses)


# ===========================================================================
# 2.  A single scripture reference -> its XE entry text
# ===========================================================================
class ScriptureReference:
    """
    One parsed reference.  Knows how to render itself as the exact XE entry
    text used in the manuscript, including the zero-padded sort key and the
    escaped colon (\\:) that Word needs because a bare colon is the sub-entry
    separator.
    """

    def __init__(self, book_number: int, book_name: str, chapter: int, verses):
        self.book_number = book_number
        self.book_name = book_name
        self.chapter = chapter
        # `verses` is the raw captured string ("7-8", "15, 18, 19") or None.
        self.verses = self._normalize_verses(verses) if verses else None

    @staticmethod
    def _normalize_verses(verses: str) -> str:
        """Tidy whitespace and dashes: '7 - 8' -> '7-8', en-dash -> hyphen."""
        v = verses.replace("\u2013", "-")
        v = re.sub(r"\s*-\s*", "-", v)
        v = re.sub(r"\s*,\s*", ", ", v)
        return v.strip()

    @property
    def first_verse(self) -> int:
        """The first verse number, used for sorting within a chapter."""
        if not self.verses:
            return 0
        return int(re.match(r"\d+", self.verses).group())

    def entry_text(self) -> str:
        """
        Produce the XE entry string using Word's index collating-sequence
        override: each level is written as  "display;sortkey" , and the two
        levels are joined by an unescaped colon.  The sort keys are hidden --
        only the display text appears in the finished index.  For example

            'Genesis;01:3\\:7-8;003.007'  ->  index shows  Genesis / 3:7-8
                                              but sorts by  01      / 003.007

        This is why the padded numbers no longer print: they live after the
        semicolons.  The colon inside the verse reference is escaped (\\:) so
        Word does not mistake it for the main/sub-entry separator.
        """
        main_display = self.book_name                  # e.g. "Genesis"
        main_sort = "%02d" % self.book_number          # e.g. "01" -> canonical order
        if self.verses:
            sub_display = "%d\\:%s" % (self.chapter, self.verses)      # "3\:7-8"
            sub_sort = "%03d.%03d" % (self.chapter, self.first_verse)  # "003.007"
        else:
            sub_display = "%d" % self.chapter           # whole chapter, e.g. "3"
            sub_sort = "%03d" % self.chapter            # "003"
        # Format:  MainDisplay;MainSort:SubDisplay;SubSort
        return "%s;%s:%s;%s" % (main_display, main_sort, sub_display, sub_sort)

    def dedupe_key(self):
        """Identity used to avoid duplicate markers in the same paragraph."""
        return (self.book_number, self.chapter, self.verses or "")


# ===========================================================================
# 3.  The subject controlled vocabulary
# ===========================================================================
class VocabEntry:
    """
    One subject headword together with its trigger patterns and an optional
    occurrence cap.

    * triggers  : list of patterns; each is a case-insensitive plain substring
                  unless it begins with 're:' , in which case the remainder is
                  treated as a regular expression.
    * max_count : the maximum number of paragraphs that may receive this marker
                  within the chosen scope (None = unlimited).
    * scope     : the bucket the cap is measured in --
                    "paragraph" : no document/chapter limit (the default; the
                                  marker already appears at most once per
                                  paragraph because in-paragraph repeats
                                  collapse to a single page number).
                    "chapter"   : at most `max_count` paragraphs per chapter,
                                  so max_count=1 means "first mention per
                                  chapter only".
                    "document"  : at most `max_count` paragraphs in the whole
                                  manuscript.
    """

    VALID_SCOPES = {"paragraph", "chapter", "document"}

    def __init__(self, headword, triggers, max_count=None, scope=None):
        self.headword = headword
        self.patterns = [self._compile(t) for t in triggers]
        self.max_count = max_count
        if scope is not None and scope not in self.VALID_SCOPES:
            sys.stderr.write(
                "Warning: term %r has unknown scope %r; using the default.\n"
                % (headword, scope))
            scope = None
        self.scope = scope  # None => fall back to the builder/CLI default

    @staticmethod
    def _compile(trigger: str) -> "re.Pattern":
        if trigger.startswith("re:"):
            return re.compile(trigger[3:], re.IGNORECASE)
        # Plain substring, case-insensitive.
        return re.compile(re.escape(trigger), re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.patterns)


class Vocabulary:
    """
    A controlled vocabulary of subject headwords loaded from JSON.

    Each value may take either of two forms:

        "Trinity": ["Trinity", "Trinitarian"]          # triggers only

        "Glory": {                                      # triggers + a cap
          "triggers": ["glory"],
          "max": 1,
          "scope": "chapter"
        }

    The plain-list form keeps full backward compatibility with older
    vocabulary files.  `default_max` and `default_scope` (set from the command
    line) fill in for any entry that does not specify its own cap, so you can
    tame a too-dense index globally without editing every term.
    """

    def __init__(self, entries, default_max=None, default_scope="paragraph"):
        self.entries = entries
        self.default_max = default_max
        self.default_scope = default_scope

    def effective_cap(self, entry: "VocabEntry"):
        """Resolve (max_count, scope) for an entry, applying the CLI defaults."""
        cap = entry.max_count if entry.max_count is not None else self.default_max
        scope = entry.scope if entry.scope is not None else self.default_scope
        return cap, scope

    @classmethod
    def load(cls, path: str, default_max=None, default_scope="paragraph"):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh, object_pairs_hook=OrderedDict)
        entries = []
        for headword, value in data.items():
            if isinstance(value, dict):
                triggers = value.get("triggers", [])
                max_count = value.get("max")
                scope = value.get("scope")
            else:
                triggers = value      # a plain list of triggers (legacy form)
                max_count = None
                scope = None
            entries.append(VocabEntry(headword, triggers, max_count, scope))
        return cls(entries, default_max=default_max, default_scope=default_scope)

    def find_entries(self, text: str):
        """Return the VocabEntry objects whose triggers fire in `text`."""
        return [e for e in self.entries if e.matches(text)]


# ===========================================================================
# 4.  The document engine: strip old markers, insert new ones, save
# ===========================================================================
class IndexBuilder:
    """
    Opens a .docx, regenerates its XE markers, and writes a new .docx.

    The .docx is a ZIP archive; only word/document.xml is rewritten, every
    other part is copied through byte-for-byte so nothing else is disturbed.
    """

    # Paragraph styles whose paragraphs must never receive markers, because
    # they are machine-generated (the index and TOC results) or are headings.
    SKIP_STYLES = {
        "Index1", "Index2", "Index3", "Index4",
        "TOC1", "TOC2", "TOC3", "TOCHeading",
    }
    HEADING_STYLES = {"Heading1", "Heading2", "Heading3", "Heading4", "Title"}

    def __init__(self, canon: BibleCanon, vocab: Vocabulary | None,
                 allow_chapter_only: bool = True,
                 index_headings: bool = False):
        self.canon = canon
        self.vocab = vocab
        self.allow_chapter_only = allow_chapter_only
        self.index_headings = index_headings
        self.tree = None
        # statistics collected during a build, keyed by chapter title
        self.stats = defaultdict(lambda: {"subject": 0, "scripture": 0, "words": 0})
        # running counts used to enforce per-term occurrence caps
        self._subject_counts = defaultdict(int)
        # names of index sections appended because the document lacked them,
        # e.g. ["Scripture Index"]; used for the end-of-run report
        self.added_index_sections = []

    # -- low-level helpers --------------------------------------------------
    @staticmethod
    def _para_style(paragraph) -> str:
        pstyle = paragraph.find(w("pPr") + "/" + w("pStyle"))
        return pstyle.get(w("val")) if pstyle is not None else ""

    @staticmethod
    def _para_text(paragraph) -> str:
        """Visible text of a paragraph = its <w:t> runs (not field codes)."""
        return "".join(t.text or "" for t in paragraph.iter(w("t")))

    @staticmethod
    def _make_xe_field(entry_text: str, flag: str):
        """
        Build the three <w:r> runs of a single hidden XE field:
            begin  ->  instrText (' XE "entry" \\f "x" ')  ->  end
        Returns a list of three lxml elements ready to append to a paragraph.
        """
        # Guard against an unescaped double-quote breaking the field code.
        safe = entry_text.replace('"', "'")
        instr = ' XE "%s" \\f "%s" ' % (safe, flag)

        r_begin = etree.Element(w("r"))
        fc1 = etree.SubElement(r_begin, w("fldChar"))
        fc1.set(w("fldCharType"), "begin")

        r_instr = etree.Element(w("r"))
        it = etree.SubElement(r_instr, w("instrText"))
        it.set(XML_SPACE, "preserve")
        it.text = instr

        r_end = etree.Element(w("r"))
        fc2 = etree.SubElement(r_end, w("fldChar"))
        fc2.set(w("fldCharType"), "end")

        return [r_begin, r_instr, r_end]

    # -- step 1: remove every existing XE field -----------------------------
    def _strip_xe(self, paragraph) -> int:
        """
        Delete all XE field run-groups that are direct children of `paragraph`.

        Fields are flat run sequences delimited by fldChar begin/end.  We walk
        the child runs with a stack so nested fields (e.g. an INDEX field, which
        we must NOT touch) are handled correctly: a group is removed only when
        its OWN instruction text starts with 'XE'.
        """
        stack = []
        to_remove = []
        for child in list(paragraph):
            if child.tag != w("r"):
                continue
            fld = child.find(w("fldChar"))
            instr = child.find(w("instrText"))
            ftype = fld.get(w("fldCharType")) if fld is not None else None

            if ftype == "begin":
                stack.append({"members": [child], "instr": ""})
                continue
            if stack:
                frame = stack[-1]
                frame["members"].append(child)
                if instr is not None and instr.text:
                    frame["instr"] += instr.text
                if ftype == "end":
                    frame = stack.pop()
                    if frame["instr"].lstrip().startswith("XE"):
                        to_remove.extend(frame["members"])
        for run in to_remove:
            paragraph.remove(run)
        return len(to_remove) // 3  # three runs per XE field

    # -- step 2: add markers for one paragraph ------------------------------
    def _tag_paragraph(self, paragraph, chapter_title: str):
        style = self._para_style(paragraph)
        if style in self.SKIP_STYLES:
            return
        is_heading = style in self.HEADING_STYLES
        if is_heading and not self.index_headings:
            return

        # Never tag a paragraph that hosts an INDEX field itself (e.g. the
        # sections this tool appends): its visible text is machine output,
        # and a vocabulary trigger matching it would corrupt the index.
        for it in paragraph.iter(w("instrText")):
            if it.text and it.text.lstrip().upper().startswith("INDEX"):
                return

        text = self._para_text(paragraph)
        if not text.strip():
            return

        self.stats[chapter_title]["words"] += len(text.split())
        new_runs = []

        # --- scripture (\f "b") ---
        seen = set()
        for ref in self.canon.find_references(text, self.allow_chapter_only):
            key = ref.dedupe_key()
            if key in seen:
                continue
            seen.add(key)
            new_runs.extend(self._make_xe_field(ref.entry_text(), "b"))
            self.stats[chapter_title]["scripture"] += 1

        # --- subject (\f "a") ---
        if self.vocab is not None:
            for entry in self.vocab.find_entries(text):
                if not self._subject_allowed(entry, chapter_title):
                    continue
                new_runs.extend(self._make_xe_field(entry.headword, "a"))
                self.stats[chapter_title]["subject"] += 1

        # Append all new field runs at the end of the paragraph (after the
        # existing text, before the paragraph mark) so they land on the
        # paragraph's page without disturbing any existing run.
        for run in new_runs:
            paragraph.append(run)

    def _subject_allowed(self, entry, chapter_title) -> bool:
        """
        Enforce a term's occurrence cap.  Returns True if a marker may be
        placed in the current paragraph for this entry, and records the use
        when it is allowed.  Caps count *paragraphs marked*, not raw mentions.
        """
        cap, scope = self.vocab.effective_cap(entry)
        if cap is None or scope == "paragraph":
            return True  # no document/chapter limit on this term
        if scope == "document":
            key = ("doc", entry.headword)
        else:  # "chapter": the chapter title makes the counter reset per chapter
            key = ("chap", chapter_title, entry.headword)
        if self._subject_counts[key] >= cap:
            return False
        self._subject_counts[key] += 1
        return True

    # -- step 3: make sure the document can DISPLAY the indexes --------------
    def _iter_field_instructions(self):
        """
        Yield the complete instruction text of every field in the document.

        A field's instruction may be split across several <w:instrText> runs
        (and fields can nest), so we walk every run in document order with a
        stack -- the same technique _strip_xe uses within one paragraph --
        and emit each field's concatenated instruction when its 'end'
        fldChar closes it.
        """
        stack = []
        for run in self.tree.iter(w("r")):
            fld = run.find(w("fldChar"))
            instr = run.find(w("instrText"))
            ftype = fld.get(w("fldCharType")) if fld is not None else None
            if ftype == "begin":
                stack.append("")
                continue
            if not stack:
                continue
            if instr is not None and instr.text:
                stack[-1] += instr.text
            if ftype == "end":
                yield stack.pop()

    def _has_index_field(self, flag: str) -> bool:
        """
        True if the document already contains an { INDEX \\f "<flag>" } field,
        i.e. a place where Word will actually RENDER the entries we mark.
        XE markers alone are invisible: without a matching INDEX field the
        finished document shows no index at all.
        """
        # Match  INDEX ... \f "a"  allowing single/double/no quotes around
        # the flag letter, since hand-inserted fields vary.
        pat = re.compile(r'\\f\s*["\u201c\']?' + re.escape(flag), re.IGNORECASE)
        for instr in self._iter_field_instructions():
            head = instr.lstrip()
            if head.upper().startswith("INDEX") and pat.search(instr):
                return True
        return False

    def _make_index_section(self, title: str, flag: str):
        """
        Build the paragraphs of one index section, ready to append to the
        document body:

            [page-break paragraph]
            [Heading1 paragraph:  e.g. "Scripture Index"]
            [paragraph holding the field  { INDEX \\f "b" \\c "2" }]

        The INDEX field is created 'dirty' (w:dirty="true") so Word offers to
        build it the first time the document is opened; pressing Ctrl+A, F9
        also builds it.  A visible placeholder run sits in the field's result
        slot so the section is not blank before the first update.
        """
        paragraphs = []

        # 1) A paragraph whose only run is a hard page break, so each index
        #    starts on a fresh page just like Word's own Insert Index does.
        p_break = etree.Element(w("p"))
        r_break = etree.SubElement(p_break, w("r"))
        br = etree.SubElement(r_break, w("br"))
        br.set(w("type"), "page")
        paragraphs.append(p_break)

        # 2) The section heading, styled Heading1 so it appears in the TOC.
        p_head = etree.Element(w("p"))
        ppr = etree.SubElement(p_head, w("pPr"))
        pstyle = etree.SubElement(ppr, w("pStyle"))
        pstyle.set(w("val"), "Heading1")
        r_head = etree.SubElement(p_head, w("r"))
        t_head = etree.SubElement(r_head, w("t"))
        t_head.text = title
        paragraphs.append(p_head)

        # 3) The INDEX field itself:  begin -> instruction -> separate ->
        #    placeholder result -> end.  \c "2" lays the index out in two
        #    columns; \f routes only the matching XE entries here.
        p_field = etree.Element(w("p"))

        r_begin = etree.SubElement(p_field, w("r"))
        fc_begin = etree.SubElement(r_begin, w("fldChar"))
        fc_begin.set(w("fldCharType"), "begin")
        fc_begin.set(w("dirty"), "true")   # ask Word to update on open

        r_instr = etree.SubElement(p_field, w("r"))
        it = etree.SubElement(r_instr, w("instrText"))
        it.set(XML_SPACE, "preserve")
        it.text = ' INDEX \\f "%s" \\c "2" ' % flag

        r_sep = etree.SubElement(p_field, w("r"))
        fc_sep = etree.SubElement(r_sep, w("fldChar"))
        fc_sep.set(w("fldCharType"), "separate")

        r_result = etree.SubElement(p_field, w("r"))
        t_result = etree.SubElement(r_result, w("t"))
        t_result.text = "(Press Ctrl+A then F9 in Word to build this index.)"

        r_end = etree.SubElement(p_field, w("r"))
        fc_end = etree.SubElement(r_end, w("fldChar"))
        fc_end.set(w("fldCharType"), "end")

        paragraphs.append(p_field)
        return paragraphs

    def _ensure_index_fields(self):
        """
        Append a Scripture and/or Subject index section at the end of the
        body for each flag that has no INDEX field anywhere in the document.
        Existing INDEX fields are always left exactly as they are.
        """
        body = self.tree.find(w("body"))
        if body is None:                     # malformed document; nothing to do
            return
        # Wanted sections, in the order they should appear at the back of the
        # book.  The Subject index is only wanted when a vocabulary is loaded.
        wanted = [("Scripture Index", "b")]
        if self.vocab is not None:
            wanted.append(("Subject Index", "a"))

        # New paragraphs must go BEFORE the final <w:sectPr> (the body-level
        # section properties element), otherwise the document is invalid.
        sect_pr = body.find(w("sectPr"))

        for title, flag in wanted:
            if self._has_index_field(flag):
                continue                     # document already displays this one
            for para in self._make_index_section(title, flag):
                if sect_pr is not None:
                    sect_pr.addprevious(para)
                else:
                    body.append(para)
            self.added_index_sections.append(title)

    # -- driver -------------------------------------------------------------
    def process(self, document_xml: bytes) -> bytes:
        """Strip + rebuild markers across the whole document, return new XML."""
        # Reset per-run state so repeated calls are fully independent.
        self.stats.clear()
        self._subject_counts.clear()
        self.added_index_sections = []
        # huge_tree lets lxml handle very large manuscripts without complaint.
        parser = etree.XMLParser(huge_tree=True)
        self.tree = etree.fromstring(document_xml, parser=parser)

        chapter_title = "(front matter)"
        for paragraph in self.tree.iter(w("p")):
            style = self._para_style(paragraph)
            if style == "Heading1":
                # Track the current chapter for the statistics report.
                title = self._para_text(paragraph).strip()
                if title:
                    chapter_title = title
            # Always strip first (idempotency), then re-tag.
            self._strip_xe(paragraph)
            self._tag_paragraph(paragraph, chapter_title)

        # After all markers are placed, make sure there is somewhere for Word
        # to actually render them: append any missing INDEX section(s).
        self._ensure_index_fields()

        return etree.tostring(
            self.tree, xml_declaration=True, encoding="UTF-8", standalone=True
        )

    def build_file(self, in_path: str, out_path: str):
        """Read in_path, rebuild markers, write out_path (a fresh .docx)."""
        with zipfile.ZipFile(in_path, "r") as zin:
            names = zin.namelist()
            document = zin.read("word/document.xml")
            new_document = self.process(document)

            # Write a new archive, copying every part except document.xml.
            tmp = out_path + ".tmp"
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for name in names:
                    if name == "word/document.xml":
                        zout.writestr(name, new_document)
                    else:
                        zout.writestr(name, zin.read(name))
        shutil.move(tmp, out_path)

    # -- reporting ----------------------------------------------------------
    def print_report(self):
        """Print a per-chapter coverage table to stdout."""
        print("%-46s %7s %8s %7s" % ("chapter", "subject", "scripture", "words"))
        print("-" * 72)
        tot_s = tot_v = 0
        for title, s in self.stats.items():
            flag = ""
            total = s["subject"] + s["scripture"]
            if s["words"] >= 200 and total == 0:
                flag = "  <== NO markers"
            print("%-46s %7d %8d %7d%s"
                  % (title[:46], s["subject"], s["scripture"], s["words"], flag))
            tot_s += s["subject"]
            tot_v += s["scripture"]
        print("-" * 72)
        print("%-46s %7d %8d" % ("TOTAL", tot_s, tot_v))


# ===========================================================================
# 5.  Seed a vocabulary file from terms already in the manuscript
# ===========================================================================
def extract_existing_subject_terms(in_path: str) -> "OrderedDict[str, list]":
    """
    Pull every distinct '\\f "a"' (subject) headword already present in the
    document and propose a starter trigger for each.  This gives you a
    vocabulary.json pre-populated with your existing controlled vocabulary
    instead of a blank file.
    """
    with zipfile.ZipFile(in_path, "r") as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    # Field codes can be split across runs, so flatten all instrText first.
    instr = " ".join(re.findall(r"<w:instrText[^>]*>([^<]*)</w:instrText>", xml))
    headwords = re.findall(r'XE "(.*?)" \\f "a"', instr)

    mapping = OrderedDict()
    for hw in headwords:
        if hw in mapping:
            continue
        # Propose a sensible trigger: the part before " (" or "," (so
        # "Ezekiel (prophet)" -> trigger "Ezekiel"; "Vaccine, Christ as"
        # -> trigger "Vaccine").  Review these by hand afterwards.
        trigger = re.split(r"\s*\(|,", hw)[0].strip()
        mapping[hw] = [trigger]
    return mapping


# ===========================================================================
# 6.  Command-line interface
# ===========================================================================
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Rebuild Scripture and Subject indexes in a Word manuscript.")
    sub = parser.add_subparsers(dest="command", required=True)

    # init-vocab ------------------------------------------------------------
    p_init = sub.add_parser(
        "init-vocab",
        help="Extract existing subject terms into a starter vocabulary.json")
    p_init.add_argument("docx", help="Input .docx manuscript")
    p_init.add_argument("-o", "--out", default="vocabulary.json",
                        help="Output JSON path (default: vocabulary.json)")

    # build -----------------------------------------------------------------
    p_build = sub.add_parser(
        "build", help="Rebuild all XE markers and write a new .docx")
    p_build.add_argument("docx", help="Input .docx manuscript")
    p_build.add_argument("-v", "--vocab", default=None,
                         help="vocabulary.json (omit to do scripture only)")
    p_build.add_argument("-o", "--out", required=True,
                         help="Output .docx path")
    p_build.add_argument("--no-chapter-only", action="store_true",
                         help="Ignore whole-chapter refs like 'Leviticus 23'")
    p_build.add_argument("--index-headings", action="store_true",
                         help="Also place markers inside heading paragraphs")
    p_build.add_argument("--subject-max", type=int, default=None,
                         help="Default cap on how many paragraphs may carry a "
                              "given subject term (within --subject-scope). "
                              "A term's own 'max' in the vocabulary overrides it.")
    p_build.add_argument("--subject-scope", default="paragraph",
                         choices=["paragraph", "chapter", "document"],
                         help="Bucket the default cap is measured in "
                              "(default: paragraph = no chapter/document limit).")

    # report ----------------------------------------------------------------
    p_report = sub.add_parser(
        "report", help="Show what WOULD be tagged, without writing a file")
    p_report.add_argument("docx", help="Input .docx manuscript")
    p_report.add_argument("-v", "--vocab", default=None,
                          help="vocabulary.json (omit to do scripture only)")
    p_report.add_argument("--no-chapter-only", action="store_true")
    p_report.add_argument("--index-headings", action="store_true")
    p_report.add_argument("--subject-max", type=int, default=None,
                          help="Default cap on paragraphs per subject term.")
    p_report.add_argument("--subject-scope", default="paragraph",
                          choices=["paragraph", "chapter", "document"],
                          help="Bucket the default cap is measured in.")

    args = parser.parse_args(argv)
    canon = BibleCanon()

    if args.command == "init-vocab":
        mapping = extract_existing_subject_terms(args.docx)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, ensure_ascii=False, indent=2)
        print("Wrote %d subject terms to %s" % (len(mapping), args.out))
        print("Review the triggers, then run:  build %s -v %s -o OUTPUT.docx"
              % (os.path.basename(args.docx), args.out))
        return 0

    # build / report share vocabulary loading
    vocab = (Vocabulary.load(
                args.vocab,
                default_max=getattr(args, "subject_max", None),
                default_scope=getattr(args, "subject_scope", "paragraph"))
             if args.vocab else None)
    builder = IndexBuilder(
        canon, vocab,
        allow_chapter_only=not args.no_chapter_only,
        index_headings=args.index_headings,
    )

    if args.command == "report":
        with zipfile.ZipFile(args.docx, "r") as z:
            builder.process(z.read("word/document.xml"))
        builder.print_report()
        return 0

    if args.command == "build":
        builder.build_file(args.docx, args.out)
        builder.print_report()
        print("\nWrote %s" % args.out)
        # Tell the user when the document had no INDEX field(s) and this run
        # created them -- previously such a document silently showed no index.
        if builder.added_index_sections:
            print("The document had no INDEX field for: %s."
                  % ", ".join(builder.added_index_sections))
            print("Added the missing section(s) at the end of the document.")
        print("Open it in Word, then press Ctrl+A and F9 to build/repaginate "
              "the indexes.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
