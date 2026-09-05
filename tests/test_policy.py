from __future__ import annotations

from pathlib import Path

import pytest

from speedrun_solver.data import load_cards, load_metrics
from speedrun_solver.engine import (
    empirical_position_model,
    final_turn_reroll_outlook,
    solve,
)

ROOT = Path(__file__).resolve().parents[1]


def test_opening_karl_malone_is_compared_to_restart_pace() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    result = solve(
        {
            "roster": [],
            "candidates": [{"id": "karl_malone_uta_1990s"}],
            "current_team": "UTA",
            "current_era": "1990s",
            "team_rerolls": 1,
            "era_rerolls": 1,
        },
        cards,
        metrics,
    )

    option = result["candidate_options"][0]
    assert result["decision"].startswith("TAKE Karl Malone")
    assert option["survival_probability_estimate"] < 0.05
    assert option["relative_to_restart"] >= 0.9
    assert option["remaining_picks"] == 4


def test_early_stage_tolerance_keeps_a_decent_dwyane_wade_opening() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    result = solve(
        {
            "roster": [],
            "candidates": [{"id": "dwyane_wade_mia_2000s"}],
            "current_team": "MIA",
            "current_era": "2000s",
            "team_rerolls": 1,
            "era_rerolls": 1,
        },
        cards,
        metrics,
    )

    option = result["candidate_options"][0]
    assert result["decision"].startswith("TAKE Dwyane Wade")
    assert option["relative_to_restart"] >= option["continue_threshold"]
    assert option["continue_threshold"] == 0.72


def test_late_run_uses_remaining_positions_in_speedrun_value() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    result = solve(
        {
            "roster": [
                {"id": "wilt_chamberlain_gsw_1960s"},
                {"id": "oscar_robertson_sac_1960s"},
                {"id": "lebron_james_lal_2010s"},
            ],
            "candidates": [{"id": "karl_malone_uta_1990s"}],
            "current_team": "UTA",
            "current_era": "1990s",
            "team_rerolls": 0,
            "era_rerolls": 0,
        },
        cards,
        metrics,
    )

    option = result["candidate_options"][0]
    assert option["remaining_picks"] == 1
    assert option["required_average_remaining"] > 0
    assert result["stage"] == 4


def test_position_replacement_values_are_derived_from_database_boards() -> None:
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    samples, summary, fresh_probability = empirical_position_model(metrics)

    assert set(samples) == {"PG", "SG", "SF", "PF", "C"}
    assert summary["C"]["source_boards"] == metrics["board_count"]
    assert summary["C"]["mean"] > summary["SF"]["mean"]
    assert fresh_probability > 0


def test_lower_composite_elgin_can_beat_wilt_on_replacement_value() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    result = solve(
        {
            "roster": [],
            "candidates": [
                {"id": "wilt_chamberlain_lal_1960s"},
                {"id": "elgin_baylor_lal_1960s"},
            ],
            "current_team": "LAL",
            "current_era": "1960s",
            "team_rerolls": 1,
            "era_rerolls": 1,
        },
        cards,
        metrics,
    )

    options = {
        option["player"]: option for option in result["candidate_options"]
    }
    wilt = options["Wilt Chamberlain"]
    elgin = options["Elgin Baylor"]
    assert wilt["raw_composite"] > elgin["raw_composite"]
    assert result["decision"].startswith("TAKE Elgin Baylor")
    assert elgin["relative_to_restart"] > wilt["relative_to_restart"]


def test_final_milwaukee_era_reroll_finds_kareem_winning_path() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    roster_ids = [
        "larry_bird_bos_1980s",
        "shai_gilgeous_alexander_okc_2020s",
        "bob_mcadoo_lac_1970s",
        "tracy_mcgrady_orl_2000s",
    ]
    result = solve(
        {
            "roster": [{"id": card_id} for card_id in roster_ids],
            "candidates": [
                {"id": card.id}
                for card in cards
                if card.team == "MIL" and card.era == "2000s" and card.playable
            ],
            "current_team": "MIL",
            "current_era": "2000s",
            "team_rerolls": 1,
            "era_rerolls": 1,
        },
        cards,
        metrics,
    )

    assert result["decision"].startswith("ERA REROLL")
    era_option = next(
        option
        for option in result["reroll_options"]
        if option["action"] == "ERA REROLL"
    )
    outlook = era_option["final_turn_outlook"]
    assert outlook["win_probability"] == pytest.approx(1 / 6, abs=1e-6)
    assert outlook["winning_outcomes"][0]["player"] == "Kareem Abdul-Jabbar"
    assert outlook["winning_outcomes"][0]["final_score"] == 113.981


def test_final_team_reroll_after_giannis_board_has_two_winning_teams() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    roster_ids = [
        "larry_bird_bos_1980s",
        "shai_gilgeous_alexander_okc_2020s",
        "bob_mcadoo_lac_1970s",
        "tracy_mcgrady_orl_2000s",
    ]
    roster = [
        next(card for card in cards if card.id == card_id)
        for card_id in roster_ids
    ]
    outlook = final_turn_reroll_outlook(
        roster,
        cards,
        team="MIL",
        era="2020s",
        kind="TEAM",
    )

    assert outlook is not None
    assert outlook["winning_outcome_count"] == 2
    assert {
        outcome["player"] for outcome in outlook["winning_outcomes"]
    } == {"Nikola Jokić", "Russell Westbrook"}


def test_deron_misses_but_jimmy_wins_due_to_historical_defense() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    roster = [
        {"id": card_id}
        for card_id in [
            "jerry_west_lal_1960s",
            "elgin_baylor_lal_1960s",
            "pau_gasol_chi_2010s",
            "wilt_chamberlain_phi_1960s",
        ]
    ]

    uta = solve(
        {
            "roster": roster,
            "candidates": [{"id": "deron_williams_uta_2010s"}],
            "current_team": "UTA",
            "current_era": "2010s",
            "team_rerolls": 1,
            "era_rerolls": 1,
        },
        cards,
        metrics,
    )
    deron = uta["candidate_options"][0]
    assert deron["final_score"] == 109.29
    assert deron["82_0"] is False
    assert uta["decision"].startswith("TEAM REROLL")

    minnesota = solve(
        {
            "roster": roster,
            "candidates": [{"id": "jimmy_butler_min_2010s"}],
            "current_team": "MIN",
            "current_era": "2010s",
            "team_rerolls": 0,
            "era_rerolls": 1,
        },
        cards,
        metrics,
    )
    jimmy = minnesota["candidate_options"][0]
    assert jimmy["final_score"] == 110.83
    assert jimmy["82_0"] is True
    assert minnesota["decision"].startswith("TAKE Jimmy Butler")


def test_houston_2000s_era_reroll_uses_best_legal_card_per_era() -> None:
    cards = load_cards(ROOT / "data" / "cards.csv")
    metrics = load_metrics(ROOT / "data" / "team_era_metrics.json")
    result = solve(
        {
            "roster": [{"id": "alonzo_mourning_mia_1990s"}],
            "candidates": [
                {"id": card.id}
                for card in cards
                if card.team == "HOU"
                and card.era == "2000s"
                and card.playable
            ],
            "current_team": "HOU",
            "current_era": "2000s",
            "team_rerolls": 1,
            "era_rerolls": 1,
        },
        cards,
        metrics,
    )

    assert result["decision"].startswith("ERA REROLL")
    era = next(
        option
        for option in result["reroll_options"]
        if option["action"] == "ERA REROLL"
    )
    assert era["better_outcome_probability"] == 1.0
    assert era["quality_edge"] > era["preserve_penalty"]
    outcomes = {
        outcome["era"]: outcome
        for outcome in era["best_legal_outlook"]["outcomes"]
    }
    assert outcomes["1990s"]["player"] == "Hakeem Olajuwon"
    assert outcomes["2010s"]["player"] == "James Harden"
    assert outcomes["2020s"]["player"] == "Kevin Durant"
