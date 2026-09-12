"""
piper_voice.py -- Read Aloud through Piper, a neural voice.

Why this exists
---------------
The Read button speaks through Qt's QTextToSpeech, which uses whatever
the operating system offers.  On Windows that is a passable voice; on
Ubuntu it is espeak-ng, which sounds like a 1990s robot.  Piper
(https://github.com/rhasspy/piper) is a free, offline, neural
text-to-speech program whose voices sound like a calm human reader.
It runs on Windows and Ubuntu alike, so choosing it in Settings gives
the same voice on both machines.

How it is driven
----------------
Piper is a command-line program.  Started with ``--json-input`` and
``--output_dir``, it loads its voice model once and then waits on
stdin; every JSON line it receives ({"text": "..."}) becomes one WAV
file in the output folder, and it prints that file's path on stdout.
So one Piper process serves a whole reading session, one sentence at
a time.

Reading happens sentence by sentence in a background thread:

    split text into sentences
    for each sentence:
        ask Piper for its WAV      (the NEXT sentence is requested while
        play the WAV                the current one is still playing, so
        tell the window which       there is no gap between them)
        sentence is sounding

Playback uses the simplest thing each platform is sure to have: ``aplay``
on Linux (part of every Ubuntu desktop) and the ``winsound`` module on
Windows (in Python's standard library).  No extra packages.

What the window sees
--------------------
``PiperEngine`` offers the small surface the Read button needs, shaped
like QTextToSpeech so the window code barely changes:

    engine.say(text)           start reading
    engine.stop()              stop, at once
    engine.speaking            True while reading
    engine.setRate(-1..+1)     the Settings reading speed
    engine.sayingWord          signal(word, utterance, start, length):
                               emitted once per SENTENCE, with the
                               sentence's span in the text handed to
                               say(); the window uses it exactly as it
                               uses Qt's per-word signal, so the
                               reading light moves a sentence at a time
    engine.finished            signal(): reading ended or was stopped
    engine.failed              signal(str): something went wrong

Files
-----
The Piper folder (Settings > Piper folder, default ~/piper) holds the
program (``piper/piper`` or ``piper/piper.exe`` as unpacked from the
release archive, or the executable itself) and one or more voices, each
a pair of files ``NAME.onnx`` and ``NAME.onnx.json`` downloaded from
https://huggingface.co/rhasspy/piper-voices.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

# ---------------------------------------------------------------------------
# Finding Piper and its voices
# ---------------------------------------------------------------------------

DEFAULT_PIPER_DIR = Path.home() / "piper"

VOICES_URL = "https://huggingface.co/rhasspy/piper-voices"
RELEASES_URL = "https://github.com/rhasspy/piper/releases/latest"


def find_piper_executable(folder: Path | str | None = None) -> Path | None:
    """The Piper program, or None.

    Looks in the folder the user named (the release archive unpacks to a
    ``piper/`` sub-folder, so both ``folder/piper/piper`` and
    ``folder/piper`` are tried), then on the PATH.
    """
    folder = Path(folder or DEFAULT_PIPER_DIR).expanduser()
    exe = "piper.exe" if platform.system() == "Windows" else "piper"
    for candidate in (folder / "piper" / exe, folder / exe):
        if candidate.is_file():
            return candidate
    found = shutil.which("piper")
    return Path(found) if found else None


def list_voices(folder: Path | str | None = None) -> list[Path]:
    """Every voice in the folder: a ``.onnx`` file whose ``.onnx.json``
    sidecar is present (Piper needs both).  Sorted by name."""
    folder = Path(folder or DEFAULT_PIPER_DIR).expanduser()
    if not folder.is_dir():
        return []
    voices = []
    for onnx in sorted(folder.rglob("*.onnx")):
        if onnx.with_name(onnx.name + ".json").is_file():
            voices.append(onnx)
    return voices


def voice_display_name(voice: Path) -> str:
    """"en_US-ryan-medium.onnx" -> "ryan (en_US, medium)"."""
    stem = voice.name[: -len(".onnx")] if voice.name.endswith(".onnx") else voice.stem
    parts = stem.split("-")
    if len(parts) >= 3:
        return f"{parts[1]} ({parts[0]}, {'-'.join(parts[2:])})"
    return stem


def player_available() -> bool:
    """Can this machine play a WAV the way we play them?"""
    if platform.system() == "Windows":
        return True                      # winsound is standard library
    return shutil.which("aplay") is not None


def rate_to_length_scale(rate: float) -> float:
    """Qt's rate (-1 slow .. 0 normal .. +1 fast) -> Piper's
    length_scale (2.0 slow .. 1.0 normal .. 0.67 fast).  Settings
    stores a percent; the window converts it to Qt's scale, and this
    turns that into the stretch factor Piper wants."""
    percent = 100 + rate * 100          # -1..+1 -> 0..200
    percent = max(50.0, min(150.0, percent))
    return round(100.0 / percent, 3)


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------

# Group 1: the sentence's closing punctuation (with any closing quotes
# or bracket), which STAYS with the sentence; group 2: the whitespace
# after it, which does not.  Or a blank line on its own.
_SENTENCE_END = re.compile(r"([.!?][\"'”’)]*)(\s+)|\n{2,}")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Cut text into sentences; return (start, length) spans into text.

    A sentence ends at . ! or ? followed by whitespace (closing quotes
    allowed in between), or at a blank line.  Spans skip leading and
    trailing whitespace so the reading light hugs the words.  Very long
    sentence-less stretches (a list, say) are still one span each; Piper
    copes with those fine.
    """
    spans = []
    position = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end(1) if match.group(1) else match.start()
        spans.append((position, end))
        position = match.end()
    spans.append((position, len(text)))

    trimmed = []
    for start, end in spans:
        chunk = text[start:end]
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk) - len(chunk.rstrip())
        if end - start - lead - trail > 0:
            trimmed.append((start + lead, end - start - lead - trail))
    return trimmed


# ---------------------------------------------------------------------------
# The Piper process: one per reading session
# ---------------------------------------------------------------------------

class PiperProcess:
    """A running Piper, fed sentences over stdin, answering with WAV paths.

    Not thread-safe by itself; ``PiperReader`` calls ``synthesize`` from
    a single worker thread.
    """

    def __init__(self, executable: Path, voice: Path, length_scale: float,
                 work_dir: Path) -> None:
        self.work_dir = work_dir
        command = [
            str(executable),
            "--model", str(voice),
            "--output_dir", str(work_dir),
            "--length_scale", str(length_scale),
            "--sentence_silence", "0.1",
            "--json-input",
            "--quiet",
        ]
        creation = {}
        if platform.system() == "Windows":
            # No console window flashing up behind the editor.
            creation["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            bufsize=1, **creation,
        )

    def synthesize(self, sentence: str) -> Path:
        """Hand Piper one sentence; block until its WAV exists."""
        if self._proc.poll() is not None:
            raise RuntimeError("Piper stopped unexpectedly.")
        # Newlines inside a sentence would be read as separate requests.
        request = json.dumps({"text": " ".join(sentence.split())})
        try:
            self._proc.stdin.write(request + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Piper stopped answering: {exc}") from exc
        path = Path(line.strip())
        if not line or not path.is_file():
            raise RuntimeError("Piper did not produce audio for a sentence.")
        return path

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()


# ---------------------------------------------------------------------------
# Playing a WAV, interruptibly
# ---------------------------------------------------------------------------

class Player:
    """Plays one WAV file at a time; ``stop()`` cuts it off mid-word."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def play(self, wav: Path) -> None:
        """Block until the file has finished (or was stopped)."""
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(str(wav), winsound.SND_FILENAME)
            return
        with self._lock:
            self._proc = subprocess.Popen(
                ["aplay", "-q", str(wav)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        self._proc.wait()
        with self._lock:
            self._proc = None

    def stop(self) -> None:
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
            return
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()


# ---------------------------------------------------------------------------
# The reading thread
# ---------------------------------------------------------------------------

class PiperReader(QThread):
    """Reads one text, sentence by sentence, then exits.

    Runs Piper and the player off the GUI thread.  Signals carry the
    sentence spans and the outcome back to ``PiperEngine``.
    """

    sentence_started = pyqtSignal(int, int)       # start, length in text
    problem = pyqtSignal(str)

    def __init__(self, executable: Path, voice: Path, length_scale: float,
                 text: str, player: Player, parent=None) -> None:
        super().__init__(parent)
        self._executable = executable
        self._voice = voice
        self._length_scale = length_scale
        self._text = text
        self._player = player
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()
        self._player.stop()

    def run(self) -> None:
        spans = split_sentences(self._text)
        if not spans:
            return
        with tempfile.TemporaryDirectory(prefix="wordvault-piper-") as tmp:
            try:
                piper = PiperProcess(self._executable, self._voice,
                                     self._length_scale, Path(tmp))
            except OSError as exc:
                self.problem.emit(f"Could not start Piper: {exc}")
                return
            try:
                self._read_all(piper, spans)
            except RuntimeError as exc:
                self.problem.emit(str(exc))
            finally:
                piper.close()

    def _read_all(self, piper: PiperProcess, spans) -> None:
        # One helper thread synthesizes the NEXT sentence while the
        # current one plays, so sentences follow each other without a
        # pause for Piper to think.
        with ThreadPoolExecutor(max_workers=1) as ahead:
            def request(index: int) -> Future:
                start, length = spans[index]
                return ahead.submit(piper.synthesize,
                                    self._text[start:start + length])

            pending = request(0)
            for index, (start, length) in enumerate(spans):
                if self._stop.is_set():
                    return
                wav = pending.result()          # wait for this sentence
                if index + 1 < len(spans):
                    pending = request(index + 1)   # queue the next
                if self._stop.is_set():
                    return
                self.sentence_started.emit(start, length)
                self._player.play(wav)
                try:
                    os.remove(wav)               # tidy as we go
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# The engine the window talks to
# ---------------------------------------------------------------------------

class PiperEngine(QObject):
    """Read Aloud through Piper; see the module docstring for the
    surface it offers the window."""

    #: (word, utterance, start, length) -- same shape as
    #: QTextToSpeech.sayingWord, but once per sentence.
    sayingWord = pyqtSignal(str, int, int, int)
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, executable: Path, voice: Path, parent=None) -> None:
        super().__init__(parent)
        self._executable = executable
        self._voice = voice
        self._rate = 0.0
        self._reader: PiperReader | None = None
        self._player = Player()

    # --- the QTextToSpeech-shaped surface ---------------------------------

    @property
    def speaking(self) -> bool:
        return self._reader is not None and self._reader.isRunning()

    def setRate(self, rate: float) -> None:
        """Qt's -1..+1; takes effect at the next say()."""
        self._rate = float(rate)

    def say(self, text: str) -> None:
        self.stop()
        reader = PiperReader(self._executable, self._voice,
                             rate_to_length_scale(self._rate),
                             text, self._player, self)
        reader.sentence_started.connect(self._on_sentence)
        reader.problem.connect(self.failed)
        reader.finished.connect(self._on_reader_finished)
        self._reader = reader
        reader.start()

    def stop(self) -> None:
        reader = self._reader
        if reader is not None and reader.isRunning():
            reader.request_stop()
            reader.wait(3000)

    # --- internals ----------------------------------------------------------

    def _on_sentence(self, start: int, length: int) -> None:
        self.sayingWord.emit("", 0, start, length)

    def _on_reader_finished(self) -> None:
        self._reader = None
        self.finished.emit()
