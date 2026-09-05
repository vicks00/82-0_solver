from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from speedrun_solver.importer import import_cards
from speedrun_solver.session import load_session

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "rankings_sample.json"


def test_cli_runs_with_offline_generated_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    import_cards(output_dir=data_dir, input_json=FIXTURE)
    state = {
        "roster": [
            {"id": "alpha_atl_2020s"},
            {"id": "bravo_atl_2020s"},
            {"id": "charlie_atl_2020s"},
            {"id": "delta_atl_2020s"},
        ],
        "candidates": [{"id": "echo_atl_2020s"}],
        "current_team": "ATL",
        "current_era": "2020s",
        "team_rerolls": 0,
        "era_rerolls": 0,
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "82_0_speedrun_solver.py"),
            "--state",
            str(state_path),
            "--cards",
            str(data_dir / "cards.csv"),
            "--team-era-metrics",
            str(data_dir / "team_era_metrics.json"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["candidate_options"][0]["id"] == "echo_atl_2020s"
    assert result["candidate_options"][0]["take_position"] == "C"
    assert result["candidate_options"][0]["82_0"] is False
    assert result["decision"].startswith("END RUN / START OVER")


def test_interactive_session_persists_and_resets_run(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    import_cards(output_dir=data_dir, input_json=FIXTURE)
    session_path = tmp_path / "speedrun-session.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "82_0_speedrun_solver.py"),
            "--session",
            str(session_path),
            "--cards",
            str(data_dir / "cards.csv"),
            "--team-era-metrics",
            str(data_dir / "team_era_metrics.json"),
        ],
        cwd=ROOT,
        input=(
            "start ATL 2020s 1 1\n"
            "offer alpha_atl_2020s\n"
            "take alpha_atl_2020s\n"
            "end\n"
            "quit\n"
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    session = load_session(session_path)

    assert "AWAIT PLAYER OFFER" in completed.stdout
    assert not session.active
    assert session.run_number == 1
    assert [event["event"] for event in session.history] == [
        "start",
        "offer",
        "take",
        "end",
    ]
