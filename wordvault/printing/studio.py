"""
studio.py — the Format Studio: edit a .wvfmt beside a live preview.

A tall, thin column of the format's settings runs down the left; the
printed pages fill the right.  Change any dial and, after a
heartbeat's pause, the preview repaints — margins, fonts, leading,
paragraph gaps, headers, all tuned BY EYE with no paper spent.  This
is the format system's promise made visible: the document stays plain
text while its costume is fitted in front of a mirror.

Design notes:
* The column is generated from the same StyleSpec vocabulary the
  format files use, one section after another (page, body, headings,
  quote, header/footer, byline).  A spin at zero / an empty field
  means "not set" and is simply omitted when the file is written.
* Every change is validated through load_format before it reaches the
  preview — the studio can never show (or save) an invalid format.
  Errors appear in the status line; the preview keeps the last good
  look.
* Save regenerates the file in clean standard form (the same emitter
  discipline as learn_format).  Hand-written comments are replaced by
  the standard header; the settings themselves all survive.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from wordvault.printing.format_file import (
    PAGE_SIZES,
    FormatError,
    load_format,
)
from wordvault.printing.learn_format import _emit_section, _toml_value

#: The dials each text style offers, in file order.  (name, kind,
#: label, maximum) — kind decides the widget.
_STYLE_DIALS = (
    ("font", "font", "Font", None),
    ("size_pt", "spin", "Size (pt)", 96),
    ("bold", "check", "Bold", None),
    ("italic", "check", "Italic", None),
    ("align", "align", "Align", None),
    ("line_spacing", "spin", "Line spacing (×)", 4),
    ("line_height_pt", "spin", "Exact line height (pt)", 120),
    ("first_line_indent_mm", "spin", "First-line indent (mm)", 40),
    ("indent_mm", "spin", "Block indent (mm)", 60),
    ("space_before_pt", "spin", "Space before (pt)", 96),
    ("space_after_pt", "spin", "Space after (pt)", 96),
    ("page_break_before", "check", "Page break before", None),
)

_STYLE_SECTIONS = ("body", "heading1", "heading2", "heading3", "quote")

_SAMPLE = (
    "# A Sample Heading\n\n"
    "## A Second-Level Heading\n\n"
    + ("This is body text for fitting the format by eye: the quick "
       "brown fox jumps over the lazy dog, and every letter pair "
       "shows its spacing. " * 3 + "\n\n") * 6
    + "> A quoted passage sits here, indented and italic if the "
    "format says so.\n\n"
    + ("More body text follows the quotation so the paragraph gap "
       "and the leading can both be judged. " * 3 + "\n\n") * 6
)


class FormatStudio(QDialog):
    """Edit one .wvfmt beside a live print preview."""

    def __init__(self, path: Path, sample_text: str = "",
                 title: str = "Sample Document", author: str = "",
                 parent=None):
        super().__init__(parent)
        self._path = Path(path)
        self._text = sample_text or _SAMPLE
        self._doc_title = title
        self._author = author
        self._fmt = load_format(self._path)   # must be valid to open
        self._building = True                 # silence changes while built

        self.setWindowTitle(f"Format Studio — {self._fmt.name}")
        self.resize(1050, 720)

        root = QHBoxLayout(self)

        # ---- the tall thin settings column --------------------------
        column = QWidget(self)
        form = QVBoxLayout(column)
        form.setSpacing(3)
        self._controls: dict = {}     # (section, key) -> widget
        self._build_column(form)
        form.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidget(column)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(280)
        root.addWidget(scroll)

        # ---- the live preview ---------------------------------------
        right = QVBoxLayout()
        from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewWidget

        self._printer = QPrinter()
        self._preview = QPrintPreviewWidget(self._printer, self)
        self._preview.paintRequested.connect(self._paint_preview)
        right.addWidget(self._preview, stretch=1)

        bottom = QHBoxLayout()
        self._status = QLabel("", self)
        bottom.addWidget(self._status, stretch=1)
        save_btn = QPushButton("&Save Format", self)
        save_btn.setToolTip(f"Write these settings to {self._path.name}")
        save_btn.clicked.connect(self._save)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(save_btn)
        bottom.addWidget(close_btn)
        right.addLayout(bottom)
        root.addLayout(right, stretch=1)

        # Debounce: a change repaints the preview after a heartbeat's
        # pause, so typing a margin doesn't re-render per keystroke.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._refresh)

        self._building = False
        self._apply_format_to_preview()

    # ------------------------------------------------- column building --

    def _heading(self, form, text: str) -> None:
        label = QLabel(f"<b>{text}</b>", self)
        label.setContentsMargins(0, 8, 0, 2)
        form.addWidget(label)

    def _row(self, form, label: str, widget) -> None:
        row = QHBoxLayout()
        lab = QLabel(label, self)
        lab.setMinimumWidth(120)
        row.addWidget(lab)
        row.addWidget(widget, stretch=1)
        form.addLayout(row)

    def _spin(self, value, maximum, decimals=2) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(0.0, float(maximum))
        spin.setDecimals(decimals)
        spin.setSingleStep(0.5)
        spin.setSpecialValueText("—")          # zero shows as "not set"
        spin.setValue(float(value or 0.0))
        spin.valueChanged.connect(self._changed)
        return spin

    def _build_column(self, form) -> None:
        fmt = self._fmt

        self._heading(form, "Page")
        size_combo = QComboBox(self)
        size_combo.addItems(sorted(PAGE_SIZES))
        size_combo.setCurrentText(fmt.page_size)
        size_combo.currentTextChanged.connect(self._changed)
        self._controls[("page", "size")] = size_combo
        self._row(form, "Paper", size_combo)
        duplex = QCheckBox("Two-sided (duplex)", self)
        duplex.setChecked(bool(fmt.duplex))
        duplex.stateChanged.connect(self._changed)
        self._controls[("page", "duplex")] = duplex
        form.addWidget(duplex)

        self._heading(form, "Margins (mm)")
        margins = fmt.margins
        for key, value in (("top", margins.top), ("bottom", margins.bottom),
                           ("left", margins.for_page(0)[3]),
                           ("right", margins.for_page(0)[1])):
            spin = self._spin(value, 80)
            self._controls[("margins", key)] = spin
            self._row(form, key.capitalize(), spin)

        for section in _STYLE_SECTIONS:
            spec = self._spec_for(section)
            self._heading(form, section.capitalize())
            for key, kind, label, maximum in _STYLE_DIALS:
                value = getattr(spec, key, None) if spec else None
                if kind == "font":
                    combo = QFontComboBox(self)
                    combo.setEditable(True)
                    combo.setCurrentText(value or "")
                    combo.currentTextChanged.connect(self._changed)
                    widget = combo
                elif kind == "align":
                    combo = QComboBox(self)
                    combo.addItems(["", "left", "right", "center",
                                    "justify"])
                    combo.setCurrentText(value or "")
                    combo.currentTextChanged.connect(self._changed)
                    widget = combo
                elif kind == "check":
                    box = QCheckBox("", self)
                    box.setChecked(bool(value))
                    box.stateChanged.connect(self._changed)
                    widget = box
                else:
                    widget = self._spin(value, maximum)
                self._controls[(section, key)] = widget
                self._row(form, label, widget)

        # Header, footer, byline: the templates ({page}, {pages},
        # {title}, {author}, {date}) and their small type size.
        for part in ("header", "footer"):
            self._heading(form, part.capitalize())
            spec = getattr(fmt, part)
            for slot in ("left", "center", "right"):
                edit = QLineEdit(getattr(spec, slot, "") or "", self)
                edit.setPlaceholderText("{page} of {pages}, {title}…")
                edit.textChanged.connect(self._changed)
                self._controls[(part, slot)] = edit
                self._row(form, slot.capitalize(), edit)
            spin = self._spin(getattr(spec, "size_pt", 0) or 0, 24)
            self._controls[(part, "size_pt")] = spin
            self._row(form, "Size (pt)", spin)

        self._heading(form, "Byline")
        byline = QLineEdit(self._fmt.byline_text or "", self)
        byline.setPlaceholderText("by {author} — {date}")
        byline.textChanged.connect(self._changed)
        self._controls[("byline", "text")] = byline
        self._row(form, "Text", byline)

    def _spec_for(self, section: str):
        """The RAW spec as the file wrote it (not merged over body —
        merging would bake body values into every heading on save)."""
        if section == "body":
            return self._fmt.body
        if section == "quote":
            return self._fmt.quote
        return self._fmt.headings.get(int(section[-1]))

    # ----------------------------------------------------- live update --

    def _changed(self, *_a) -> None:
        if not self._building:
            self._debounce.start()

    def _refresh(self) -> None:
        """Assemble → validate → repaint (or report and keep the last
        good look)."""
        text = self.serialized()
        try:
            probe = self._path.with_suffix(".studio-probe")
            probe.write_text(text, encoding="utf-8")
            try:
                self._fmt = load_format(probe)
            finally:
                probe.unlink(missing_ok=True)
        except FormatError as error:
            self._status.setText(f"<font color='#b33'>{error}</font>")
            return
        self._status.setText("")
        self._apply_format_to_preview()

    def _apply_format_to_preview(self) -> None:
        from wordvault.printing.renderer import page_setup_for_preview

        page_setup_for_preview(self._printer, self._fmt)
        self._preview.updatePreview()

    def _paint_preview(self, printer) -> None:
        from wordvault.printing.renderer import print_styled

        print_styled(printer, self._text, self._fmt,
                     title=self._doc_title, author=self._author,
                     configure=False)

    # ------------------------------------------------------- serialize --

    def serialized(self) -> str:
        """The column's current state as .wvfmt TOML."""
        from datetime import date

        get = self._controls.get

        def spin_value(section, key):
            widget = get((section, key))
            value = widget.value() if widget else 0.0
            return value if value > 0 else None

        lines = [
            f"# {self._fmt.name} - tuned in the Format Studio on "
            f"{date.today().isoformat()}.",
            "# Edit freely: this is YOUR copy (in ~/.wordvault/formats).",
            "# The full specification is in docs/format-file.md.",
            "",
            "[format]",
            f"name = {_toml_value(self._fmt.name)}",
            "",
            "[page]",
            f"size = {_toml_value(get(('page', 'size')).currentText())}",
        ]
        if get(("page", "duplex")).isChecked():
            lines.append("duplex = true")
        lines.append("")
        lines.append("[page.margins]")
        lines.append('unit = "mm"')
        for key in ("top", "bottom", "left", "right"):
            lines.append(f"{key} = "
                         f"{_toml_value(get(('margins', key)).value())}")
        lines.append("")

        for section in _STYLE_SECTIONS:
            spec: dict = {}
            for key, kind, _label, _max in _STYLE_DIALS:
                widget = get((section, key))
                if widget is None:
                    continue
                if kind in ("font", "align"):
                    value = widget.currentText().strip()
                    if value:
                        spec[key] = value
                elif kind == "check":
                    if widget.isChecked():
                        spec[key] = True
                else:
                    spec[key] = spin_value(section, key)
            _emit_section(lines, section, spec,
                          tuple(k for k, *_ in _STYLE_DIALS))

        for part in ("header", "footer"):
            spec = {}
            for slot in ("left", "center", "right"):
                value = get((part, slot)).text().strip()
                if value:
                    spec[slot] = value
            if spec:
                size = spin_value(part, "size_pt")
                if size:
                    spec["size_pt"] = size
            _emit_section(lines, part, spec,
                          ("left", "center", "right", "size_pt"))

        byline = get(("byline", "text")).text().strip()
        if byline:
            lines += ["[byline]", f"text = {_toml_value(byline)}", ""]
        return "\n".join(lines)

    # ------------------------------------------------------------ save --

    def _save(self) -> None:
        text = self.serialized()
        try:                              # never save an invalid format
            probe = self._path.with_suffix(".studio-probe")
            probe.write_text(text, encoding="utf-8")
            try:
                load_format(probe)
            finally:
                probe.unlink(missing_ok=True)
        except FormatError as error:
            self._status.setText(f"<font color='#b33'>Not saved: "
                                 f"{error}</font>")
            return
        self._path.write_text(text, encoding="utf-8")
        self._status.setText(f"Saved to {self._path.name}.")
