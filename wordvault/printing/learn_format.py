"""
learn_format.py — read a .docx and write a .wvfmt that prints like it.

Learning by example: the page size, margins (mirror margins
included), the Normal style's font/size/alignment/spacing, the
Heading styles, the Quote style, and a page-number footer are all
recorded inside every Word document — this module reads them out and
emits a WordVault print format, automating what was once done by
hand with a ruler and the styles dialog (the KDP 6x9 format was born
that way, measured from a real manuscript).

Dependency-free: raw zipfile + ElementTree, like the other docx
readers in this codebase.  What cannot be learned is left out, and
the emitted file says in its comments where it came from.

Two Word habits the learner sees through: theme fonts (styles that
say asciiTheme="minorHAnsi" while the real name, e.g. Aptos, lives
in theme1.xml) and direct formatting (font and size painted straight
onto the text, overriding a style sheet that still claims Times New
Roman 12 from some ancestral template — the body majority vote in
_body_majority learns what the words actually wear).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

#: Known page sizes by their twip dimensions (1 twip = 1/20 pt),
#: matched with tolerance — Word files round these slightly.
_PAGE_SIZES_TWIPS = {
    "Letter": (12240, 15840),
    "Legal": (12240, 20160),
    "A4": (11906, 16838),
    "A5": (8391, 11906),
    "B5": (9978, 14170),
    "6x9": (8640, 12960),
}

_ALIGN = {"both": "justify", "distribute": "justify", "center": "center",
          "right": "right", "end": "right", "left": "left",
          "start": "left"}


def _read(zf: zipfile.ZipFile, member: str):
    try:
        return ET.fromstring(zf.read(member))
    except (KeyError, ET.ParseError):
        return None


def _twips_to_in(value) -> float:
    return round(int(value) / 1440.0, 2)


def _theme_fonts(zf: zipfile.ZipFile) -> dict:
    """The document theme's actual font names, e.g. {"minor": "Aptos",
    "major": "Aptos Display"}.  Newer Word files rarely name fonts
    directly in styles.xml — they say asciiTheme="minorHAnsi" and the
    real name lives here, in word/theme/theme1.xml."""
    themes: dict = {}
    root = _read(zf, "word/theme/theme1.xml")
    if root is not None:
        for tag, key in ((f"{A}majorFont", "major"),
                         (f"{A}minorFont", "minor")):
            latin = root.find(f".//{tag}/{A}latin")
            if latin is not None and latin.get("typeface"):
                themes[key] = latin.get("typeface")
    return themes


def _font_name(rfonts, themes: dict) -> str | None:
    """The font an rFonts element means: a plain name if it gives one,
    else the theme font it points at (minorHAnsi -> the theme's minor
    font, and so on), else None."""
    if rfonts is None:
        return None
    plain = rfonts.get(f"{W}ascii")
    if plain:
        return plain
    theme_ref = (rfonts.get(f"{W}asciiTheme")
                 or rfonts.get(f"{W}hAnsiTheme") or "")
    if theme_ref.startswith("major"):
        return themes.get("major")
    if theme_ref.startswith("minor"):
        return themes.get("minor")
    return None


def _style_chain(styles_root, style_id: str):
    """A style and its basedOn ancestors, nearest first."""
    by_id = {}
    for style in styles_root.findall(f"{W}style"):
        by_id[style.get(f"{W}styleId")] = style
    chain, seen = [], set()
    while style_id and style_id not in seen and style_id in by_id:
        seen.add(style_id)
        style = by_id[style_id]
        chain.append(style)
        based = style.find(f"{W}basedOn")
        style_id = based.get(f"{W}val") if based is not None else None
    return chain


def _prop(chain, xpath: str, attribute: str | None = f"{W}val"):
    """First defined value of a property along a style chain."""
    for style in chain:
        el = style.find(xpath)
        if el is not None:
            return el.get(attribute) if attribute else el
    return None


def _style_spec(styles_root, style_id: str, defaults: dict,
                themes: dict | None = None) -> dict:
    """What one Word style says, as .wvfmt-ready values (None = not
    said anywhere, so the format file stays silent about it)."""
    chain = _style_chain(styles_root, style_id)
    if not chain:
        return {}
    spec: dict = {}

    font = _font_name(_prop(chain, f"{W}rPr/{W}rFonts", None),
                      themes or {})
    spec["font"] = font or defaults.get("font")
    size = _prop(chain, f"{W}rPr/{W}sz")
    if size:
        spec["size_pt"] = int(size) / 2.0
    elif defaults.get("size_pt"):
        spec["size_pt"] = defaults["size_pt"]
    bold_el = _prop(chain, f"{W}rPr/{W}b", None)
    if bold_el is not None:
        spec["bold"] = bold_el.get(f"{W}val", "1") not in ("0", "false")
    italic_el = _prop(chain, f"{W}rPr/{W}i", None)
    if italic_el is not None:
        spec["italic"] = italic_el.get(f"{W}val", "1") not in ("0", "false")
    align = _prop(chain, f"{W}pPr/{W}jc")
    if align in _ALIGN:
        spec["align"] = _ALIGN[align]

    spacing = _prop(chain, f"{W}pPr/{W}spacing", None)
    if spacing is not None:
        before = spacing.get(f"{W}before")
        after = spacing.get(f"{W}after")
        line = spacing.get(f"{W}line")
        rule = spacing.get(f"{W}lineRule", "auto")
        if before:
            spec["space_before_pt"] = round(int(before) / 20.0, 1)
        if after:
            spec["space_after_pt"] = round(int(after) / 20.0, 1)
        if line and rule == "auto":
            spec["line_spacing"] = round(int(line) / 240.0, 2)
        elif line and rule in ("exact", "atLeast"):
            # Word's "Exactly"/"At least" leading, in twips -> points.
            spec["line_height_pt"] = round(int(line) / 20.0, 1)

    indent = _prop(chain, f"{W}pPr/{W}ind", None)
    if indent is not None:
        first = indent.get(f"{W}firstLine")
        left = indent.get(f"{W}left")
        if first:
            spec["first_line_indent_mm"] = round(int(first) / 20.0 * 0.3528, 1)
        if left:
            spec["indent_mm"] = round(int(left) / 20.0 * 0.3528, 1)

    if _prop(chain, f"{W}pPr/{W}pageBreakBefore", None) is not None:
        spec["page_break_before"] = True
    return spec


def _body_majority(document, themes: dict) -> dict:
    """What the body text actually WEARS, as opposed to what the style
    sheet says it should wear.

    Word applies direct formatting (font and size painted straight
    onto the runs, spacing and alignment onto the paragraphs) OVER the
    styles — and real manuscripts are full of it: a document can say
    'Times New Roman 12' in its Normal style while every visible word
    is direct-formatted Aptos 11.  Learning by example must learn the
    look, so this walks every plain body paragraph (no paragraph style,
    or Normal), counts votes, and reports any value worn by a clear
    majority.  The caller lets these votes override the style sheet,
    which is exactly Word's own precedence rule."""
    font_votes: Counter = Counter()
    size_votes: Counter = Counter()
    total_runs = 0
    align_votes: Counter = Counter()
    spacing_votes: Counter = Counter()
    total_paras = 0

    for p in document.iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        pstyle = ppr.find(f"{W}pStyle") if ppr is not None else None
        style_id = pstyle.get(f"{W}val") if pstyle is not None else None
        if style_id not in (None, "Normal"):
            continue                    # headings, lists, TOC: not body
        if not "".join(t.text or "" for t in p.iter(f"{W}t")).strip():
            continue                    # empty paragraphs carry no vote
        total_paras += 1
        if ppr is not None:
            jc = ppr.find(f"{W}jc")
            align_votes[jc.get(f"{W}val") if jc is not None else None] += 1
            spacing = ppr.find(f"{W}spacing")
            spacing_votes[
                tuple(sorted(spacing.attrib.items()))
                if spacing is not None else None] += 1
        else:
            align_votes[None] += 1
            spacing_votes[None] += 1
        for r in p.findall(f"{W}r"):
            text = r.find(f"{W}t")
            if text is None or not (text.text or "").strip():
                continue
            total_runs += 1
            rpr = r.find(f"{W}rPr")
            font = _font_name(
                rpr.find(f"{W}rFonts") if rpr is not None else None, themes)
            font_votes[font] += 1
            sz = rpr.find(f"{W}sz") if rpr is not None else None
            size_votes[sz.get(f"{W}val") if sz is not None else None] += 1

    def winner(votes: Counter, total: int):
        """The value worn by more than half the voters — None both for
        'no majority' and for 'the majority wears nothing direct'."""
        if not votes or total == 0:
            return None
        value, count = votes.most_common(1)[0]
        return value if value is not None and count * 2 > total else None

    worn: dict = {}
    font = winner(font_votes, total_runs)
    if font:
        worn["font"] = font
    size = winner(size_votes, total_runs)
    if size:
        worn["size_pt"] = int(size) / 2.0
    align = winner(align_votes, total_paras)
    if align in _ALIGN:
        worn["align"] = _ALIGN[align]
    spacing = winner(spacing_votes, total_paras)
    if spacing:
        attrs = dict(spacing)
        before = attrs.get(f"{W}before")
        after = attrs.get(f"{W}after")
        line = attrs.get(f"{W}line")
        rule = attrs.get(f"{W}lineRule", "auto")
        if before:
            worn["space_before_pt"] = round(int(before) / 20.0, 1)
        if after:
            worn["space_after_pt"] = round(int(after) / 20.0, 1)
        if line and rule == "auto":
            worn["line_spacing"] = round(int(line) / 240.0, 2)
    return worn


def _footer_wants_page_numbers(zf: zipfile.ZipFile) -> str | None:
    """'{page}' / '{page} of {pages}' when a footer carries Word's
    PAGE (and NUMPAGES) field — the sign this design numbers its
    pages; None when no footer does."""
    for member in zf.namelist():
        if not re.match(r"word/footer\d*\.xml$", member):
            continue
        root = _read(zf, member)
        if root is None:
            continue
        instructions = " ".join(
            (el.text or "") for el in root.iter(f"{W}instrText"))
        if re.search(r"\bPAGE\b", instructions):
            if re.search(r"\bNUMPAGES\b", instructions):
                return "{page} of {pages}"
            return "{page}"
    return None


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace('"', '\\"') + '"'


def _emit_section(lines: list, header: str, spec: dict, keys) -> None:
    said = {k: spec[k] for k in keys if spec.get(k) is not None}
    if said:
        lines.append(f"[{header}]")
        for key, value in said.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")


def learn_format(docx_path: str | Path, name: str) -> str:
    """Read `docx_path` and return .wvfmt TOML that prints like it.
    Raises OSError/ValueError with a plain message on unreadable
    files.  The caller validates the result through load_format
    before saving — the learner must never emit an invalid file."""
    docx_path = Path(docx_path)
    with zipfile.ZipFile(docx_path) as zf:
        document = _read(zf, "word/document.xml")
        styles = _read(zf, "word/styles.xml")
        settings = _read(zf, "word/settings.xml")
        if document is None or styles is None:
            raise ValueError(f"{docx_path.name} is not a readable .docx")

        # --- page geometry (the LAST sectPr governs the document) ---
        sects = document.findall(f".//{W}sectPr")
        sect = sects[-1] if sects else None
        page_size = "Letter"
        margins: dict = {}
        if sect is not None:
            pg = sect.find(f"{W}pgSz")
            if pg is not None:
                w = int(pg.get(f"{W}w", 12240))
                h = int(pg.get(f"{W}h", 15840))
                for known, (kw, kh) in _PAGE_SIZES_TWIPS.items():
                    if abs(w - kw) <= 60 and abs(h - kh) <= 60:
                        page_size = known
                        break
            mar = sect.find(f"{W}pgMar")
            if mar is not None:
                for side in ("top", "bottom", "left", "right", "gutter"):
                    value = mar.get(f"{W}{side}")
                    if value is not None:
                        margins[side] = _twips_to_in(value)
        mirrored = (settings is not None
                    and settings.find(f"{W}mirrorMargins") is not None)

        # --- styles ---
        themes = _theme_fonts(zf)
        defaults: dict = {}
        doc_defaults = styles.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
        if doc_defaults is not None:
            font = _font_name(doc_defaults.find(f"{W}rFonts"), themes)
            if font:
                defaults["font"] = font
            size = doc_defaults.find(f"{W}sz")
            if size is not None:
                defaults["size_pt"] = int(size.get(f"{W}val")) / 2.0

        # Paragraph DEFAULTS too: modern Word keeps its standard
        # paragraph spacing in docDefaults/pPrDefault (not in the
        # Normal style), and a learned format that misses it prints
        # paragraphs with no gap at all — the "no full line between
        # paragraphs" report.
        p_defaults = styles.find(
            f"{W}docDefaults/{W}pPrDefault/{W}pPr/{W}spacing")
        if p_defaults is not None:
            after = p_defaults.get(f"{W}after")
            line = p_defaults.get(f"{W}line")
            rule = p_defaults.get(f"{W}lineRule", "auto")
            if after:
                defaults["space_after_pt"] = round(int(after) / 20.0, 1)
            if line and rule == "auto":
                defaults["line_spacing"] = round(int(line) / 240.0, 2)

        body = _style_spec(styles, "Normal", defaults, themes)
        for key in ("space_after_pt", "line_spacing"):
            if key not in body and key in defaults:
                body[key] = defaults[key]
        # The style sheet is only the undercoat: when most of the real
        # body text is direct-formatted (very common — a document whose
        # Normal style says Times New Roman 12 while every visible word
        # wears Aptos 11), the paint wins, as it does in Word itself.
        body.update(_body_majority(document, themes))
        body.setdefault("font", "Georgia")
        body.setdefault("size_pt", 11)
        headings = {n: _style_spec(styles, f"Heading{n}", {}, themes)
                    for n in range(1, 7)}
        quote = _style_spec(styles, "Quote", {}, themes)

        footer_template = _footer_wants_page_numbers(zf)

    # --- emit ---
    lines = [
        f"# {name} - learned from {docx_path.name} "
        f"on {date.today().isoformat()}.",
        "# WordVault read the page, margins, and styles out of that",
        "# Word document and wrote this format to print like it.",
        "# Edit freely: this is YOUR copy (in ~/.wordvault/formats).",
        "# The full specification is in docs/format-file.md.",
        "",
        "[format]",
        f"name = {_toml_value(name)}",
        "",
        "[page]",
        f"size = {_toml_value(page_size)}",
        "",
    ]
    if margins:
        lines.append("[page.margins]")
        lines.append('unit = "in"')
        lines.append(f"top = {_toml_value(margins.get('top', 1.0))}")
        lines.append(f"bottom = {_toml_value(margins.get('bottom', 1.0))}")
        if mirrored:
            lines.append(
                f"inside = {_toml_value(margins.get('left', 1.0))}")
            lines.append(
                f"outside = {_toml_value(margins.get('right', 1.0))}")
            if margins.get("gutter"):
                lines.append(f"gutter = {_toml_value(margins['gutter'])}")
        else:
            lines.append(f"left = {_toml_value(margins.get('left', 1.0))}")
            lines.append(
                f"right = {_toml_value(margins.get('right', 1.0))}")
        lines.append("")

    _emit_section(lines, "body", body,
                  ("font", "size_pt", "align", "line_spacing",
                   "line_height_pt", "first_line_indent_mm",
                   "space_before_pt", "space_after_pt"))
    for n in range(1, 7):
        _emit_section(lines, f"heading{n}", headings[n],
                      ("size_pt", "bold", "italic", "align",
                       "space_before_pt", "space_after_pt",
                       "page_break_before"))
    _emit_section(lines, "quote", quote,
                  ("italic", "indent_mm", "size_pt",
                   "space_before_pt", "space_after_pt"))
    if footer_template:
        lines.append("[footer]")
        lines.append(f"center = {_toml_value(footer_template)}")
        lines.append("")

    return "\n".join(lines)
