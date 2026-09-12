"""
updater.py -- Help > Check for Updates.

WordVault reaches its users in two ways (docs/updating.md):

  * a git checkout (GitHub Desktop or plain git), or
  * a ZIP downloaded from GitHub and unpacked into a folder.

This module makes updating a menu click for both.  The pieces:

  1. WHAT IS NEWEST.  The version of record is the ``__version__`` line
     in ``wordvault/__init__.py`` on GitHub's main branch.  We fetch that
     one small file over HTTPS and read the version and release date out
     of it.  No tags, no releases page, no login: bumping the version in
     ``__init__.py`` and pushing IS publishing a release.

  2. WHAT IS RUNNING.  ``wordvault.__version__`` in this very process.

  3. HOW TO UPDATE.  The program folder tells us how it arrived:
       - a ``.git`` folder and a ``git`` command  -> ``git pull``
       - a ``.git`` folder but no ``git`` command -> the user has GitHub
         Desktop; we can only point them at its Pull button
       - no ``.git`` folder                       -> a ZIP install; we
         download main.zip and unpack it over the program folder

     A user's library never lives in the program folder (it is in
     ``~/.wordvault``), so replacing program files cannot touch writing.

Everything that talks to the network or runs git lives in plain
functions that take no Qt objects, so they can be unit-tested with fake
data and reused headless.  The two QThread workers at the bottom wrap
those functions so the window never freezes while waiting on GitHub.

Design rules:
  * Never raise into the GUI.  Every failure becomes an ``UpdateError``
    with a sentence a writer can act on.
  * Never touch the library.  We only ever write inside the program
    folder (or a temp folder).
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from wordvault import REPO_URL, __version__

# ---------------------------------------------------------------------------
# Where things are on GitHub
# ---------------------------------------------------------------------------

#: The one file whose __version__ line defines "the newest version".
VERSION_FILE_URL = (
    REPO_URL.replace("https://github.com/", "https://raw.githubusercontent.com/")
    + "/main/wordvault/__init__.py"
)

#: The whole program as a ZIP of the main branch (what the green Code
#: button offers).  GitHub puts everything inside one top-level folder
#: named ``WordVault-main/``; ``apply_zip_bytes`` strips that off.
ZIP_URL = REPO_URL + "/archive/refs/heads/main.zip"

#: Seconds to wait for GitHub before giving up quietly.
TIMEOUT = 8


class UpdateError(Exception):
    """A problem the user can read: no network, dirty checkout, etc."""


@dataclass(frozen=True)
class RemoteInfo:
    """What GitHub says the newest version is."""

    version: str        # e.g. "1.1"
    release_date: str   # e.g. "September 12, 2026" (may be "")

    @property
    def is_newer(self) -> bool:
        """True when the copy on GitHub is newer than the one running."""
        return is_newer(self.version, __version__)


# ---------------------------------------------------------------------------
# Pure helpers (no network, no Qt): easy to test
# ---------------------------------------------------------------------------

def parse_version(text: str) -> tuple[int, ...]:
    """Turn "1.0", "1.2.3", or "v1.10" into a tuple of ints for comparing.

    Anything that is not digits-and-dots is ignored, so a stray "v" or a
    suffix like "-beta" does not break the comparison; "1.10" correctly
    sorts after "1.9" (which plain string comparison gets wrong).
    """
    numbers = re.findall(r"\d+", text)
    return tuple(int(n) for n in numbers) or (0,)


def is_newer(remote: str, local: str) -> bool:
    """Is version string ``remote`` strictly newer than ``local``?"""
    return parse_version(remote) > parse_version(local)


def parse_version_file(source: str) -> RemoteInfo:
    """Read ``__version__`` and ``RELEASE_DATE`` out of __init__.py text.

    The file is Python, but we do not execute it (it came off the
    network); a regular expression finds the two assignments instead.
    """
    version_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.M)
    if not version_match:
        raise UpdateError("Could not find a version number in the file GitHub sent.")
    date_match = re.search(r'^RELEASE_DATE\s*=\s*["\']([^"\']*)["\']', source, re.M)
    return RemoteInfo(
        version=version_match.group(1),
        release_date=date_match.group(1) if date_match else "",
    )


def program_root() -> Path:
    """The folder WordVault runs from: the parent of the ``wordvault``
    package (the one holding pyproject.toml, docs/, tests/ ...)."""
    return Path(__file__).resolve().parent.parent


def install_kind(root: Path | None = None) -> str:
    """How this copy arrived, which decides how it updates.

    Returns one of:
      "git"             a checkout, and the git command is available
      "github-desktop"  a checkout, but no git on the PATH (GitHub
                        Desktop keeps its own private copy of git)
      "zip"             no .git folder: a downloaded ZIP
    """
    root = root or program_root()
    if (root / ".git").exists():
        return "git" if shutil.which("git") else "github-desktop"
    return "zip"


# ---------------------------------------------------------------------------
# Network: asking GitHub what is newest
# ---------------------------------------------------------------------------

def fetch_remote_info(url: str = VERSION_FILE_URL, timeout: float = TIMEOUT) -> RemoteInfo:
    """Download __init__.py from GitHub and read the version out of it."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "WordVault-updater"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            source = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # URLError, timeout, HTTPError, SSL ...
        raise UpdateError(
            "Could not reach GitHub to check for updates.\n"
            f"({exc.__class__.__name__}: {exc})"
        ) from exc
    return parse_version_file(source)


# ---------------------------------------------------------------------------
# Applying an update
# ---------------------------------------------------------------------------

def _run_git(root: Path, *args: str) -> str:
    """Run one git command in the program folder; return its output."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"Could not run git: {exc}") from exc
    if result.returncode != 0:
        raise UpdateError(
            f"git {' '.join(args)} failed:\n{(result.stderr or result.stdout).strip()}"
        )
    return result.stdout.strip()


def current_commit(root: Path | None = None) -> str:
    """The short commit id of a git checkout, or "" for a ZIP install.
    Shown in Help > About so a bug report can say exactly what ran."""
    root = root or program_root()
    if install_kind(root) != "git":
        return ""
    try:
        return _run_git(root, "rev-parse", "--short", "HEAD")
    except UpdateError:
        return ""


def apply_git_update(root: Path) -> str:
    """``git pull`` the program folder.  Refuses (clearly) if the user
    has edited files, so their work is never silently merged over."""
    dirty = _run_git(root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise UpdateError(
            "This copy has local code changes, so an automatic pull could "
            "tangle them with the update.\n\nCommit or discard those changes "
            "(GitHub Desktop or git), then check for updates again.\n\n"
            f"Changed files:\n{dirty}"
        )
    before = _run_git(root, "rev-parse", "HEAD")
    _run_git(root, "pull", "--ff-only")
    after = _run_git(root, "rev-parse", "HEAD")
    if before == after:
        return "Already up to date."

    # A new version may need a new package.  When pyproject.toml changed
    # AND this copy was pip-installed in editable mode (the developer
    # set-up), refresh it; a plain "run from the folder" copy needs
    # nothing, and any missing package is named at startup anyway.
    changed = _run_git(root, "diff", "--name-only", before, after)
    if "pyproject.toml" in changed.splitlines() and _is_editable_install(root):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-e", f"{root}[full]"],
            cwd=root, capture_output=True, text=True, timeout=600, check=False,
        )
    return f"Updated {before[:7]} -> {after[:7]}."


def _is_editable_install(root: Path) -> bool:
    """Was ``pip install -e .`` run for this folder in this interpreter?
    Editable installs leave a ``__editable__`` finder or a ``.egg-link``
    / ``*.egg-info`` behind; the egg-info in the project folder is the
    simplest tell."""
    return any(root.glob("*.egg-info"))


def apply_zip_bytes(data: bytes, root: Path) -> str:
    """Unpack a GitHub main.zip over the program folder.

    GitHub wraps everything in one top folder (``WordVault-main/``); the
    files are copied from inside it so they land directly in ``root``.
    Existing files are overwritten, new ones added, nothing is deleted:
    a user's own notes or scripts sitting in the folder survive.
    Python has already loaded the running program into memory, so
    replacing the .py files underneath it is safe; the new code takes
    effect at the next start.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UpdateError("The download from GitHub was not a valid ZIP file.") from exc

    with tempfile.TemporaryDirectory() as tmp:
        archive.extractall(tmp)
        # The single top-level folder GitHub created.
        tops = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(tops) != 1:
            raise UpdateError("The ZIP from GitHub did not have the expected layout.")
        source = tops[0]
        count = 0
        for item in source.rglob("*"):
            if item.is_dir():
                continue
            target = root / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            count += 1
    return f"Replaced the program files ({count} files)."


def download_zip(url: str = ZIP_URL, timeout: float = TIMEOUT * 4) -> bytes:
    """Fetch main.zip from GitHub (a few megabytes)."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "WordVault-updater"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise UpdateError(f"Could not download the update from GitHub.\n({exc})") from exc


def apply_update(root: Path | None = None) -> str:
    """Update the program folder whichever way it arrived; return a
    one-line summary for the status bar."""
    root = root or program_root()
    kind = install_kind(root)
    if kind == "git":
        return apply_git_update(root)
    if kind == "github-desktop":
        raise UpdateError(
            "This copy is managed by GitHub Desktop.\n\n"
            "Close WordVault, open GitHub Desktop, choose the WordVault "
            "repository, and click Fetch origin, then Pull origin.  "
            "Start WordVault again and the new version is in place."
        )
    return apply_zip_bytes(download_zip(), root)


# ---------------------------------------------------------------------------
# Qt workers: run the above off the GUI thread
# ---------------------------------------------------------------------------

def _make_workers():
    """Build the QThread classes lazily, so importing this module never
    requires PyQt6 (keeping the storage layer headless-friendly)."""
    from PyQt6.QtCore import QThread, pyqtSignal

    class CheckWorker(QThread):
        """Asks GitHub for the newest version in the background.
        Emits ``found(RemoteInfo)`` or ``failed(str)``."""

        found = pyqtSignal(object)
        failed = pyqtSignal(str)

        def run(self) -> None:
            try:
                self.found.emit(fetch_remote_info())
            except UpdateError as exc:
                self.failed.emit(str(exc))

    class ApplyWorker(QThread):
        """Performs the update in the background.
        Emits ``done(str)`` with a summary or ``failed(str)``."""

        done = pyqtSignal(str)
        failed = pyqtSignal(str)

        def run(self) -> None:
            try:
                self.done.emit(apply_update())
            except UpdateError as exc:
                self.failed.emit(str(exc))

    return CheckWorker, ApplyWorker
