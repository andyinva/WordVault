"""
wordvault.printing — the .wvfmt print-format system.

WordVault never shows formatted output on screen (deliberately
non-WYSIWYG): the author writes plain Markdown, picks a format BY NAME
at print time, and first sees the styled result on paper.

  format_file.py  (Qt-free)  load and validate .wvfmt definition files
  renderer.py     (Qt)       Markdown -> styled QTextDocument + page setup

Format files are created by hand or by the future WordVault Formatter
app — never by WordVault itself.  See docs/format-file.md for the spec.
"""

from wordvault.printing.format_file import (
    FormatError,
    PrintFormat,
    ensure_default_formats,
    list_formats,
    load_format,
)

__all__ = [
    "FormatError",
    "PrintFormat",
    "ensure_default_formats",
    "list_formats",
    "load_format",
]
