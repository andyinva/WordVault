"""
kokoro_voice.py -- Read Aloud through Kokoro, a natural neural voice.

Why this exists
---------------
Piper (piper_voice.py) was a great step up from the robot voice, but it
still sounds choppy over a long essay, most of all when slowed down.
Kokoro (https://github.com/hexgrad/kokoro) is a newer free, offline
voice model that reads with a smoother, more human flow.  It needs no
graphics card and runs on Windows and Ubuntu alike.

How it differs from the Piper engine
------------------------------------
* Kokoro is a Python package (``kokoro-onnx``), not a separate program,
  so the voice model is loaded ONCE and kept in memory.  The second and
  later presses of Read start almost at once.
* On Linux the sound goes out as ONE continuous stream (a single
  ``aplay`` fed raw audio) rather than one WAV file per sentence, so
  there is no click or gap where sentences meet.
* The pause after each sentence is set here, on purpose: a short one
  between sentences and a longer one between paragraphs, the way a
  person reads aloud.
* Abbreviations are spoken as words ("Matt. 24" is read "Matthew 24").

Reading still happens sentence by sentence in a background thread, and
a few sentences are prepared ahead of the one being spoken so the voice
never has to stop and think.

What the window sees
--------------------
``KokoroEngine`` offers exactly the surface ``PiperEngine`` does (see
piper_voice.py), so the window treats the two alike:

    engine.say(text)   engine.stop()   engine.speaking
    engine.setRate(-1..+1)
    engine.sayingWord  signal(word, utterance, start, length), emitted
                       once per SENTENCE with the sentence's span
    engine.finished    signal()
    engine.failed      signal(str)

Files
-----
The Kokoro folder (default ~/kokoro) holds two files, downloaded once
by ``python tools/install_kokoro.py``:

    kokoro-v1.0.onnx     the voice model (about 310 MB)
    voices-v1.0.bin      every voice's character (about 27 MB)
"""

from __future__ import annotations

import importlib.util
import io
import platform
import re
import shutil
import subprocess
import threading
import time
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from wordvault.editor.piper_voice import split_sentences

# ---------------------------------------------------------------------------
# Finding Kokoro and its files
# ---------------------------------------------------------------------------

DEFAULT_KOKORO_DIR = Path.home() / "kokoro"

MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"

#: Where tools/install_kokoro.py fetches the two files from.
DOWNLOAD_BASE = ("https://github.com/thewh1teagle/kokoro-onnx/releases/"
                 "download/model-files-v1.0/")

#: Kokoro always produces sound at this many samples per second.
SAMPLE_RATE = 24000

#: The voice used until the writer picks another in Settings.
DEFAULT_VOICE = "bm_george"

#: The English voices that ship in voices-v1.0.bin, with plain names
#: for the Settings list.  The id's first letter is the accent
#: (a = American, b = British) and its second the speaker (f/m).
ENGLISH_VOICES = {
    "bm_george": "George (British, male)",
    "bm_daniel": "Daniel (British, male)",
    "bm_fable": "Fable (British, male)",
    "bm_lewis": "Lewis (British, male)",
    "bf_alice": "Alice (British, female)",
    "bf_emma": "Emma (British, female)",
    "bf_isabella": "Isabella (British, female)",
    "bf_lily": "Lily (British, female)",
    "am_michael": "Michael (American, male)",
    "am_fenrir": "Fenrir (American, male)",
    "am_adam": "Adam (American, male)",
    "am_echo": "Echo (American, male)",
    "am_eric": "Eric (American, male)",
    "am_liam": "Liam (American, male)",
    "am_onyx": "Onyx (American, male)",
    "am_puck": "Puck (American, male)",
    "af_heart": "Heart (American, female)",
    "af_bella": "Bella (American, female)",
    "af_nicole": "Nicole (American, female)",
    "af_sarah": "Sarah (American, female)",
    "af_sky": "Sky (American, female)",
    "af_nova": "Nova (American, female)",
    "af_river": "River (American, female)",
    "af_alloy": "Alloy (American, female)",
    "af_aoede": "Aoede (American, female)",
    "af_jessica": "Jessica (American, female)",
    "af_kore": "Kore (American, female)",
}


def voice_language(voice: str) -> str:
    """The pronunciation a voice was trained for: British voices
    (ids starting with "b") sound right only with British phonemes."""
    return "en-gb" if voice.startswith("b") else "en-us"


def package_available() -> bool:
    """Is the kokoro-onnx Python package installed?"""
    return importlib.util.find_spec("kokoro_onnx") is not None


def kokoro_files(folder: Path | str | None = None) -> tuple[Path, Path]:
    """Where the model and voices files are expected to be."""
    folder = Path(folder or DEFAULT_KOKORO_DIR).expanduser()
    return folder / MODEL_FILE, folder / VOICES_FILE


def what_is_missing(folder: Path | str | None = None) -> str | None:
    """None when Kokoro is ready to read; otherwise a short phrase
    naming the first thing that is missing, for Settings and the
    status bar to show."""
    if not package_available():
        return "the kokoro-onnx package"
    model, voices = kokoro_files(folder)
    if not model.is_file():
        return f"the voice model ({MODEL_FILE})"
    if not voices.is_file():
        return f"the voices file ({VOICES_FILE})"
    if not player_available():
        return "a sound player (sudo apt install alsa-utils)"
    return None


def player_available() -> bool:
    """Can this machine play sound the way we play it?"""
    if platform.system() == "Windows":
        return True                      # winsound is standard library
    return shutil.which("aplay") is not None


def rate_to_speed(rate: float) -> float:
    """Qt's rate (-1 slow .. 0 normal .. +1 fast) -> Kokoro's speed
    (0.5 half pace .. 1.0 natural .. 1.5 brisk).  Settings stores a
    percent and the window hands it over on Qt's scale; unlike Piper,
    Kokoro takes the percent almost as it stands."""
    percent = 100 + rate * 100
    percent = max(50.0, min(150.0, percent))
    return round(percent / 100.0, 2)


# ---------------------------------------------------------------------------
# Making text speakable
# ---------------------------------------------------------------------------

# Abbreviations the voice should say as full words.  The key is the
# abbreviation in lower case without its period.  Only the unambiguous
# ones are here; "Gen." or "Col." could be a rank as well as a book,
# so they are left for the voice to read as written.
_SPOKEN = {
    "matt": "Matthew", "mt": "Matthew", "mk": "Mark", "lk": "Luke",
    "jn": "John", "rom": "Romans", "cor": "Corinthians",
    "gal": "Galatians", "eph": "Ephesians", "phil": "Philippians",
    "thess": "Thessalonians", "tim": "Timothy", "heb": "Hebrews",
    "jas": "James", "pet": "Peter", "rev": "Revelation",
    "exod": "Exodus", "lev": "Leviticus", "deut": "Deuteronomy",
    "josh": "Joshua", "judg": "Judges", "sam": "Samuel", "kgs": "Kings",
    "chr": "Chronicles", "chron": "Chronicles", "neh": "Nehemiah",
    "ps": "Psalm", "pss": "Psalms", "psa": "Psalm", "prov": "Proverbs",
    "eccl": "Ecclesiastes", "isa": "Isaiah", "jer": "Jeremiah",
    "lam": "Lamentations", "ezek": "Ezekiel", "dan": "Daniel",
    "hos": "Hosea", "obad": "Obadiah", "mic": "Micah", "hab": "Habakkuk",
    "zeph": "Zephaniah", "hag": "Haggai", "zech": "Zechariah",
    "mal": "Malachi",
    "cf": "compare", "vs": "versus", "e.g": "for example",
    "i.e": "that is", "viz": "namely", "ch": "chapter",
    "chap": "chapter", "chs": "chapters", "vv": "verses",
    "vol": "volume", "approx": "approximately",
}

# An abbreviation followed by its period: "Matt." "e.g." "cf."
_ABBREVIATED = re.compile(r"\b([A-Za-z]+(?:\.[A-Za-z]+)?)\.")

# "Rev." is Revelation before a chapter number but Reverend before a
# name, so it is only expanded when a digit follows.
_NEEDS_NUMBER = {"rev", "dan", "mal", "hab", "sam", "tim", "pet", "mic",
                 "ps", "ch", "chap", "chs", "vol"}

# A chapter-and-verse reference such as 24:3 or 6:12-17.  The ending
# keeps clock times ("10:30 a.m.", "6:15 pm") from being read as verses.
_CHAPTER_VERSE = re.compile(
    r"\b(\d{1,3}):(\d{1,3})\b(?!\s*(?:[ap]\.?m\b|o'clock))", re.IGNORECASE)


def speech_text(sentence: str) -> str:
    """The sentence as it should be SPOKEN: abbreviations opened out
    into words and line breaks folded into spaces.  The reading light
    still uses the original text, so this may change length freely.

        "See Matt. 24:3, cf. Joel 2:31."
     -> "See Matthew 24, verse 3, compare Joel 2, verse 31."
    """
    def open_out(match: re.Match) -> str:
        word = match.group(1)
        spoken = _SPOKEN.get(word.lower())
        if spoken is None:
            return match.group(0)             # not one of ours
        if word.lower() in _NEEDS_NUMBER:
            rest = match.string[match.end():].lstrip()
            if not rest[:1].isdigit():
                return match.group(0)         # "Rev. Smith", "Dan. said"
        return spoken

    text = " ".join(sentence.split())
    text = _ABBREVIATED.sub(open_out, text)
    # "24:3" read bare comes out as "twenty four three"; a listener
    # follows "24, verse 3" far more easily.
    text = _CHAPTER_VERSE.sub(r"\1, verse \2", text)
    return text


# ---------------------------------------------------------------------------
# Turning Kokoro's sound into bytes a player understands
# ---------------------------------------------------------------------------

def silence(seconds: float) -> bytes:
    """That much quiet, as 16-bit mono sound at SAMPLE_RATE."""
    return b"\0\0" * int(SAMPLE_RATE * seconds)


#: The breath after a sentence, and the longer one after a paragraph.
SENTENCE_PAUSE = 0.28
PARAGRAPH_PAUSE = 0.65


class KokoroSynth:
    """The loaded Kokoro model: text in, sound bytes out.

    Loading takes a second or two and a few hundred megabytes, so one
    instance is kept per model file for the life of the program (see
    ``get_synth``).  ``speak`` may be called from a worker thread.
    """

    def __init__(self, model: Path, voices: Path) -> None:
        # Imported here, not at the top: WordVault must start and run
        # for people who never installed Kokoro.
        from kokoro_onnx import Kokoro

        self._kokoro = Kokoro(str(model), str(voices))

    def speak(self, text: str, voice: str, speed: float) -> bytes:
        """One sentence as 16-bit mono sound at SAMPLE_RATE."""
        import numpy as np

        samples, _rate = self._kokoro.create(
            text, voice=voice, speed=speed, lang=voice_language(voice))
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        # A very short fade at each end, so a sentence never starts or
        # stops with a click where it meets the quiet around it.
        fade = min(len(samples) // 2, SAMPLE_RATE // 200)     # 5 ms
        if fade:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            samples[:fade] *= ramp
            samples[-fade:] *= ramp[::-1]
        # Kokoro gives numbers between -1 and 1; sound cards want
        # whole numbers between -32768 and 32767.
        return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


_synths: dict[tuple[str, str], KokoroSynth] = {}
_synths_lock = threading.Lock()


def get_synth(model: Path, voices: Path) -> KokoroSynth:
    """The shared KokoroSynth for these files, loaded on first use."""
    key = (str(model), str(voices))
    with _synths_lock:
        if key not in _synths:
            _synths[key] = KokoroSynth(model, voices)
        return _synths[key]


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
#
# A player takes sentences one after another through play() and tells
# the caller, through the ``started`` callback, the moment each one
# becomes audible (that is when the reading light should move).
#
#     player.play(sound, started)   queue/play one sentence
#     player.finish()               block until everything has sounded
#     player.stop()                 silence, at once (any thread)

class StreamPlayer:
    """Linux: one ``aplay`` for the whole reading, fed raw sound.

    Because every sentence goes down the same pipe, they join without
    a gap.  The price is that sound is written a second or so before
    it is heard, so this class keeps its own clock of when each
    sentence will actually reach the speakers.
    """

    #: Bytes handed to aplay at a time (about 85 ms of sound), small
    #: enough that stop() and the reading light stay prompt.
    CHUNK = 4096

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._stopped = threading.Event()
        # The time (time.monotonic) at which the sound written so far
        # will have finished playing.
        self._audible_until = 0.0

    def _open(self) -> subprocess.Popen:
        if self._proc is None:
            self._proc = subprocess.Popen(
                ["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                 "-r", str(SAMPLE_RATE), "-c", "1", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return self._proc

    def play(self, sound: bytes, started: Callable[[], None]) -> None:
        proc = self._open()
        # This sentence is heard when the ones before it have finished,
        # or right now if the speakers have already fallen silent.
        begins = max(time.monotonic(), self._audible_until)
        self._audible_until = begins + len(sound) / (2 * SAMPLE_RATE)
        announced = False
        try:
            for offset in range(0, len(sound), self.CHUNK):
                if self._stopped.is_set():
                    return
                if not announced and time.monotonic() >= begins:
                    started()
                    announced = True
                # Blocks while aplay's buffer is full, which is what
                # keeps us only a little ahead of the speakers.
                proc.stdin.write(sound[offset:offset + self.CHUNK])
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            if self._stopped.is_set():
                return
            raise RuntimeError(f"the sound player stopped: {exc}") from exc
        # A short sentence can be written whole before its turn comes;
        # wait for that turn before moving the reading light.
        if not announced:
            self._stopped.wait(max(0.0, begins - time.monotonic()))
            if not self._stopped.is_set():
                started()

    def finish(self) -> None:
        """Let the last of the sound out, then close the player."""
        proc = self._proc
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        # Wait in short steps so stop() can still cut in.
        while proc.poll() is None and not self._stopped.is_set():
            self._stopped.wait(0.05)

    def stop(self) -> None:
        self._stopped.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()


class SentencePlayer:
    """Windows: each sentence played from memory with ``winsound``.

    winsound cannot take a continuous stream, so here a sentence is
    wrapped as a WAV in memory and played to its end before the next.
    """

    def __init__(self) -> None:
        self._stopped = threading.Event()

    def play(self, sound: bytes, started: Callable[[], None]) -> None:
        if self._stopped.is_set():
            return
        import winsound

        # Build a complete WAV file in memory around the raw sound.
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(sound)
        started()
        winsound.PlaySound(buffer.getvalue(), winsound.SND_MEMORY)

    def finish(self) -> None:
        pass                              # play() already waited

    def stop(self) -> None:
        self._stopped.set()
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)


def make_player():
    """The right player for this operating system."""
    return SentencePlayer() if platform.system() == "Windows" else StreamPlayer()


# ---------------------------------------------------------------------------
# The reading thread
# ---------------------------------------------------------------------------

class KokoroReader(QThread):
    """Reads one text, sentence by sentence, then exits.

    ``speak`` is any function that turns a sentence into sound bytes
    (the real one loads Kokoro; tests pass a fake).  ``player`` is a
    StreamPlayer, a SentencePlayer or a test stand-in.
    """

    sentence_started = pyqtSignal(int, int)       # start, length in text
    problem = pyqtSignal(str)

    #: How many sentences are prepared ahead of the one being spoken.
    #: More than one, because a short sentence gives too little time to
    #: prepare a long one that follows it.
    AHEAD = 3

    def __init__(self, speak: Callable[[str], bytes], text: str,
                 player, parent=None) -> None:
        super().__init__(parent)
        self._speak = speak
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
        # One helper thread prepares sentences in order while the
        # earlier ones play.
        ahead = ThreadPoolExecutor(max_workers=1)
        try:
            self._read_all(ahead, spans)
            if not self._stop.is_set():
                self._player.finish()
        except Exception as exc:  # noqa: BLE001 -- shown, never crashed over
            if not self._stop.is_set():
                self.problem.emit(str(exc) or exc.__class__.__name__)
            self._player.stop()
        finally:
            # Do not wait for a sentence still being prepared: Stop
            # must feel instant.  Its result is simply thrown away.
            ahead.shutdown(wait=False, cancel_futures=True)

    def _pause_after(self, index: int, spans) -> bytes:
        """The quiet that follows sentence ``index``: longer when the
        next sentence begins a new paragraph, none after the last."""
        if index + 1 >= len(spans):
            return silence(0.1)
        start, length = spans[index]
        gap = self._text[start + length:spans[index + 1][0]]
        return silence(PARAGRAPH_PAUSE if "\n" in gap else SENTENCE_PAUSE)

    def _wait_for(self, future) -> bytes | None:
        """The prepared sound, or None if Stop was pressed first.
        Waits in short steps so Stop never has to sit through a long
        sentence being prepared."""
        while not self._stop.is_set():
            try:
                return future.result(timeout=0.1)
            except FutureTimeout:
                continue
        return None

    def _read_all(self, ahead: ThreadPoolExecutor, spans) -> None:
        pending: deque = deque()          # sounds being prepared, in order
        next_to_request = 0

        def top_up() -> None:
            """Keep AHEAD sentences in preparation."""
            nonlocal next_to_request
            while next_to_request < len(spans) and len(pending) < self.AHEAD:
                start, length = spans[next_to_request]
                sentence = speech_text(self._text[start:start + length])
                pending.append(ahead.submit(self._speak, sentence))
                next_to_request += 1

        top_up()
        for index, (start, length) in enumerate(spans):
            if self._stop.is_set():
                return
            sound = self._wait_for(pending.popleft())
            if sound is None:
                return                            # stopped while waiting
            top_up()
            self._player.play(
                sound + self._pause_after(index, spans),
                # Called by the player when this sentence is audible.
                lambda s=start, n=length: self.sentence_started.emit(s, n),
            )


# ---------------------------------------------------------------------------
# The engine the window talks to
# ---------------------------------------------------------------------------

class KokoroEngine(QObject):
    """Read Aloud through Kokoro; see the module docstring for the
    surface it offers the window."""

    #: (word, utterance, start, length) -- same shape as
    #: QTextToSpeech.sayingWord, but once per sentence.
    sayingWord = pyqtSignal(str, int, int, int)
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, model: Path, voices: Path, voice: str = DEFAULT_VOICE,
                 parent=None) -> None:
        super().__init__(parent)
        self._model = Path(model)
        self._voices = Path(voices)
        self._voice = voice
        self._rate = 0.0
        self._reader: KokoroReader | None = None
        # Tests replace these two to run without Kokoro or a sound card.
        self._make_player = make_player
        self._speak_factory = self._default_speak

    # --- the QTextToSpeech-shaped surface ---------------------------------

    @property
    def speaking(self) -> bool:
        return self._reader is not None and self._reader.isRunning()

    def setRate(self, rate: float) -> None:
        """Qt's -1..+1; takes effect at the next say()."""
        self._rate = float(rate)

    def say(self, text: str) -> None:
        self.stop()
        reader = KokoroReader(self._speak_factory(), text,
                              self._make_player(), self)
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

    def _default_speak(self) -> Callable[[str], bytes]:
        """A function that speaks one sentence in the chosen voice at
        the chosen pace.  The model is loaded inside it, on the worker
        thread, so the window never freezes while Kokoro wakes up."""
        model, voices, voice = self._model, self._voices, self._voice
        speed = rate_to_speed(self._rate)

        def speak(sentence: str) -> bytes:
            return get_synth(model, voices).speak(sentence, voice, speed)

        return speak

    def _on_sentence(self, start: int, length: int) -> None:
        self.sayingWord.emit("", 0, start, length)

    def _on_reader_finished(self) -> None:
        # Only the reader that is current may announce the end; an old
        # one finishing late must not switch the button back.
        if self.sender() is not self._reader:
            return
        self._reader = None
        self.finished.emit()
