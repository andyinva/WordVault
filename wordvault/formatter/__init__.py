"""
wordvault.formatter — the book assembler.

WordVault is the writing room; the Formatter is the bindery.  It takes
ordered chapters from the library and produces a finished, print-ready
book PDF: front matter (title page, copyright page with ISBN), table of
contents, the chapters themselves, and back matter (subject index and
scripture index) — each section switched on or off per book.

The pieces:

    book.py     BookProject — the saved .wvbook project file (pure
                Python, no Qt; testable everywhere)
    builder.py  Assembles chapters into one manuscript and drives the
                print renderer to a PDF
    window.py   FormatterWindow — the PyQt6 interface, launched from
                WordVault's Library menu
"""

from wordvault.formatter.book import BookProject  # noqa: F401
