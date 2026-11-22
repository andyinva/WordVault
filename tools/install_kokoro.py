#!/usr/bin/env python3
"""
install_kokoro.py - set up the Kokoro reading voice for WordVault.

Run it once, with WordVault closed, from the WordVault folder using the
same Python that runs WordVault:

    Ubuntu:    venv/bin/python tools/install_kokoro.py
    Windows:   venv\\Scripts\\python tools\\install_kokoro.py

What it does, in order:

    1. installs the kokoro-onnx Python package (with pip);
    2. downloads the voice model and the voices file (about 340 MB in
       all) into the "kokoro" folder in your home folder;
    3. speaks one test sentence so you can hear that it works;
    4. makes Kokoro the Reading voice in WordVault's settings, with
       George (British) reading at 100% speed.

It is safe to run again: finished downloads are kept, and a download
that was cut off carries on from where it stopped.

Options:

    --voice bm_daniel   choose a different voice (see Settings for names)
    --no-select         install only; leave WordVault's settings alone
    --no-test           skip the spoken test sentence
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Let this script import the wordvault package it sits beside.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The two files Kokoro needs, with their exact sizes in bytes so a
# cut-off download is never mistaken for a finished one.
FILES = {
    "kokoro-v1.0.onnx": 325_532_387,
    "voices-v1.0.bin": 28_214_398,
}
DOWNLOAD_BASE = ("https://github.com/thewh1teagle/kokoro-onnx/releases/"
                 "download/model-files-v1.0/")
FOLDER = Path.home() / "kokoro"


# ---------------------------------------------------------------------------
# Step 1: the Python package
# ---------------------------------------------------------------------------

def install_package() -> None:
    """pip install kokoro-onnx into the Python running this script."""
    try:
        import kokoro_onnx  # noqa: F401
        print("1. kokoro-onnx is already installed.")
        return
    except ImportError:
        pass
    print("1. Installing the kokoro-onnx package (a minute or two)...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "kokoro-onnx"])
    if result.returncode != 0:
        sys.exit("   pip could not install kokoro-onnx; see the messages "
                 "above. Nothing else was changed.")
    # Let this running Python notice the package pip just added.
    importlib.invalidate_caches()


# ---------------------------------------------------------------------------
# Step 2: the model files
# ---------------------------------------------------------------------------

def download(name: str, size: int) -> None:
    """Fetch one file into FOLDER, resuming a partial download."""
    target = FOLDER / name
    if target.is_file() and target.stat().st_size == size:
        print(f"   {name}: already here.")
        return

    # Download to NAME.part first; only a complete file gets the real
    # name, so WordVault never tries to load half a model.
    part = FOLDER / (name + ".part")
    have = part.stat().st_size if part.is_file() else 0
    if have > size:                       # not ours; start over
        part.unlink()
        have = 0

    request = urllib.request.Request(DOWNLOAD_BASE + name)
    if have:
        # Ask the server for only the bytes we do not have yet.
        request.add_header("Range", f"bytes={have}-")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if have and response.status != 206:
                have = 0                  # server sent the whole file again
            mode = "ab" if have else "wb"
            with open(part, mode) as out:
                done = have
                while True:
                    block = response.read(1 << 20)        # 1 MB at a time
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    percent = 100 * done // size
                    print(f"\r   {name}: {done >> 20} of {size >> 20} MB "
                          f"({percent}%)", end="", flush=True)
        print()
    except (urllib.error.URLError, OSError) as exc:
        print()
        sys.exit(f"   The download stopped: {exc}\n   Run this script "
                 "again and it will carry on from where it stopped.")

    if part.stat().st_size != size:
        sys.exit(f"   {name} came out the wrong size. Run this script "
                 "again to finish it.")
    part.replace(target)


def download_files() -> None:
    print(f"2. Fetching the voice files into {FOLDER} ...")
    FOLDER.mkdir(parents=True, exist_ok=True)
    for name, size in FILES.items():
        download(name, size)


# ---------------------------------------------------------------------------
# Step 3: a spoken test
# ---------------------------------------------------------------------------

def spoken_test(voice: str) -> None:
    """Say one sentence through the same code WordVault uses."""
    from wordvault.editor.kokoro_voice import (
        ENGLISH_VOICES, KokoroSynth, kokoro_files, make_player, silence,
    )

    print("3. Loading the voice for a spoken test...")
    model, voices = kokoro_files(FOLDER)
    synth = KokoroSynth(model, voices)
    name = ENGLISH_VOICES[voice].split(" ")[0]
    sound = synth.speak(
        f"This is {name}. Word Vault will read your writing in this voice.",
        voice, 1.0)
    if sys.platform != "win32" and shutil.which("aplay") is None:
        print("   The voice works, but the 'aplay' sound player is "
              "missing.\n   Install it with:  sudo apt install alsa-utils")
        return
    player = make_player()
    player.play(sound + silence(0.3), lambda: None)
    player.finish()
    print("   You should have heard the test sentence.")


# ---------------------------------------------------------------------------
# Step 4: WordVault's settings
# ---------------------------------------------------------------------------

def select_in_wordvault(voice: str) -> None:
    """Make Kokoro the Reading voice, at the voice's natural pace."""
    try:
        from PyQt6.QtCore import QSettings
    except ImportError:
        print("4. PyQt6 is not in this Python, so the setting was not "
              "changed.\n   Choose Kokoro yourself under Help > Settings "
              "> Reading voice.")
        return
    # The same names the editor uses (editor/main_window.py).
    settings = QSettings("WordVault", "WordVault")
    settings.setValue("tts_engine", "kokoro")
    settings.setValue("kokoro_voice", voice)
    # Kokoro's natural pace is 100%.  A slower setting chosen to tame
    # Piper would make this voice drag.
    settings.setValue("tts_rate_percent", 100)
    settings.sync()
    print("4. WordVault is now set to read with Kokoro at 100% speed.")


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--voice", default="bm_george",
                        help="voice id, e.g. bm_george or am_michael")
    parser.add_argument("--no-select", action="store_true",
                        help="do not change WordVault's settings")
    parser.add_argument("--no-test", action="store_true",
                        help="skip the spoken test sentence")
    args = parser.parse_args()

    from wordvault.editor.kokoro_voice import ENGLISH_VOICES

    if args.voice not in ENGLISH_VOICES:
        sys.exit(f"Unknown voice {args.voice!r}. Choose one of: "
                 + ", ".join(ENGLISH_VOICES))

    install_package()
    download_files()
    if not args.no_test:
        spoken_test(args.voice)
    if not args.no_select:
        select_in_wordvault(args.voice)
    print("\nDone. Start WordVault and press Read.")


if __name__ == "__main__":
    main()
