from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from speedrun_solver.data import load_cards, load_metrics
from speedrun_solver.importer import import_cards
from speedrun_solver.webapp import AppService, attach_lifetime_watchdog, create_server

FIXTURE = Path(__file__).parent / "fixtures" / "rankings_sample.json"
ROOT = Path(__file__).resolve().parents[1]


def service(tmp_path: Path) -> AppService:
    data_dir = tmp_path / "data"
    import_cards(output_dir=data_dir, input_json=FIXTURE)
    return AppService(
        load_cards(data_dir / "cards.csv"),
        load_metrics(data_dir / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )


def test_browser_service_tracks_full_run_state(tmp_path: Path) -> None:
    app = service(tmp_path)
    opened = app.start("ATL", "2020s", team_rerolls=1, era_rerolls=1)

    assert opened["session"]["active"]
    assert opened["session"]["spin_open"]
    assert opened["session"]["started_at"] is not None
    assert opened["session"]["finished_at"] is None
    assert opened["session"]["chase_started_at"] is None
    assert opened["session"]["chase_finished_at"] is None
    assert not opened["session"]["clock_enabled"]
    assert opened["report"]["board"]["card_count"] == 7
    assert len(opened["report"]["candidate_options"]) == 6
    assert opened["report"]["candidate_options"][0]["id"] == "alpha_atl_2020s"
    assert opened["report"]["chance"]["probability"] >= 0
    assert opened["report"]["chance"]["health"] in {
        "strong",
        "healthy",
        "fragile",
        "critical",
    }
    assert len(opened["chance_history"]) == 2

    picked = app.take("alpha_atl_2020s")
    assert not picked["session"]["spin_open"]
    assert picked["roster"][0]["player"] == "Alpha Guard"
    assert picked["roster"][0]["assigned_position"] == "PG"
    assert picked["report"]["action"] == "NEXT_SPIN"
    assert picked["chance_history"][-1]["label"] == "picked Alpha Guard"

    next_spin = app.next_spin("ATL", "2020s")
    candidate_ids = {
        card["id"] for card in next_spin["report"]["candidate_options"]
    }
    assert "alpha_atl_2020s" not in candidate_ids
    assert next_spin["roster"][0]["player"] == "Alpha Guard"
    assert next_spin["session"]["team_rerolls"] == 1
    assert next_spin["session"]["era_rerolls"] == 1

    restored = service(tmp_path).state()
    assert restored["session"]["active"]
    assert restored["roster"][0]["id"] == "alpha_atl_2020s"

    ended = app.end("policy")
    assert not ended["session"]["active"]
    assert ended["session"]["finished_at"] is not None
    assert ended["session"]["result"] == "ended"
    assert ended["session"]["chase_finished_at"] is None
    assert ended["roster"] == []
    assert ended["history"][-1]["event"] == "end"

    running = app.start_clock()
    assert running["session"]["clock_enabled"]
    assert running["session"]["clock_running"]
    paused = app.pause_clock()
    assert not paused["session"]["clock_running"]
    reset = app.reset_clock()
    assert reset["session"]["clock_elapsed_seconds"] == 0.0
    disabled = app.disable_clock()
    assert not disabled["session"]["clock_enabled"]


def test_catalog_exposes_searchable_team_and_era_values(tmp_path: Path) -> None:
    catalog = service(tmp_path).catalog()
    assert catalog["teams"] == ["ATL"]
    assert catalog["eras"] == ["2020s"]
    assert catalog["valid_boards"] == [{"team": "ATL", "era": "2020s"}]


def test_successful_state_reports_secured_probability(tmp_path: Path) -> None:
    app = service(tmp_path)
    app.start("ATL", "2020s")
    app.session.roster = [{"id": "alpha_atl_2020s"}]
    app.session.complete(success=True, final_score=110.0)
    app._record_chance("82-0 secured")
    state = app.state()

    assert state["report"]["chance"]["probability"] == 1.0
    assert state["report"]["chance"]["health"] == "secured"
    assert state["session"]["result"] == "82-0"


def test_browser_probability_uses_actual_board_simulation(tmp_path: Path) -> None:
    app = AppService(
        load_cards(ROOT / "data" / "cards.csv"),
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )
    state = app.start("LAL", "1960s")
    chance = state["report"]["chance"]

    assert chance["simulation"]["method"] == (
        "paired stage-aware policy Monte Carlo"
    )
    assert chance["simulation"]["trials"] > 0
    assert 0 < chance["probability"] < 0.5


def test_offline_board_excludes_players_already_in_roster(
    tmp_path: Path,
) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )
    app.session.start("MIL", "2010s", team_rerolls=0, era_rerolls=1)
    app.session.roster = [{"id": "giannis_antetokounmpo_mil_2020s"}]

    app._populate_current_board()

    assert "giannis_antetokounmpo_mil_2010s" not in {
        candidate["id"] for candidate in app.session.candidates
    }


def test_current_board_chance_includes_recommended_pick(
    tmp_path: Path,
) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )
    app.session.start("PHI", "1960s", team_rerolls=1, era_rerolls=1)
    app.session.roster = [{"id": "elgin_baylor_lal_1960s"}]
    app.session.candidates = [
        {"id": card.id}
        for card in cards
        if card.team == "PHI" and card.era == "1960s" and card.playable
    ]

    before = app.state()
    assert before["report"]["recommended_card"]["player"] == "Wilt Chamberlain"
    assert before["report"]["chance"]["current_board"]
    projected_probability = before["report"]["projected_chance"]["probability"]
    assert before["report"]["chance"]["probability"] == projected_probability

    after = app.take(before["report"]["recommended_card"]["id"])
    assert after["report"]["chance"]["probability"] == projected_probability


def test_houston_policy_excludes_already_committed_player_names(
    tmp_path: Path,
) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )
    app.session.start("HOU", "2000s", team_rerolls=0, era_rerolls=1)
    app.session.roster = [
        {"id": "lebron_james_lal_2010s"},
        {"id": "james_harden_phi_2020s"},
    ]
    app.session.candidates = [
        {"id": card.id}
        for card in cards
        if card.team == "HOU" and card.era == "2000s" and card.playable
    ]
    report = app.state()["report"]

    assert report["action"] == "TAKE"
    assert report["recommended_card"]["player"] == "Tracy McGrady"
    assert report["projected_chance"]["simulation"]["method"] == (
        "paired stage-aware policy Monte Carlo"
    )
    assert report["action_selection"]["paired"]
    assert not {
        detail["player"]
        for detail in report["candidate_options"]
    }.intersection(
        {"LeBron James", "James Harden"}
    )


def test_elite_opening_shaq_is_not_abandoned_without_strong_evidence(
    tmp_path: Path,
) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )

    report = app.start("ORL", "1990s")["report"]

    assert report["board"]["best_legal"]["card_id"] == (
        "shaquille_oneal_orl_1990s"
    )
    assert report["action"] == "TAKE"
    assert report["recommended_card"]["id"] == "shaquille_oneal_orl_1990s"
    assert report["action_selection"]["model_leader"] == "END_RUN"
    assert report["action_selection"]["restart_guard_applied"]
    assert report["action_selection"]["confidence"] < 0.975


def test_mediocre_opening_board_is_not_blindly_taken(
    tmp_path: Path,
) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )

    report = app.start("MIA", "1980s")["report"]

    assert report["board"]["composite"]["max"] < 13
    assert report["action"] in {"TEAM_REROLL", "ERA_REROLL", "END_RUN"}


def test_phi_opening_preserves_final_era_reroll_and_exposes_distribution(
    tmp_path: Path,
) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )

    report = app.start(
        "PHI",
        "2020s",
        team_rerolls=0,
        era_rerolls=1,
    )["report"]

    assert report["action"] == "TAKE"
    assert report["recommended_card"]["id"] == "james_harden_phi_2020s"
    compared = {
        option["action"]: option
        for option in report["action_selection"]["compared_actions"]
    }
    assert compared["TAKE"]["speedrun_value"] > compared["ERA_REROLL"][
        "speedrun_value"
    ]
    distribution = report["reroll_expectations"]["era_distribution"]
    assert distribution["outcome_count"] == 6
    assert distribution["probability_better"] == pytest.approx(0.5)
    assert distribution["probability_better_by_2"] == pytest.approx(
        1 / 6,
        abs=1e-6,
    )
    assert distribution["probability_worse"] == pytest.approx(0.5)
    outcomes = report["reroll_expectations"]["era_outcomes"]
    assert {outcome["era"] for outcome in outcomes} == {
        "1960s",
        "1970s",
        "1980s",
        "1990s",
        "2000s",
        "2010s",
    }


def test_final_pick_action_comparison_has_nonzero_time_cost(
    tmp_path: Path,
) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )
    app.session.start("HOU", "1990s", team_rerolls=0, era_rerolls=1)
    app.session.roster = [
        {"id": "lebron_james_lal_2010s"},
        {"id": "james_harden_phi_2020s"},
        {"id": "magic_johnson_lal_1980s"},
        {"id": "kevin_garnett_min_2000s"},
    ]
    app.session.candidates = [
        {"id": card.id}
        for card in cards
        if card.team == "HOU" and card.era == "1990s" and card.playable
    ]

    report = app.state()["report"]

    assert report["action_selection"]["compared_actions"]
    assert all(
        action["average_turns"] >= 0.25
        for action in report["action_selection"]["compared_actions"]
    )


def test_dead_final_board_state_is_browser_json_safe(tmp_path: Path) -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    app = AppService(
        cards,
        load_metrics(ROOT / "data" / "team_era_metrics.json"),
        tmp_path / "active-run.json",
    )
    app.session.start("PHI", "1990s", team_rerolls=0, era_rerolls=1)
    app.session.roster = [
        {"id": "lebron_james_mia_2010s"},
        {"id": "elvin_hayes_hou_1970s"},
        {"id": "kevin_johnson_phx_1980s"},
        {"id": "elgin_baylor_lal_1960s"},
    ]
    app.session.candidates = [
        {"id": card.id}
        for card in cards
        if card.team == "PHI" and card.era == "1990s" and card.playable
    ]

    encoded = json.dumps(app.state(), allow_nan=False)
    parsed = json.loads(encoded)
    improvement = parsed["report"]["action_selection"]["reroll_improvement"]
    assert improvement is None or isinstance(improvement, (int, float))


def test_http_server_serves_ui_and_persistent_api(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    import_cards(output_dir=data_dir, input_json=FIXTURE)
    server = create_server(
        host="127.0.0.1",
        port=0,
        cards_path=data_dir / "cards.csv",
        metrics_path=data_dir / "team_era_metrics.json",
        session_path=tmp_path / "active-run.json",
        static_root=ROOT / "web",
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
            assert "82-0 Speedrun Control" in response.read().decode("utf-8")
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "default-src 'self'" in response.headers[
                "Content-Security-Policy"
            ]

        request = urllib.request.Request(
            f"{base_url}/api/run/start",
            data=json.dumps({"team": "ATL", "era": "2020s"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            state = json.load(response)
        assert state["session"]["active"]
        assert state["report"]["board"]["team"] == "ATL"

        wrong_content_type = urllib.request.Request(
            f"{base_url}/api/run/end",
            data=b'{"reason":"cross-site"}',
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as unsupported:
            urllib.request.urlopen(wrong_content_type, timeout=5)
        assert unsupported.value.code == 415

        hostile_host = urllib.request.Request(
            f"{base_url}/api/state",
            headers={"Host": "attacker.example"},
        )
        with pytest.raises(urllib.error.HTTPError) as forbidden:
            urllib.request.urlopen(hostile_host, timeout=5)
        assert forbidden.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_server_rejects_non_loopback_binding(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    import_cards(output_dir=data_dir, input_json=FIXTURE)

    with pytest.raises(ValueError, match="restricted to loopback"):
        create_server(
            host="0.0.0.0",
            port=0,
            cards_path=data_dir / "cards.csv",
            metrics_path=data_dir / "team_era_metrics.json",
            session_path=tmp_path / "active-run.json",
            static_root=ROOT / "web",
        )


def _start_test_server(tmp_path: Path) -> tuple:
    data_dir = tmp_path / "data"
    import_cards(output_dir=data_dir, input_json=FIXTURE)
    server = create_server(
        host="127.0.0.1",
        port=0,
        cards_path=data_dir / "cards.csv",
        metrics_path=data_dir / "team_era_metrics.json",
        session_path=tmp_path / "active-run.json",
        static_root=ROOT / "web",
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    return server, thread


def test_http_server_closes_after_max_lifetime(tmp_path: Path) -> None:
    server, thread = _start_test_server(tmp_path)
    try:
        attach_lifetime_watchdog(
            server,
            max_lifetime_seconds=0.4,
            idle_after_inactive_seconds=None,
        )
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_server_stays_up_during_active_game_then_closes(
    tmp_path: Path,
) -> None:
    server, thread = _start_test_server(tmp_path)
    try:
        server.service.session.start(
            "ATL", "2020s", team_rerolls=1, era_rerolls=1
        )
        attach_lifetime_watchdog(
            server,
            max_lifetime_seconds=5,
            idle_after_inactive_seconds=0.3,
        )
        time.sleep(0.5)
        assert thread.is_alive()
        server.service.session.end("test finished")
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
