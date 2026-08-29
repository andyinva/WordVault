"""
provenance.py — the writer's evidence: a document's construction story.

The vault has been keeping the record all along — append-only
revisions with timestamps, the editing clock, the spelling log.  This
module reads that record back as a PROVENANCE REPORT: documentation a
writer can print to show how a document actually grew.  Four kinds of
evidence tell the story:

* GROWTH   — the word count session by session; human writing has an
             unmistakable shape (bursts, plateaus, deletions, rework).
* LABOR    — the editing clock's measured active time.
* IMPERFECTION — real misspellings, corrected along the way, each with
             a timestamp; the most human evidence there is.
* ARRIVAL  — how text entered: accumulated typing-sized steps, or
             large single arrivals (imports, pastes).  The report
             shows both honestly; its credibility comes from hiding
             nothing.

Everything here is pure — plain lists in, a Markdown string out — so
it is tested headless; the window supplies the data from the store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

#: A pause longer than this between revisions starts a new session.
SESSION_GAP_MINUTES = 30

#: A single revision that adds more than this many words is reported
#: as a "large arrival" (import, paste, or one very long pour).
LARGE_ARRIVAL_WORDS = 200


def word_count(text: str) -> int:
    return len(text.split())


def _parse(iso_utc: str) -> datetime:
    dt = datetime.fromisoformat(iso_utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local(iso_utc: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return _parse(iso_utc).astimezone().strftime(fmt)


@dataclass
class Session:
    """One sitting: consecutive revisions with no long pause between."""
    start_utc: str
    end_utc: str
    revisions: int
    words_start: int          # words BEFORE the sitting began
    words_end: int            # words when it ended


def sessions(revisions: list[tuple[str, int]]) -> list[Session]:
    """Group (created_utc, words) revisions into sittings.

    Consecutive revisions closer than SESSION_GAP_MINUTES belong to
    one session; a longer silence starts the next.  words_start is the
    count BEFORE the session (0 for the first), so each session's net
    contribution is words_end - words_start.
    """
    result: list[Session] = []
    previous_words = 0
    current: Session | None = None
    for created, words in revisions:
        if current is not None:
            gap = (_parse(created) - _parse(current.end_utc)).total_seconds()
            if gap <= SESSION_GAP_MINUTES * 60:
                current.end_utc = created
                current.revisions += 1
                current.words_end = words
                continue
            previous_words = current.words_end
            result.append(current)
        current = Session(created, created, 1, previous_words, words)
    if current is not None:
        result.append(current)
    return result


def large_arrivals(revisions: list[tuple[str, int]],
                   threshold: int = LARGE_ARRIVAL_WORDS
                   ) -> list[tuple[str, int]]:
    """(created_utc, words_added) for every revision whose net growth
    exceeded the threshold — the imports, pastes, and long pours."""
    arrivals = []
    previous = 0
    for created, words in revisions:
        if words - previous > threshold:
            arrivals.append((created, words - previous))
        previous = words
    return arrivals


def format_duration(seconds: int) -> str:
    hours, minutes = seconds // 3600, (seconds % 3600) // 60
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def build_report(
    *,
    title: str,
    created_utc: str,
    revisions: list[tuple[str, int]],       # (created_utc, words), oldest first
    editing_seconds: int,
    spelling_rows: list[tuple[str, str, str]],  # (created_utc, typed, corrected)
    program_version: str = "",
    style_block: str | None = None,     # stylometric consistency, pre-worded
    pastes: list[tuple] = (),           # (created_utc, words, snippet, comment)
) -> str:
    """The Provenance Report as Markdown, ready to save or print."""
    lines: list[str] = []
    say = lines.append

    say(f"# Provenance Report — {title}")
    say("")
    stamp = datetime.now().astimezone().strftime("%B %d, %Y at %H:%M")
    version = f" by WordVault {program_version}" if program_version else ""
    say(f"Generated {stamp}{version} from the document's own history.")
    say("")

    # --- the document ---------------------------------------------------
    current_words = revisions[-1][1] if revisions else 0
    sits = sessions(revisions)
    active_days = {s.start_utc[:10] for s in sits}
    say("## The document")
    say("")
    say(f"- Created: {_local(created_utc)}")
    say(f"- Revisions preserved: {len(revisions)}")
    say(f"- Words today: {current_words:,}")
    say(f"- Writing sessions: {len(sits)}, across "
        f"{len(active_days)} different day(s)")
    if editing_seconds:
        say(f"- Active writing time (hands on keys): "
            f"{format_duration(editing_seconds)}")
    say("")

    # --- growth, session by session -------------------------------------
    say("## The sessions")
    say("")
    say("Each line is one sitting — revisions separated by less than "
        f"{SESSION_GAP_MINUTES} minutes of silence.")
    say("")
    say("| Session | Began | Ended | Saves | Words | Net |")
    say("|---|---|---|---|---|---|")
    for i, s in enumerate(sits, 1):
        net = s.words_end - s.words_start
        say(f"| {i} | {_local(s.start_utc)} | "
            f"{_local(s.end_utc, '%H:%M')} | {s.revisions} | "
            f"{s.words_start:,} → {s.words_end:,} | {net:+,} |")
    say("")

    # --- how the text arrived --------------------------------------------
    say("## How the text arrived")
    say("")
    arrivals = large_arrivals(revisions)
    small = max(len(revisions) - len(arrivals) - 1, 0)
    say(f"Of {len(revisions)} preserved revisions, {small} grew by "
        f"typing-sized steps (under {LARGE_ARRIVAL_WORDS} words each).")
    if arrivals:
        say("")
        say(f"{len(arrivals)} revision(s) brought more than "
            f"{LARGE_ARRIVAL_WORDS} words at once — imports, pasted "
            "material, or a long uninterrupted pour:")
        say("")
        for created, added in arrivals:
            say(f"- {_local(created)}: {added:+,} words in one step")
    if pastes:
        # The writer's own memory of each arrival: what it was and
        # where it came from, asked at the moment of pasting.
        say("")
        say("Pasted material, in the writer's own words:")
        say("")
        for created, words, snippet, comment in pastes:
            note = (f" — “{comment}”" if comment
                    else f" (“{snippet[:40]}…”, no note)")
            say(f"- {_local(created)}: {words} words pasted{note}")
    say("")

    # --- stylometric consistency (optional; worded by the caller) --------
    if style_block:
        say("## Stylometric consistency")
        say("")
        say(style_block)
        say("")

    # --- the statement ----------------------------------------------------
    say("## Statement")
    say("")
    say("This report was assembled entirely from the document's "
        "revision history in the writer's vault. The vault is "
        "append-only by design: saving never overwrites an earlier "
        "state, and every revision listed above remains stored and "
        "can be reopened, compared, and read in the WordVault "
        "timeline. The growth, sessions, arrivals, and corrections "
        "reported here are the document's own record of its making.")
    if spelling_rows:
        say("")
        say("*The spelling corrections made while writing are "
            "recorded on the next page.*")
    say("")

    # --- the human record, LAST (page 2 of the printed report) -----------
    # Compact by request: the corrections flow inline, strung out to
    # the right (typed → corrected; typed → corrected; …) with one
    # date SPAN instead of a date per item — the evidence intact, the
    # report as small as it can be.  The section sits after the
    # Statement so everything else fits on the first page.
    say("## Corrections along the way")
    say("")
    if spelling_rows:
        import textwrap

        first = _local(spelling_rows[0][0], "%Y-%m-%d")
        last = _local(spelling_rows[-1][0], "%Y-%m-%d")
        span = first if first == last else f"{first} to {last}"
        say(f"{len(spelling_rows)} misspelling(s) made and corrected "
            f"({span}) — the record of real hands on real keys:")
        say("")
        flow = ";  ".join(f"{typed} → {corrected}"
                          for _created, typed, corrected in spelling_rows)
        say(textwrap.fill(flow, width=72))
    else:
        say("No spelling corrections were recorded for this document.")
    say("")
    return "\n".join(lines)
