"""
Tests for editor/piper_voice.py without a real Piper or a sound card.

A tiny fake "piper" script stands in for the program: it speaks the
same protocol (--json-input lines in, WAV paths out), writing a
silent WAV per request.  A fake Player records what it was asked to
play instead of making sound.  Together they let the whole reading
pipeline (split, synthesize ahead, play, signal, stop) run headless.
"""

from __future__ import annotations

import os
import stat
import sys
import textwrap
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no display needed
from PyQt6.QtWidgets import QApplication  # noqa: E402

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
    return condition()


# --------------------------------------------------------------- pure --

def test_split_sentences_spans_and_trimming():
    text = "First one.  Second, \"quoted?\" Third!\n\nA new paragraph"
    spans = pv.split_sentences(text)
    pieces = [text[s:s + n] for s, n in spans]
    assert pieces == ["First one.", "Second, \"quoted?\"", "Third!",
                      "A new paragraph"]
    # Spans never include the whitespace between sentences.
    for s, n in spans:
        assert text[s] != " " and text[s + n - 1] != " "


def test_split_sentences_empty_and_whitespace():
    assert pv.split_sentences("") == []
    assert pv.split_sentences("   \n\n  ") == []


@pytest.mark.parametrize("rate, scale", [
    (0.0, 1.0),      # normal
    (0.5, 0.667),    # 150%: shorter phonemes
    (-0.5, 2.0),     # 50%: stretched
    (1.0, 0.667),    # clamped to the Settings range
    (-1.0, 2.0),
])
def test_rate_to_length_scale(rate, scale):
    assert pv.rate_to_length_scale(rate) == scale


def test_voice_display_name():
    assert pv.voice_display_name(Path("en_US-ryan-medium.onnx")) == "ryan (en_US, medium)"
    assert pv.voice_display_name(Path("en_GB-alan-low.onnx")) == "alan (en_GB, low)"
    assert pv.voice_display_name(Path("odd.onnx")) == "odd"


def test_list_voices_requires_the_json_sidecar(tmp_path):
    (tmp_path / "a.onnx").write_bytes(b"")
    (tmp_path / "a.onnx.json").write_text("{}")
    (tmp_path / "lonely.onnx").write_bytes(b"")          # no sidecar
    sub = tmp_path / "more"
    sub.mkdir()
    (sub / "b.onnx").write_bytes(b"")
    (sub / "b.onnx.json").write_text("{}")
    assert [v.name for v in pv.list_voices(tmp_path)] == ["a.onnx", "b.onnx"]
    assert pv.list_voices(tmp_path / "nowhere") == []


def test_find_piper_executable_layouts(tmp_path, monkeypatch):
    monkeypatch.setattr(pv.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pv.shutil, "which", lambda name: None)
    assert pv.find_piper_executable(tmp_path) is None
    (tmp_path / "piper").mkdir()
    exe = tmp_path / "piper" / "piper"
    exe.write_text("#!/bin/sh\n")
    assert pv.find_piper_executable(tmp_path) == exe


# --------------------------------------------------------------- fakes --

FAKE_PIPER = textwrap.dedent(r'''
    #!/usr/bin/env python3
    """Pretend Piper: --json-input lines in, silent WAV paths out."""
    import json, sys, wave, time
    args = sys.argv[1:]
    out_dir = args[args.index("--output_dir") + 1]
    n = 0
    for line in sys.stdin:
        n += 1
        text = json.loads(line)["text"]
        path = f"{out_dir}/{n}.wav"
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
            w.writeframes(b"\0\0" * 220)          # 10 ms of silence
        with open(f"{out_dir}/log.txt", "a") as log:
            log.write(text + "\n")
        print(path, flush=True)
''').lstrip()


@pytest.fixture
def fake_piper(tmp_path):
    """A folder laid out like a real Piper install, with a fake program."""
    folder = tmp_path / "piperhome"
    (folder / "piper").mkdir(parents=True)
    exe = folder / "piper" / "piper"
    exe.write_text(FAKE_PIPER)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    (folder / "en_US-test-medium.onnx").write_bytes(b"")
    (folder / "en_US-test-medium.onnx.json").write_text("{}")
    return folder


class RecordingPlayer:
    """Stands in for aplay/winsound: remembers files, plays instantly
    (or slowly, so stop() has something to interrupt)."""

    def __init__(self, delay=0.0):
        self.played = []
        self.delay = delay
        self.stopped = False

    def play(self, wav):
        self.played.append(Path(wav).read_bytes()[:4])   # "RIFF"
        end = time.monotonic() + self.delay
        while time.monotonic() < end and not self.stopped:
            time.sleep(0.01)

    def stop(self):
        self.stopped = True


@pytest.mark.skipif(sys.platform == "win32", reason="fake piper is a shell script")
def test_reader_reads_every_sentence_in_order(fake_piper, qapp):
    text = "One sentence. Two sentences! Three?"
    player = RecordingPlayer()
    reader = pv.PiperReader(fake_piper / "piper" / "piper",
                            fake_piper / "en_US-test-medium.onnx",
                            1.0, text, player)
    starts = []
    reader.sentence_started.connect(lambda s, n: starts.append(text[s:s + n]))
    problems = []
    reader.problem.connect(problems.append)
    done = []
    reader.finished.connect(lambda: done.append(True))
    reader.start()
    assert wait_until(qapp, lambda: done)
    assert problems == []
    assert starts == ["One sentence.", "Two sentences!", "Three?"]
    assert player.played == [b"RIFF"] * 3


@pytest.mark.skipif(sys.platform == "win32", reason="fake piper is a shell script")
def test_engine_stop_cuts_reading_short(fake_piper, qapp):
    text = ". ".join(f"Sentence number {i}" for i in range(1, 30)) + "."
    engine = pv.PiperEngine(fake_piper / "piper" / "piper",
                            fake_piper / "en_US-test-medium.onnx")
    player = RecordingPlayer(delay=0.3)
    engine._player = player
    heard = []
    engine.sayingWord.connect(lambda w, u, s, n: heard.append(text[s:s + n]))
    done = []
    engine.finished.connect(lambda: done.append(True))
    engine.say(text)
    assert wait_until(qapp, lambda: len(heard) >= 2)
    assert engine.speaking
    engine.stop()
    assert wait_until(qapp, lambda: done, timeout=5.0)
    assert not engine.speaking
    assert len(heard) < 29          # it did not read to the end


@pytest.mark.skipif(sys.platform == "win32", reason="fake piper is a shell script")
def test_engine_reports_a_broken_piper(fake_piper, qapp):
    broken = fake_piper / "piper" / "piper"
    broken.write_text("#!/bin/sh\nexit 3\n")      # dies at once
    engine = pv.PiperEngine(broken, fake_piper / "en_US-test-medium.onnx")
    engine._player = RecordingPlayer()
    failures = []
    engine.failed.connect(failures.append)
    done = []
    engine.finished.connect(lambda: done.append(True))
    engine.say("Hello there.")
    assert wait_until(qapp, lambda: done)
    assert failures and "Piper" in failures[0]
