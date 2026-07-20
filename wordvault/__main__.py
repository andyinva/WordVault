"""
__main__.py — launch the WordVault editor:

    python -m wordvault                # opens/creates the default library
    python -m wordvault my_library.db  # opens/creates a specific library

The default library lives at ~/.wordvault/library.db — the same location
on Ubuntu (/home/<user>/.wordvault/) and Windows 11
(C:/Users/<user>/.wordvault/), keeping behavior identical on both
(DESIGN.md section 12).
"""

from __future__ import annotations

import sys
from pathlib import Path


def default_library_path() -> Path:
    """~/.wordvault/library.db, creating the folder on first run."""
    folder = Path.home() / ".wordvault"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "library.db"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv

    # Import PyQt6 here (not at module top) so that `import wordvault`
    # stays GUI-free — the storage layer must keep working headless.
    from PyQt6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

    from wordvault.editor import MainWindow
    from wordvault.storage.encryption import is_encrypted_database
    from wordvault.storage.store import DocumentStore

    library = Path(argv[1]) if len(argv) > 1 else default_library_path()

    app = QApplication(argv)
    app.setApplicationName("WordVault")

    # Stage 9: an encrypted library asks for its passphrase up front.
    # Wrong entries just re-prompt; Cancel exits quietly.
    passphrase = None
    while is_encrypted_database(library):
        pw, ok = QInputDialog.getText(
            None, "WordVault", f"Passphrase for {library.name}:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return 0
        try:
            DocumentStore(library, passphrase=pw).close()  # probe
            passphrase = pw
            break
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(None, "WordVault", str(exc))

    window = MainWindow(library, passphrase=passphrase)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
