"""
extensions.py — personal extensions, loaded from ~/.wordvault/extensions.

WordVault is the same open-source program for everyone, but a writer's
copy may grow personal abilities that were never shipped.  At startup
the editor looks in the personal folder

    ~/.wordvault/extensions/

(the same hidden home as personal print formats and the library) and
imports every ``*.py`` file found there.  A file that defines a
function ``register(window)`` is called with the main window; what it
does from there is its own business.  Typical extensions add a button
with ``window.add_extension_button(text, tooltip, callback)``.

Design rules, in keeping with the vault's philosophy of honesty:

* Nothing here is hidden or disabled — a copy without extensions simply
  HAS none.  The folder does not even exist until its owner creates it.
* A broken extension must never take the program down with it: every
  load error is caught, reported on standard error, and skipped, so
  WordVault always starts.
* Extensions are ordinary Python running with the program's own powers.
  Only put files here that you wrote or read and trust — the same rule
  as for anything you run on your own computer.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

#: The personal folder searched at startup.  Module-level so tests can
#: point it somewhere temporary.
EXTENSIONS_DIR = Path.home() / ".wordvault" / "extensions"


def load_extensions(window) -> list[str]:
    """Import every extension and call its register(window).

    Returns the names (file stems) of the extensions that registered
    successfully — the caller may mention them in the status bar.
    Files starting with an underscore are skipped, so an extension can
    keep private helper modules beside itself.
    """
    loaded: list[str] = []
    if not EXTENSIONS_DIR.is_dir():
        return loaded                     # no folder: nothing personal here
    for path in sorted(EXTENSIONS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue                      # helper module, not an extension
        try:
            spec = importlib.util.spec_from_file_location(
                f"wordvault_extension_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            # Registering in sys.modules first lets an extension import
            # dataclasses/typing helpers from itself without surprises.
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if callable(register):
                register(window)
                loaded.append(path.stem)
        except Exception:                 # noqa: BLE001 — never block startup
            print(f"WordVault: extension {path.name} failed to load:",
                  file=sys.stderr)
            traceback.print_exc()
    return loaded
