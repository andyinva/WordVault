"""
Tests for wordvault/updater.py: the parts that need no network.

The version comparison, reading the version out of __init__.py text,
telling a git checkout from a ZIP folder, and unpacking a GitHub-style
ZIP over a program folder.  The network calls themselves are two small
urllib functions; everything they feed into is covered here.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from wordvault import __version__
from wordvault import updater


# ------------------------------------------------------------ versions --

@pytest.mark.parametrize("text, expected", [
    ("1.0", (1, 0)),
    ("1.2.3", (1, 2, 3)),
    ("v1.10", (1, 10)),
    ("2.0-beta", (2, 0)),
    ("", (0,)),
])
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


def test_is_newer_compares_numerically_not_as_text():
    # "1.10" is newer than "1.9" even though "1.1..." sorts first as text.
    assert updater.is_newer("1.10", "1.9")
    assert not updater.is_newer("1.9", "1.10")
    assert not updater.is_newer("1.0", "1.0")
    assert updater.is_newer("2", "1.99.99")


def test_parse_version_file_reads_version_and_date():
    source = (
        '"""docstring"""\n'
        'import os\n'
        '__version__ = "1.7"\n'
        'RELEASE_DATE = "March 3, 2027"\n'
    )
    info = updater.parse_version_file(source)
    assert info.version == "1.7"
    assert info.release_date == "March 3, 2027"
    assert info.is_newer == updater.is_newer("1.7", __version__)


def test_parse_version_file_without_version_line_fails_clearly():
    with pytest.raises(updater.UpdateError):
        updater.parse_version_file("print('nothing here')\n")


def test_running_version_file_agrees_with_package():
    """The real __init__.py must parse to the version the package reports;
    this is exactly what the remote check does with GitHub's copy."""
    source = (Path(updater.__file__).parent / "__init__.py").read_text()
    assert updater.parse_version_file(source).version == __version__


# -------------------------------------------------------- install kind --

def test_install_kind_zip_when_no_git_folder(tmp_path):
    assert updater.install_kind(tmp_path) == "zip"


def test_install_kind_git_or_desktop_when_git_folder_present(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updater.shutil, "which", lambda name: "/usr/bin/git")
    assert updater.install_kind(tmp_path) == "git"
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)
    assert updater.install_kind(tmp_path) == "github-desktop"


def test_program_root_is_the_project_folder():
    root = updater.program_root()
    assert (root / "wordvault" / "__init__.py").exists()
    assert (root / "pyproject.toml").exists()


# ------------------------------------------------------------ zip apply --

def _github_style_zip(files: dict[str, str]) -> bytes:
    """Build a ZIP the way GitHub does: everything under one top folder."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"WordVault-main/{name}", content)
    return buffer.getvalue()


def test_apply_zip_bytes_replaces_and_adds_but_never_deletes(tmp_path):
    # An existing "program folder" with an old file, a user's own note,
    # and a file that the new version no longer ships.
    (tmp_path / "wordvault").mkdir()
    (tmp_path / "wordvault" / "__init__.py").write_text("old")
    (tmp_path / "my_notes.txt").write_text("mine")
    (tmp_path / "obsolete.py").write_text("gone upstream")

    data = _github_style_zip({
        "wordvault/__init__.py": "new",
        "wordvault/updater.py": "brand new file",
        "docs/guide.md": "docs",
    })
    summary = updater.apply_zip_bytes(data, tmp_path)

    assert "3 files" in summary
    assert (tmp_path / "wordvault" / "__init__.py").read_text() == "new"
    assert (tmp_path / "wordvault" / "updater.py").read_text() == "brand new file"
    assert (tmp_path / "docs" / "guide.md").read_text() == "docs"
    # Untouched: the user's own file and the file upstream dropped.
    assert (tmp_path / "my_notes.txt").read_text() == "mine"
    assert (tmp_path / "obsolete.py").exists()
    # No stray top-level folder was created.
    assert not (tmp_path / "WordVault-main").exists()


def test_apply_zip_bytes_rejects_garbage(tmp_path):
    with pytest.raises(updater.UpdateError):
        updater.apply_zip_bytes(b"not a zip at all", tmp_path)


def test_apply_zip_bytes_rejects_unexpected_layout(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("one/a.txt", "a")
        archive.writestr("two/b.txt", "b")   # two top folders: not GitHub's shape
    with pytest.raises(updater.UpdateError):
        updater.apply_zip_bytes(buffer.getvalue(), tmp_path)


# ------------------------------------------------------------ git apply --

def test_apply_git_update_refuses_a_dirty_checkout(tmp_path, monkeypatch):
    """Local edits must never be silently merged over."""
    calls = []

    def fake_git(root, *args):
        calls.append(args)
        if args[0] == "status":
            return " M wordvault/editor/main_window.py"
        raise AssertionError("pull must not run on a dirty tree")

    monkeypatch.setattr(updater, "_run_git", fake_git)
    with pytest.raises(updater.UpdateError) as err:
        updater.apply_git_update(tmp_path)
    assert "main_window.py" in str(err.value)
    assert calls == [("status", "--porcelain", "--untracked-files=no")]


def test_apply_git_update_pulls_a_clean_checkout(tmp_path, monkeypatch):
    heads = iter(["aaaaaaa1", "bbbbbbb2"])   # before, after

    def fake_git(root, *args):
        if args[0] == "status":
            return ""
        if args[0] == "rev-parse":
            return next(heads)
        if args[0] == "pull":
            return "Updating aaaaaaa1..bbbbbbb2"
        if args[0] == "diff":
            return "wordvault/updater.py"   # pyproject unchanged: no pip
        raise AssertionError(f"unexpected git call {args}")

    monkeypatch.setattr(updater, "_run_git", fake_git)
    summary = updater.apply_git_update(tmp_path)
    assert summary == "Updated aaaaaaa -> bbbbbbb."


# ------------------------------------------- closing during a check --

def test_closing_during_an_update_check_is_safe():
    """Closing WordVault while the startup update check was still
    asking GitHub destroyed the worker thread mid-request and aborted
    the program ("QThread: Destroyed while thread is still running").
    Workers now belong to no window and are kept alive until done."""
    import gc
    import os
    import threading
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)
    from PyQt6.QtWidgets import QApplication, QWidget

    from wordvault import updater

    app = QApplication.instance() or QApplication([])
    CheckWorker, _ = updater._make_workers()

    # A check that is "on the network" until we say otherwise.
    answer = threading.Event()

    class SlowCheck(CheckWorker):
        def run(self) -> None:
            answer.wait(10)
            self.found.emit("late answer")

    window = QWidget()                    # stands in for the main window
    received = []
    worker = SlowCheck()
    worker.found.connect(received.append)
    mine = [worker]
    updater.start_worker(worker)
    assert worker in updater._running_workers

    # The window closes while the check is still out: it lets go...
    updater.release_workers(mine)
    assert mine == []
    window.deleteLater()
    del window, worker
    gc.collect()
    app.processEvents()                   # ...and is really destroyed.

    # The check is still running, and still safely held.
    assert len(updater._running_workers) >= 1
    assert updater._running_workers[-1].isRunning()

    # GitHub finally answers: the worker ends cleanly, nobody is told.
    answer.set()
    end = time.monotonic() + 5
    while updater._running_workers and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    assert updater._running_workers == []
    assert received == []


def test_exit_waits_for_a_running_worker():
    """At program exit a worker still running is waited for, not
    destroyed under its own feet."""
    import os
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)
    from PyQt6.QtWidgets import QApplication

    from wordvault import updater

    QApplication.instance() or QApplication([])
    CheckWorker, _ = updater._make_workers()

    class ShortCheck(CheckWorker):
        def run(self) -> None:
            time.sleep(0.3)

    worker = ShortCheck()
    updater.start_worker(worker)
    updater._wait_for_workers()           # what atexit calls
    assert worker.isFinished()
    assert updater._running_workers == []
