"""
wordvault.editor — the PyQt6 user interface (roadmap stage 2).

This package holds everything graphical.  The rule from DESIGN.md section 3
applies everywhere here: the editor NEVER touches SQL — it talks only to
DocumentStore.  That keeps the GUI thin and the storage layer testable and
replaceable (a future server can stand in for the store unchanged).

Stage 2 scope (deliberately minimal, per the roadmap):
  * open or create a library database
  * list documents, create a new document, switch between documents
  * type; every pause becomes a timestamped revision automatically
  * status bar showing title, revision count, word count, last-save time

Time travel UI (the slider), age coloring, outline pane, and search all
arrive in later stages — the data for them is already being recorded.
"""

# MainWindow is imported lazily (PEP 562) so that pure-logic submodules
# (outline parsing, age tracking) can be imported for headless tests
# without dragging in the whole GUI stack.
__all__ = ["MainWindow"]


def __getattr__(name):
    if name == "MainWindow":
        from wordvault.editor.main_window import MainWindow
        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
