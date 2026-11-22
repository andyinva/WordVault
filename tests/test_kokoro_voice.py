"""
Tests for editor/kokoro_voice.py without Kokoro or a sound card.

A fake "speak" function stands in for the voice model (it returns a
little silence for every sentence and remembers what it was asked to
say), and a fake player records what it was given instead of making
sound.  Together they let the whole reading pipeline (split, prepare
ahead, play, signal, stop) run headless.  The real StreamPlayer is
tested against a pretend ``aplay`` that simply saves what it is fed.
"""

from __future__ import annotations

import os
import stat
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no display needed
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.editor import kokoro_voice as kv  # noqa: E402
from wordvault.editor import piper_voice as pv  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """One QApplication for the module (Qt allows only one)."""
    return QApplication.instance() or QApplication([])


def wait_until(qapp, condition, timeout=15.0) -> bool:
    """Pump Qt events until condition() is true or time runs out, so
    the worker thread's queued signals reach their slots."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


# --------------------------------------------------------------- pure --

def test_abbreviations_do_not_end_a_sentence():
    text = ("In Matt. 24 he speaks. See cf. Joel 2:31 and Rev. 6:12. "
            "W. Wrede wrote in 1904. It took approx. ten years. Dr. Smith "
            "agreed.")
    pieces = [text[s:s + n] for s, n in pv.split_sentences(text)]
    assert pieces == [
        "In Matt. 24 he speaks.",
        "See cf. Joel 2:31 and Rev. 6:12.",
        "W. Wrede wrote in 1904.",
        "It took approx. ten years.",
        "Dr. Smith agreed.",
    ]


def test_a_line_break_still_ends_a_sentence_after_an_abbreviation():
    # A heading or list line that happens to end in "etc." or "v."
    text = "Chapter heading, part v.\nThe body begins here."
    pieces = [text[s:s + n] for s, n in pv.split_sentences(text)]
    assert pieces == ["Chapter heading, part v.", "The body begins here."]


@pytest.mark.parametrize("written, spoken", [
    ("See Matt. 24:3, cf. Joel 2:31.",
     "See Matthew 24, verse 3, compare Joel 2, verse 31."),
    ("In 1 Cor. 15 and Rev. 6:12 we read.",
     "In 1 Corinthians 15 and Revelation 6, verse 12 we read."),
    # "Rev." before a name is a title, not the book: left alone.
    ("The Rev. Smith spoke at 10:30 a.m. today.",
     "The Rev. Smith spoke at 10:30 a.m. today."),
    ("Line one\nline two", "Line one line two"),
    ("Nothing to change here.", "Nothing to change here."),
])
def test_speech_text(written, spoken):
    assert kv.speech_text(written) == spoken


@pytest.mark.parametrize("rate, speed", [
    (0.0, 1.0),       # 100%: the natural pace
    (-0.3, 0.7),      # 70%
    (0.5, 1.5),       # 150%
    (-1.0, 0.5),      # clamped to the Settings range
    (1.0, 1.5),
])
def test_rate_to_speed(rate, speed):
    assert kv.rate_to_speed(rate) == speed


def test_voice_language_follows_the_accent():
    assert kv.voice_language("bm_george") == "en-gb"
    assert kv.voice_language("am_michael") == "en-us"
    assert kv.DEFAULT_VOICE in kv.ENGLISH_VOICES


def test_what_is_missing_names_each_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(kv, "package_available", lambda: False)
    assert "package" in kv.what_is_missing(tmp_path)
    monkeypatch.setattr(kv, "package_available", lambda: True)
    assert kv.MODEL_FILE in kv.what_is_missing(tmp_path)
    (tmp_path / kv.MODEL_FILE).write_bytes(b"")
    assert kv.VOICES_FILE in kv.what_is_missing(tmp_path)
    (tmp_path / kv.VOICES_FILE).write_bytes(b"")
    monkeypatch.setattr(kv, "player_available", lambda: False)
    assert "player" in kv.what_is_missing(tmp_path)
    monkeypatch.setattr(kv, "player_available", lambda: True)
    assert kv.what_is_missing(tmp_path) is None


# --------------------------------------------------------------- fakes --

class FakeVoice:
    """Stands in for Kokoro: remembers each sentence, returns 10 ms of
    silence for it (after an optional delay, to imitate a slow model)."""

    def __init__(self, delay=0.0, fail=False):
        self.said = []
        self.delay = delay
        self.fail = fail

    def __call__(self, sentence: str) -> bytes:
        if self.fail:
            raise RuntimeError("model would not load")
        time.sleep(self.delay)
        self.said.append(sentence)
        return kv.silence(0.01)


class RecordingPlayer:
    """Stands in for the sound card: counts sentences and notes the
    length of each, playing instantly (or slowly, so stop() has
    something to interrupt)."""

    def __init__(self, delay=0.0):
        self.lengths = []
        self.delay = delay
        self.stopped = False
        self.finished = False

    def play(self, sound, started):
        started()
        self.lengths.append(len(sound))
        end = time.monotonic() + self.delay
        while time.monotonic() < end and not self.stopped:
            time.sleep(0.01)

    def finish(self):
        self.finished = True

    def stop(self):
        self.stopped = True


def make_engine(voice, player):
    """A KokoroEngine wired to the fakes instead of the real thing."""
    engine = kv.KokoroEngine("model.onnx", "voices.bin")
    engine._speak_factory = lambda: voice
    engine._make_player = lambda: player
    return engine


# ------------------------------------------------------------- reading --

def test_reader_reads_every_sentence_in_order(qapp):
    text = "One sentence. See Matt. 24 there!\n\nA new paragraph?"
    voice, player = FakeVoice(), RecordingPlayer()
    reader = kv.KokoroReader(voice, text, player)
    starts, problems, done = [], [], []
    reader.sentence_started.connect(lambda s, n: starts.append(text[s:s + n]))
    reader.problem.connect(problems.append)
    reader.finished.connect(lambda: done.append(True))
    reader.start()
    assert wait_until(qapp, lambda: done)
    assert problems == []
    # The reading light follows the text as written...
    assert starts == ["One sentence.", "See Matt. 24 there!",
                      "A new paragraph?"]
    # ...while the voice is handed the abbreviation opened out.
    assert voice.said == ["One sentence.", "See Matthew 24 there!",
                          "A new paragraph?"]
    assert player.finished
    # The pause before a new paragraph is longer than between sentences.
    assert player.lengths[1] > player.lengths[0]


def test_engine_stop_cuts_reading_short(qapp):
    text = ". ".join(f"Sentence number {i}" for i in range(1, 30)) + "."
    engine = make_engine(FakeVoice(), RecordingPlayer(delay=0.3))
    heard, done = [], []
    engine.sayingWord.connect(lambda w, u, s, n: heard.append(text[s:s + n]))
    engine.finished.connect(lambda: done.append(True))
    engine.say(text)
    assert wait_until(qapp, lambda: len(heard) >= 2)
    assert engine.speaking
    engine.stop()
    assert wait_until(qapp, lambda: done, timeout=5.0)
    assert not engine.speaking
    assert len(heard) < 29          # it did not read to the end


def test_stop_does_not_wait_for_a_slow_voice(qapp):
    # The model takes 2 s per sentence; Stop must still return at once.
    engine = make_engine(FakeVoice(delay=2.0), RecordingPlayer())
    engine.say("A slow sentence. And another.")
    assert wait_until(qapp, lambda: engine.speaking)
    began = time.monotonic()
    engine.stop()
    assert time.monotonic() - began < 1.0


def test_engine_reports_a_voice_that_will_not_load(qapp):
    engine = make_engine(FakeVoice(fail=True), RecordingPlayer())
    failures, done = [], []
    engine.failed.connect(failures.append)
    engine.finished.connect(lambda: done.append(True))
    engine.say("Hello there.")
    assert wait_until(qapp, lambda: done)
    assert failures == ["model would not load"]


# ------------------------------------------------------- stream player --

@pytest.mark.skipif(sys.platform == "win32", reason="aplay is Linux only")
def test_stream_player_sends_one_unbroken_stream(tmp_path, monkeypatch):
    # A pretend aplay: copies whatever it is fed into a file.
    captured = tmp_path / "captured.raw"
    fake = tmp_path / "aplay"
    fake.write_text(f"#!/bin/sh\ncat > '{captured}'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    player = kv.StreamPlayer()
    first, second = b"\x01\x00" * 6000, b"\x02\x00" * 6000    # 0.25 s each
    order = []
    began = time.monotonic()
    player.play(first, lambda: order.append(("first", time.monotonic())))
    player.play(second, lambda: order.append(("second", time.monotonic())))
    player.finish()

    # Both sentences went down the same pipe, in order, nothing between.
    assert captured.read_bytes() == first + second
    assert [name for name, _ in order] == ["first", "second"]
    # The second sentence was announced when the first had finished
    # sounding (0.25 s in), not when it was merely written.
    assert order[1][1] - began >= 0.24
