"""
format_file.py — loading and validating .wvfmt print-format files.

A .wvfmt is a small TOML file describing how a printed page should look:
page size and margins, then one style section per structural element
(body, heading1..heading6, quote, list).  The full contract lives in
docs/format-file.md — the future Formatter app writes these files by
guided choices; WordVault only reads them.

This module is deliberately Qt-FREE so it can be tested headless and
reused by other tools (the Formatter itself, a format validator, ...).
Unknown sections or keys are ERRORS, not silence: a typo in a format
file should be caught at load time, never discovered as a mysteriously
plain paragraph three pages into a printout.
"""

from __future__ import annotations

import re
import shutil

try:
    import tomllib                    # Python 3.11+
except ImportError:                   # 3.10: the identical 'tomli' package
    import tomli as tomllib           # (pip install tomli)

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional, Union

#: Where the author's format files live; ensure_default_formats() seeds
#: it with the starters shipped in the repository's formats/ folder.
FORMATS_DIR = Path.home() / ".wordvault" / "formats"

#: Shipped starters (repo_root/formats), relative to this file.
_SHIPPED_DIR = Path(__file__).resolve().parents[2] / "formats"

#: Page sizes WordVault knows how to ask the printer for.
PAGE_SIZES = ("Letter", "Legal", "A4", "A5", "B5")

_STYLE_SECTIONS = (
    "body", "heading1", "heading2", "heading3",
    "heading4", "heading5", "heading6", "quote", "list",
)


class FormatError(ValueError):
    """A .wvfmt file is invalid; the message says exactly what and where."""


_IN_TO_MM = 25.4


@dataclass
class Margins:
    """
    Page margins in millimetres.  Two modes, exactly as in Word's Page
    Setup:

      normal    — fixed left/right on every page;
      mirrored  — inside/outside instead: odd (right-hand) pages put the
                  inside margin on their LEFT edge, even pages on their
                  RIGHT — the spine side always gets the binding room.
                  `gutter` is extra binding space added to the inside.
    """

    top: float = 25.0
    bottom: float = 25.0
    left: float = 20.0
    right: float = 20.0
    mirrored: bool = False
    inside: float = 0.0
    outside: float = 0.0
    gutter: float = 0.0

    def for_page(self, index: int) -> tuple[float, float, float, float]:
        """(top, right, bottom, left) in mm for the 0-based page index.
        Index 0 prints as page 1 — a right-hand page in a book."""
        if not self.mirrored:
            return (self.top, self.right, self.bottom, self.left)
        spine = self.inside + self.gutter
        if index % 2 == 0:                       # right-hand page
            return (self.top, self.outside, self.bottom, spine)
        return (self.top, spine, self.bottom, self.outside)

    def text_width_deduction(self) -> float:
        """Horizontal margin total (constant across pages, mm)."""
        if self.mirrored:
            return self.inside + self.gutter + self.outside
        return self.left + self.right


@dataclass
class StyleSpec:
    """How one structural element prints.  Unset values (None) inherit
    from the body style; the body itself falls back to the defaults here."""

    font: Optional[str] = None
    size_pt: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    align: Optional[str] = None            # left | right | center | justify
    line_spacing: Optional[float] = None   # multiple, e.g. 1.4
    first_line_indent_mm: Optional[float] = None
    indent_mm: Optional[float] = None      # left margin of the whole block
    space_before_pt: Optional[float] = None
    space_after_pt: Optional[float] = None
    page_break_before: Optional[bool] = None

    def merged_over(self, base: "StyleSpec") -> "StyleSpec":
        """This style with unset values filled from `base`."""
        merged = StyleSpec()
        for f in fields(StyleSpec):
            mine = getattr(self, f.name)
            setattr(merged, f.name,
                    mine if mine is not None else getattr(base, f.name))
        return merged


#: Template variables, by where they make sense.  {page}/{pages} exist
#: only while printing a particular page — page furniture territory.
_DOC_VARS = {"title", "author", "date"}
_PAGE_VARS = _DOC_VARS | {"page", "pages"}

_VAR_RE = re.compile(r"\{(\w+)\}")


def _check_template(template: str, allowed: set, where: str, path: Path) -> None:
    unknown = set(_VAR_RE.findall(template)) - allowed
    if unknown:
        raise FormatError(
            f"{path.name}: unknown variable(s) "
            f"{sorted('{' + v + '}' for v in unknown)} in {where} "
            f"(allowed: {sorted('{' + v + '}' for v in allowed)})"
        )


@dataclass
class FurnitureSpec:
    """A page header or footer: three template slots aligned to the text
    column's left edge, centre, and right edge, drawn on every page."""

    left: str = ""
    center: str = ""
    right: str = ""
    font: Optional[str] = None      # None: the body font
    size_pt: float = 9.0
    bold: bool = False
    italic: bool = False

    def wanted(self) -> bool:
        return bool(self.left or self.center or self.right)


#: The ultimate fallbacks — a plain, readable page.
_BODY_DEFAULTS = StyleSpec(
    font="Georgia", size_pt=11.0, bold=False, italic=False, align="left",
    line_spacing=1.3, first_line_indent_mm=0.0, indent_mm=0.0,
    space_before_pt=0.0, space_after_pt=6.0, page_break_before=False,
)


@dataclass
class PrintFormat:
    """One loaded .wvfmt: page geometry plus resolved element styles."""

    name: str
    path: Optional[Path] = None
    page_size: str = "Letter"
    margins: Margins = field(default_factory=Margins)
    body: StyleSpec = field(default_factory=lambda: _BODY_DEFAULTS)
    headings: dict = field(default_factory=dict)   # level -> StyleSpec
    quote: StyleSpec = field(default_factory=StyleSpec)
    list_style: StyleSpec = field(default_factory=StyleSpec)
    header: FurnitureSpec = field(default_factory=FurnitureSpec)
    footer: FurnitureSpec = field(default_factory=FurnitureSpec)
    byline_text: str = ""                          # "" = no byline
    byline_style: StyleSpec = field(default_factory=StyleSpec)

    def needs_manual_pagination(self) -> bool:
        """Mirrored margins and page furniture both require WordVault to
        paginate and paint each page itself."""
        return (self.margins.mirrored or self.header.wanted()
                or self.footer.wanted())

    def style_for_byline(self) -> StyleSpec:
        return self.byline_style.merged_over(self.body)

    def style_for_heading(self, level: int) -> StyleSpec:
        """The effective style of a heading level: its own section if
        given, else the nearest SHALLOWER defined heading, else a bolder,
        larger body — so a format defining only heading1 still prints
        deeper headings sensibly."""
        for lvl in range(level, 0, -1):
            if lvl in self.headings:
                return self.headings[lvl].merged_over(self.body)
        derived = StyleSpec(bold=True,
                            size_pt=(self.body.size_pt or 11.0) * 1.2)
        return derived.merged_over(self.body)

    def style_for_quote(self) -> StyleSpec:
        return self.quote.merged_over(self.body)

    def style_for_list(self) -> StyleSpec:
        return self.list_style.merged_over(self.body)


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------

_STYLE_KEYS = {f.name for f in fields(StyleSpec)}


def _parse_style(section: str, data: dict, path: Path) -> StyleSpec:
    unknown = set(data) - _STYLE_KEYS
    if unknown:
        raise FormatError(
            f"{path.name}: unknown key(s) {sorted(unknown)} in [{section}] "
            f"(allowed: {sorted(_STYLE_KEYS)})"
        )
    align = data.get("align")
    if align is not None and align not in ("left", "right", "center", "justify"):
        raise FormatError(
            f"{path.name}: [{section}] align must be left/right/center/justify"
        )
    kwargs = {}
    for key, value in data.items():
        if key in ("bold", "italic", "page_break_before"):
            if not isinstance(value, bool):
                raise FormatError(f"{path.name}: [{section}] {key} must be true/false")
            kwargs[key] = value
        elif key in ("font", "align"):
            kwargs[key] = str(value)
        else:
            try:
                kwargs[key] = float(value)
            except (TypeError, ValueError):
                raise FormatError(
                    f"{path.name}: [{section}] {key} must be a number"
                ) from None
    return StyleSpec(**kwargs)


def _parse_margins(data: dict, path: Path) -> Margins:
    """
    The Word-shaped [page.margins] table.  Two mutually exclusive modes:
      normal    top/bottom/left/right
      mirrored  top/bottom/inside/outside (+ optional gutter)
    `unit` is "mm" (default) or "in"; every value converts to mm.
    """
    if not isinstance(data, dict):
        raise FormatError(f"{path.name}: [page.margins] must be a table")
    allowed = {"unit", "top", "bottom", "left", "right",
               "inside", "outside", "gutter"}
    unknown = set(data) - allowed
    if unknown:
        raise FormatError(
            f"{path.name}: unknown key(s) {sorted(unknown)} in [page.margins]"
        )
    unit = data.get("unit", "mm")
    if unit not in ("mm", "in"):
        raise FormatError(f"{path.name}: [page.margins] unit must be 'mm' or 'in'")
    factor = _IN_TO_MM if unit == "in" else 1.0

    def value(key, default=None):
        raw = data.get(key, default)
        if raw is None:
            return None
        if not isinstance(raw, (int, float)) or raw < 0:
            raise FormatError(
                f"{path.name}: [page.margins] {key} must be a non-negative number"
            )
        return float(raw) * factor

    has_lr = "left" in data or "right" in data
    has_io = "inside" in data or "outside" in data
    if has_lr and has_io:
        raise FormatError(
            f"{path.name}: [page.margins] use left/right OR inside/outside "
            f"(mirror margins), not both"
        )
    if "gutter" in data and not has_io:
        raise FormatError(
            f"{path.name}: [page.margins] gutter only applies with "
            f"inside/outside (mirror margins)"
        )

    top = value("top", 25.0 / factor)
    bottom = value("bottom", 25.0 / factor)
    if has_io:
        return Margins(
            top=top, bottom=bottom, mirrored=True,
            inside=value("inside", 25.0 / factor),
            outside=value("outside", 20.0 / factor),
            gutter=value("gutter", 0.0) or 0.0,
        )
    return Margins(
        top=top, bottom=bottom,
        left=value("left", 20.0 / factor),
        right=value("right", 20.0 / factor),
    )


def _parse_furniture(section: str, data: dict, path: Path) -> FurnitureSpec:
    """[header] / [footer]: template slots plus a small type face."""
    allowed = {"left", "center", "right", "font", "size_pt", "bold", "italic"}
    unknown = set(data) - allowed
    if unknown:
        raise FormatError(
            f"{path.name}: unknown key(s) {sorted(unknown)} in [{section}]"
        )
    spec = FurnitureSpec()
    for slot in ("left", "center", "right"):
        template = str(data.get(slot, ""))
        _check_template(template, _PAGE_VARS, f"[{section}] {slot}", path)
        setattr(spec, slot, template)
    if "font" in data:
        spec.font = str(data["font"])
    if "size_pt" in data:
        try:
            spec.size_pt = float(data["size_pt"])
        except (TypeError, ValueError):
            raise FormatError(
                f"{path.name}: [{section}] size_pt must be a number"
            ) from None
    for key in ("bold", "italic"):
        if key in data:
            if not isinstance(data[key], bool):
                raise FormatError(
                    f"{path.name}: [{section}] {key} must be true/false"
                )
            setattr(spec, key, data[key])
    return spec


def load_format(path: Union[str, Path]) -> PrintFormat:
    """Load and validate one .wvfmt file (raises FormatError with a
    plain-language message on any problem)."""
    path = Path(path)
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise FormatError(f"{path.name}: not valid TOML — {exc}") from None

    allowed_sections = {"format", "page", "header", "footer", "byline",
                        *_STYLE_SECTIONS}
    unknown = set(data) - allowed_sections
    if unknown:
        raise FormatError(
            f"{path.name}: unknown section(s) {sorted(unknown)} "
            f"(allowed: {sorted(allowed_sections)})"
        )

    meta = data.get("format", {})
    name = str(meta.get("name", path.stem))

    fmt = PrintFormat(name=name, path=path)

    page = data.get("page", {})
    unknown = set(page) - {"size", "margins_mm", "margins"}
    if unknown:
        raise FormatError(f"{path.name}: unknown key(s) {sorted(unknown)} in [page]")
    size = page.get("size", "Letter")
    if size not in PAGE_SIZES:
        raise FormatError(
            f"{path.name}: page size '{size}' not supported "
            f"(choose from {', '.join(PAGE_SIZES)})"
        )
    fmt.page_size = size
    if "margins" in page and "margins_mm" in page:
        raise FormatError(
            f"{path.name}: give EITHER [page.margins] OR margins_mm, not both"
        )
    if "margins" in page:
        fmt.margins = _parse_margins(page["margins"], path)
    elif "margins_mm" in page:
        # Legacy shorthand: four numbers, CSS order, always millimetres.
        margins = page["margins_mm"]
        if (not isinstance(margins, list) or len(margins) != 4
                or not all(isinstance(m, (int, float)) for m in margins)):
            raise FormatError(
                f"{path.name}: margins_mm must be four numbers "
                f"[top, right, bottom, left]"
            )
        top, right, bottom, left = (float(m) for m in margins)
        fmt.margins = Margins(top=top, right=right, bottom=bottom, left=left)

    if "body" in data:
        fmt.body = _parse_style("body", data["body"], path).merged_over(
            _BODY_DEFAULTS
        )
    for level in range(1, 7):
        section = f"heading{level}"
        if section in data:
            fmt.headings[level] = _parse_style(section, data[section], path)
    if "quote" in data:
        fmt.quote = _parse_style("quote", data["quote"], path)
    if "list" in data:
        fmt.list_style = _parse_style("list", data["list"], path)

    if "header" in data:
        fmt.header = _parse_furniture("header", data["header"], path)
    if "footer" in data:
        fmt.footer = _parse_furniture("footer", data["footer"], path)
    if "byline" in data:
        byline = dict(data["byline"])
        template = str(byline.pop("text", ""))
        if not template:
            raise FormatError(f"{path.name}: [byline] needs a 'text' template")
        # {page}/{pages} make no sense in a byline — it prints once.
        _check_template(template, _DOC_VARS, "[byline] text", path)
        fmt.byline_text = template
        fmt.byline_style = _parse_style("byline", byline, path)
    return fmt


# ---------------------------------------------------------------------------
# The author's format collection
# ---------------------------------------------------------------------------

def ensure_default_formats() -> Path:
    """
    Create ~/.wordvault/formats on first use, seeded with the starter
    formats shipped in the repository — and keep UNMODIFIED copies
    up to date when the shipped masters improve.

    The rule that makes this safe: a sidecar record (.seeded.json)
    remembers the hash each file had when seeded.  If the author's copy
    still matches that hash (never edited), a newer master replaces it;
    the moment the author edits a copy, it is theirs for good.
    """
    import hashlib
    import json

    FORMATS_DIR.mkdir(parents=True, exist_ok=True)
    record_path = FORMATS_DIR / ".seeded.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    changed = False
    if _SHIPPED_DIR.is_dir():
        for shipped in sorted(_SHIPPED_DIR.glob("*.wvfmt")):
            target = FORMATS_DIR / shipped.name
            shipped_hash = digest(shipped)
            if not target.exists():
                shutil.copy2(shipped, target)          # first seeding
                record[shipped.name] = shipped_hash
                changed = True
                continue
            target_hash = digest(target)
            if (target_hash == record.get(shipped.name)
                    and target_hash != shipped_hash):
                shutil.copy2(shipped, target)          # untouched: upgrade
                record[shipped.name] = shipped_hash
                changed = True
            elif (target_hash == shipped_hash
                    and record.get(shipped.name) != shipped_hash):
                # The copy matches the current master (fresh manual copy,
                # or seeded before record-keeping existed): adopt it, so
                # future master improvements auto-upgrade it.
                record[shipped.name] = shipped_hash
                changed = True
    if changed:
        try:
            record_path.write_text(json.dumps(record, indent=1),
                                   encoding="utf-8")
        except OSError:
            pass
    return FORMATS_DIR


def list_formats() -> list[PrintFormat]:
    """Every VALID format in the author's collection, sorted by name.
    Invalid files are skipped here (the print chooser is no place for a
    stack trace); a validator tool can lint them individually."""
    ensure_default_formats()
    formats = []
    for path in sorted(FORMATS_DIR.glob("*.wvfmt")):
        try:
            formats.append(load_format(path))
        except FormatError:
            continue
    formats.sort(key=lambda f: f.name.lower())
    return formats
