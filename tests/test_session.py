from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from speedrun_solver.session import (
    RunSession,
    SessionError,
    load_session,
    save_session,
)


def test_session_persists_roster_rerolls_and_history(tmp_path: Path) -> None:
    path = tmp_path / "active-run.json"
    session = RunSession()
    session.start("dal", "1980s", team_rerolls=2, era_rerolls=1)
    session.set_candidates(["mark_aguire_dal_1980s"])
    session.take("mark_aguire_dal_1980s")
    session.advance_spin("MIA", "2000s")
    session.reroll_team("LAC")
    save_session(path, session)

    restored = load_session(path)
    assert restored.active
    assert restored.started_at is not None
    assert restored.finished_at is None
    assert restored.current_team == "LAC"
    assert restored.current_era == "2000s"
    assert restored.spin_open
    assert restored.team_rerolls == 1
    assert restored.era_rerolls == 1
    assert restored.roster == [{"id": "mark_aguire_dal_1980s"}]
    assert [event["event"] for event in restored.history] == [
        "start",
        "offer",
        "take",
        "next_spin",
        "team_reroll",
    ]


def test_session_end_clears_active_run_but_keeps_history() -> None:
    session = RunSession()
    session.start("DAL", "1980s", team_rerolls=1, era_rerolls=1)
    session.end(reason="policy")

    assert not session.active
    assert session.started_at is not None
    assert session.finished_at is not None
    assert session.chase_started_at is None
    assert session.chase_finished_at is None
    assert not session.clock_enabled
    assert session.result == "ended"
    assert session.current_team is None
    assert session.roster == []
    assert session.history[-1]["event"] == "end"
    assert session.history[-1]["reason"] == "policy"


def test_successful_completion_stops_timer_and_keeps_roster() -> None:
    session = RunSession()
    session.start_clock()
    session.start("GSW", "1960s", team_rerolls=1, era_rerolls=1)
    session.set_candidates(["winner"])
    session.take("winner")
    session.complete(success=True, final_score=110.25)

    assert not session.active
    assert session.result == "82-0"
    assert session.finished_at is not None
    assert session.chase_finished_at == session.finished_at
    assert session.clock_enabled
    assert not session.clock_running
    assert session.final_score == 110.25
    assert session.roster == [{"id": "winner"}]
    assert session.history[-1]["event"] == "complete"


def test_opt_in_clock_spans_multiple_ended_runs() -> None:
    session = RunSession()
    assert not session.clock_enabled
    session.start_clock()
    chase_started_at = session.chase_started_at

    session.start("UTA", "1990s", team_rerolls=1, era_rerolls=1)
    session.end(reason="policy")
    session.start("MIA", "2000s", team_rerolls=1, era_rerolls=1)

    assert session.chase_started_at == chase_started_at
    assert session.chase_finished_at is None
    assert session.clock_running
    assert session.run_number == 2


def test_new_chase_never_inherits_previous_100_percent_chance() -> None:
    session = RunSession()
    session.start("MIN", "2010s", team_rerolls=1, era_rerolls=1)
    session.record_chance(
        probability=1.0,
        relative_to_restart=999.0,
        continue_threshold=1.0,
        label="82-0 secured",
    )
    session.complete(success=True, final_score=110.0)

    session.start("LAL", "1980s", team_rerolls=1, era_rerolls=1)
    assert session.chance_history == []


def test_active_run_cleans_stale_completed_chase_entry() -> None:
    session = RunSession(active=True, run_number=22)
    session.chance_history = [
        {
            "run_number": 21,
            "probability": 1.0,
            "label": "picked Jimmy Butler",
        },
        {
            "run_number": 22,
            "probability": 0.019,
            "label": "opening spin",
        },
    ]

    assert session.remove_previous_completed_chase()
    assert session.chance_history == [
        {
            "run_number": 22,
            "probability": 0.019,
            "label": "opening spin",
        }
    ]


def test_reset_and_disable_clock_are_independent_of_run_state() -> None:
    session = RunSession()
    session.start_clock()
    session.start("MIN", "2010s", team_rerolls=1, era_rerolls=1)
    session.roster = [{"id": "winner"}]
    session.complete(success=True, final_score=110.0)
    session.reset_clock()

    assert session.result == "82-0"
    assert session.final_score == 110.0
    assert session.roster == [{"id": "winner"}]
    assert session.clock_elapsed_seconds == 0.0
    session.disable_clock()
    assert not session.clock_enabled
    assert not session.clock_running


def test_clock_can_pause_resume_and_persist(tmp_path: Path) -> None:
    session = RunSession()
    session.start_clock()
    session.clock_segment_started_at = (
        datetime.now(timezone.utc) - timedelta(seconds=2)
    ).isoformat()
    session.pause_clock()
    assert not session.clock_running
    assert session.clock_elapsed_seconds >= 1.9

    session.start_clock()
    assert session.clock_running
    path = tmp_path / "clock.json"
    save_session(path, session)
    restored = load_session(path)
    assert restored.clock_enabled
    assert restored.clock_running
    assert restored.clock_elapsed_seconds >= 1.9

def test_session_rejects_illegal_transitions() -> None:
    session = RunSession()
    with pytest.raises(SessionError, match="No active run"):
        session.take("anything")

    session.start("DAL", "1980s", team_rerolls=0, era_rerolls=0)
    with pytest.raises(SessionError, match="No TEAM rerolls"):
        session.reroll_team("LAC")
    with pytest.raises(SessionError, match="not in the active offer"):
        session.take("anything")


def test_next_spin_requires_previous_spin_to_be_resolved() -> None:
    session = RunSession()
    session.start("DAL", "1980s", team_rerolls=1, era_rerolls=1)
    with pytest.raises(SessionError, match="Resolve the current spin"):
        session.advance_spin("MIA", "2000s")

    session.set_candidates(["card"])
    session.take("card")
    session.advance_spin("MIA", "2000s")
    assert session.current_team == "MIA"
    assert session.current_era == "2000s"
    assert session.spin_open


def test_session_json_is_readable_and_versioned(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    save_session(path, RunSession())
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["active"] is False
