"""
Headless tests for the Provenance Report (wordvault/provenance.py):
session grouping, arrival detection, and the report text itself — the
writer's evidence must be assembled correctly before it is believed.
Pure functions, no Qt.
"""

from wordvault.provenance import (
    Session,
    build_report,
    format_duration,
    large_arrivals,
    sessions,
    word_count,
)


def _t(day: int, hour: int, minute: int = 0) -> str:
    return f"2026-08-{day:02d}T{hour:02d}:{minute:02d}:00+00:00"


def test_word_count():
    assert word_count("three little words") == 3
    assert word_count("") == 0


def test_close_revisions_form_one_session():
    revs = [(_t(1, 9, 0), 100), (_t(1, 9, 10), 220), (_t(1, 9, 25), 300)]
    sits = sessions(revs)
    assert len(sits) == 1
    assert sits[0] == Session(_t(1, 9, 0), _t(1, 9, 25), 3, 0, 300)


def test_a_long_silence_starts_a_new_session():
    revs = [(_t(1, 9, 0), 100), (_t(1, 9, 10), 200),
            (_t(1, 14, 0), 250), (_t(2, 8, 0), 400)]
    sits = sessions(revs)
    assert len(sits) == 3
    # Each session's start knows the words BEFORE it began.
    assert sits[1].words_start == 200 and sits[1].words_end == 250
    assert sits[2].words_start == 250 and sits[2].words_end == 400


def test_large_arrivals_are_flagged_honestly():
    revs = [(_t(1, 9), 50), (_t(1, 10), 120),      # typing-sized
            (_t(1, 11), 900),                      # a paste or import
            (_t(1, 12), 950)]
    arrivals = large_arrivals(revs)
    assert arrivals == [(_t(1, 11), 780)]


def test_report_tells_the_whole_story():
    revs = [(_t(1, 9, 0), 100), (_t(1, 9, 20), 400),
            (_t(3, 19, 0), 800), (_t(3, 21, 0), 780)]
    report = build_report(
        title="The Judaic Logic of Matthew 24",
        created_utc=_t(1, 8, 55),
        revisions=revs,
        editing_seconds=7380,
        spelling_rows=[(_t(1, 9, 5), "jeprodising", "jeopardizing")],
        program_version="1.0",
    )
    assert "# Provenance Report — The Judaic Logic of Matthew 24" in report
    assert "Revisions preserved: 4" in report
    assert "Words today: 780" in report
    assert "2 h 3 min" in report                    # the editing clock
    assert "Writing sessions: 3" in report
    assert "jeprodising" in report and "jeopardizing" in report
    assert "append-only" in report                  # the statement
    # The 300-word arrival on day 1 and the 400-word one on day 3.
    assert report.count("words in one step") == 2
    # Deletions appear as negative net, honestly.
    assert "-20" in report


def test_report_survives_an_empty_document():
    report = build_report(
        title="Empty", created_utc=_t(1, 8), revisions=[],
        editing_seconds=0, spelling_rows=[])
    assert "Revisions preserved: 0" in report
    assert "No spelling corrections" in report


def test_style_block_joins_the_report_when_given():
    report = build_report(
        title="Essay", created_utc=_t(1, 8),
        revisions=[(_t(1, 9), 500)], editing_seconds=0,
        spelling_rows=[],
        style_block="Distance 0.84, verdict consistent.")
    assert "## Stylometric consistency" in report
    assert "Distance 0.84" in report
    # And the section sits before the Statement.
    assert report.index("Stylometric") < report.index("## Statement")


def test_format_duration():
    assert format_duration(7380) == "2 h 3 min"
    assert format_duration(240) == "4 min"


def test_corrections_sit_last_with_a_signpost():
    """Page-one economy: everything else precedes the corrections, and
    the Statement tells the reader where to find them."""
    report = build_report(
        title="Essay", created_utc=_t(1, 8),
        revisions=[(_t(1, 9), 500)], editing_seconds=60,
        spelling_rows=[(_t(1, 9, 5), "teh", "the")],
        style_block="Distance 0.9, consistent.")
    order = [report.index(h) for h in (
        "## The document", "## The sessions", "## How the text arrived",
        "## Stylometric consistency", "## Statement",
        "## Corrections along the way")]
    assert order == sorted(order)
    assert "recorded on the next page" in report


def test_pasted_material_speaks_in_the_writers_words():
    report = build_report(
        title="Essay", created_utc=_t(1, 8),
        revisions=[(_t(1, 9), 500)], editing_seconds=0,
        spelling_rows=[],
        pastes=[(_t(1, 9, 30), 54, "For behold, the Lord will come",
                 "Isaiah 66:15-22 from Bible Search Lite"),
                (_t(2, 10), 30, "and the wall of the city", "")])
    assert "Pasted material, in the writer's own words:" in report
    assert "54 words pasted — “Isaiah 66:15-22 from Bible Search "\
           "Lite”" in report
    # An uncommented paste is still shown, honestly, with its glimpse.
    assert "30 words pasted (“and the wall of the city…”, no note)" \
        in report
