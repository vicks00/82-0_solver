from __future__ import annotations

import json
import math
import mimetypes
import threading
import time
import webbrowser
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit

from .data import board_index, load_cards, load_metrics
from .badges import player_badges
from .engine import (
    board_quality_for_positions,
    roster_outlook,
    solve,
)
from .models import Card
from .scoring import (
    POSITIONS,
    THRESHOLD,
    best_assignment,
    display_assignment,
    exact_team_score,
)
from .session import RunSession, SessionError, load_session, save_session
from .simulation import (
    compare_speedrun_actions,
    simulate_policy_continuation,
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

DEFAULT_SERVER_LIFETIME_SECONDS = 6 * 60 * 60


def _require_loopback_host(host: str) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError(
            "The browser app is restricted to loopback. Use 127.0.0.1."
        )

class AppService:
    """Stateful application API shared by the HTTP server and tests."""

    def __init__(
        self,
        cards: list[Card],
        metrics: dict[str, Any],
        session_path: str | Path,
    ) -> None:
        self.cards = cards
        self.metrics = metrics
        self.session_path = Path(session_path)
        self.boards = board_index(metrics)
        self.cards_by_id = {card.id: card for card in cards}
        self._simulation_cache: dict[
            tuple[tuple[str, ...], int, int], dict[str, Any]
        ] = {}
        self._reroll_simulation_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...], int, int],
            dict[str, Any],
        ] = {}
        self._action_comparison_cache: dict[
            tuple[tuple[str, ...], str, str, str | None, int, int],
            dict[str, Any],
        ] = {}
        self.cards_by_board: dict[tuple[str, str], list[Card]] = defaultdict(list)
        for card in cards:
            if card.playable:
                self.cards_by_board[(card.team.upper(), card.era.lower())].append(card)
        self.session = load_session(self.session_path)
        self.lock = threading.RLock()
        changed = False
        if self.session.remove_previous_completed_chase():
            changed = True
        if self._remove_duplicate_player_candidates():
            changed = True
        if not self.session.chance_history:
            self._record_chance("chase started")
            changed = True
        if changed:
            self._save()

    def catalog(self) -> dict[str, Any]:
        teams = sorted({team for team, _ in self.boards})
        eras = sorted(
            {board["era"] for board in self.metrics["boards"]},
            key=lambda era: int(era[:4]),
        )
        return {
            "teams": teams,
            "eras": eras,
            "valid_boards": [
                {"team": board["team"], "era": board["era"]}
                for board in self.metrics["boards"]
            ],
        }

    def start(
        self,
        team: str,
        era: str,
        team_rerolls: int = 1,
        era_rerolls: int = 1,
    ) -> dict[str, Any]:
        with self.lock:
            self._validate_board(team, era)
            self.session.start(
                team,
                era,
                team_rerolls=team_rerolls,
                era_rerolls=era_rerolls,
            )
            self._populate_current_board()
            self._record_chance("opening spin")
            self._save()
            return self.state()

    def next_spin(self, team: str, era: str) -> dict[str, Any]:
        with self.lock:
            self._validate_board(team, era)
            self.session.advance_spin(team, era)
            self._populate_current_board()
            self._record_chance("next spin")
            self._save()
            return self.state()

    def team_reroll(self, team: str) -> dict[str, Any]:
        with self.lock:
            if not self.session.current_era:
                raise SessionError("No active era to preserve.")
            self._validate_board(team, self.session.current_era)
            if team.upper() == self.session.current_team:
                raise SessionError("Choose a different team for the TEAM reroll.")
            self.session.reroll_team(team)
            self._populate_current_board()
            self._record_chance("TEAM reroll")
            self._save()
            return self.state()

    def era_reroll(self, era: str) -> dict[str, Any]:
        with self.lock:
            if not self.session.current_team:
                raise SessionError("No active team to preserve.")
            self._validate_board(self.session.current_team, era)
            if era.lower() == str(self.session.current_era).lower():
                raise SessionError("Choose a different era for the ERA reroll.")
            self.session.reroll_era(era)
            self._populate_current_board()
            self._record_chance("ERA reroll")
            self._save()
            return self.state()

    def take(self, card_id: str) -> dict[str, Any]:
        with self.lock:
            report = self._report()
            legal_ids = {
                option["id"] for option in report.get("candidate_options", [])
            }
            if card_id not in legal_ids:
                raise SessionError("That card cannot be legally added to this roster.")
            selected = self.cards_by_id[card_id]
            committed_players = {
                self.cards_by_id[spec["id"]].player.casefold()
                for spec in self.session.roster
                if spec["id"] in self.cards_by_id
            }
            if selected.player.casefold() in committed_players:
                raise SessionError(
                    f"{selected.player} is already committed in this run."
                )
            self.session.take(card_id)
            if len(self.session.roster) == 5:
                roster = [
                    self.cards_by_id[spec["id"]]
                    for spec in self.session.roster
                ]
                final_score = exact_team_score(roster)
                self.session.complete(
                    success=final_score >= THRESHOLD,
                    final_score=round(final_score, 3),
                )
            self._record_chance(f"picked {self.cards_by_id[card_id].player}")
            self._save()
            return self.state()

    def end(self, reason: str = "manual") -> dict[str, Any]:
        with self.lock:
            self.session.end(reason)
            self._record_chance("restart baseline")
            self._save()
            return self.state()

    def reset_clock(self) -> dict[str, Any]:
        with self.lock:
            self.session.reset_clock()
            self._save()
            return self.state()

    def start_clock(self) -> dict[str, Any]:
        with self.lock:
            self.session.start_clock()
            self._save()
            return self.state()

    def pause_clock(self) -> dict[str, Any]:
        with self.lock:
            self.session.pause_clock()
            self._save()
            return self.state()

    def disable_clock(self) -> dict[str, Any]:
        with self.lock:
            self.session.disable_clock()
            self._save()
            return self.state()

    def state(self) -> dict[str, Any]:
        with self.lock:
            report = self._report()
            report["chance"] = self._chance_with_trend(report["chance"])
            roster_cards = [
                self.cards_by_id[spec["id"]]
                for spec in self.session.roster
                if spec["id"] in self.cards_by_id
            ]
            optimized_assignment = best_assignment(roster_cards)
            live_assignment = self.session.live_positions
            uses_live_assignment = (
                bool(roster_cards)
                and set(live_assignment) == {card.id for card in roster_cards}
            )
            assignment = (
                live_assignment if uses_live_assignment else optimized_assignment
            )
            committed_score = (
                exact_team_score(roster_cards) if roster_cards else 0.0
            )
            return {
                "session": {
                    "active": self.session.active,
                    "run_number": self.session.run_number,
                    "chase_started_at": self.session.chase_started_at,
                    "chase_finished_at": self.session.chase_finished_at,
                    "clock_enabled": self.session.clock_enabled,
                    "clock_running": self.session.clock_running,
                    "clock_elapsed_seconds": round(
                        self.session.clock_elapsed_seconds, 3
                    ),
                    "clock_segment_started_at": (
                        self.session.clock_segment_started_at
                    ),
                    "started_at": self.session.started_at,
                    "finished_at": self.session.finished_at,
                    "result": self.session.result,
                    "final_score": self.session.final_score,
                    "spin_open": self.session.spin_open,
                    "current_team": self.session.current_team,
                    "current_era": self.session.current_era,
                    "team_rerolls": self.session.team_rerolls,
                    "era_rerolls": self.session.era_rerolls,
                    "history_count": len(self.session.history),
                },
                "roster": [
                    {
                        "id": card.id,
                        "player": card.player,
                        "team": card.team,
                        "era": card.era,
                        "positions": list(card.positions),
                        "assigned_position": assignment.get(card.id),
                        "assignment_source": (
                            "live" if uses_live_assignment else "solver"
                        ),
                        "raw_composite": round(card.raw_composite, 3),
                        "tier": card.tier,
                        "tier_label": card.tier_label,
                        "badges": player_badges(card),
                    }
                    for card in roster_cards
                ],
                "score_progress": {
                    "threshold": THRESHOLD,
                    "roster_size": len(roster_cards),
                    "raw_composite_sum": round(
                        sum(card.raw_composite for card in roster_cards),
                        3,
                    ),
                    "adjusted_committed_score": round(committed_score, 3),
                    "approximate_remaining": round(
                        max(0.0, THRESHOLD - committed_score),
                        3,
                    ),
                    "complete": len(roster_cards) == 5,
                    "wins": (
                        committed_score >= THRESHOLD
                        if len(roster_cards) == 5
                        else None
                    ),
                },
                "report": report,
                "history": self.session.history[-20:],
                "chance_history": self.session.chance_history[-30:],
            }

    def _report(self) -> dict[str, Any]:
        if not self.session.active:
            chance = self._roster_chance()
            return {
                "action": "START",
                "decision": "START A NEW RUN",
                "recommended_card": None,
                "candidate_options": [],
                "board": None,
                "reroll_expectations": None,
                "chance": chance,
            }
        if not self.session.spin_open:
            return {
                "action": "NEXT_SPIN",
                "decision": "ENTER NEXT TEAM + ERA",
                "recommended_card": None,
                "candidate_options": [],
                "board": None,
                "reroll_expectations": None,
                "chance": self._roster_chance(),
            }

        solved = solve(self.session.solver_state(), self.cards, self.metrics)
        roster_cards = [
            self.cards_by_id[spec["id"]]
            for spec in self.session.roster
            if spec["id"] in self.cards_by_id
        ]
        best_take_option = (
            solved["candidate_options"][0]
            if solved["candidate_options"]
            else None
        )
        current_team = str(self.session.current_team)
        current_era = str(self.session.current_era)
        board = self.boards[(current_team.upper(), current_era.lower())]
        stage_open_positions = set(solved["open_positions"])
        current_best_legal = solved.get("current_best_legal_outlook")
        stage_quality = (
            float(current_best_legal["path_value"])
            if current_best_legal is not None
            else board_quality_for_positions(board, stage_open_positions)
        )
        reroll_by_action = {
            option["action"]: option for option in solved["reroll_options"]
        }
        team_reroll = reroll_by_action.get("TEAM REROLL")
        era_reroll = reroll_by_action.get("ERA REROLL")
        option_by_id = {
            option["id"]: option for option in solved["candidate_options"]
        }
        board_cards = sorted(
            self.cards_by_board[(current_team.upper(), current_era.lower())],
            key=lambda card: card.raw_composite,
            reverse=True,
        )
        candidate_details = []
        for card in board_cards:
            if card.id not in {
                spec["id"] for spec in self.session.candidates
            }:
                continue
            option = option_by_id.get(card.id)
            candidate_details.append(
                {
                    "id": card.id,
                    "player": card.player,
                    "positions": list(card.positions),
                    "raw_composite": round(card.raw_composite, 3),
                    "pts": card.pts,
                    "reb": card.reb,
                    "ast": card.ast,
                    "stl": card.stl,
                    "blk": card.blk,
                    "historical_defense": (
                        card.stl_historically_unavailable
                        or card.blk_historically_unavailable
                    ),
                    "tier": card.tier,
                    "tier_label": card.tier_label,
                    "badges": player_badges(card),
                    "legal": option is not None,
                    "take_position": (
                        option["take_position"] if option is not None else None
                    ),
                    "continuation_probability": (
                        option["survival_probability_estimate"]
                        if option is not None
                        else None
                    ),
                    "relative_to_restart": (
                        option["relative_to_restart"]
                        if option is not None
                        else None
                    ),
                    "continue_threshold": (
                        option["continue_threshold"]
                        if option is not None
                        else None
                    ),
                    "required_average_remaining": (
                        option["required_average_remaining"]
                        if option is not None
                        else None
                    ),
                    "final_score": (
                        option["final_score"]
                        if option is not None
                        else None
                    ),
                    "margin_to_82": (
                        round(option["final_score"] - THRESHOLD, 3)
                        if option is not None
                        and option["final_score"] is not None
                        else None
                    ),
                }
            )

        roster_only_chance = self._roster_chance()
        comparison = self._paired_action_comparison(
            roster_cards,
            current_team=current_team,
            current_era=current_era,
            take_card_id=(
                best_take_option["id"] if best_take_option is not None else None
            ),
        )
        compared_actions = []
        for projection in comparison["actions"]:
            compared_actions.append(
                {
                    **projection,
                    "utility": projection["speedrun_value"],
                    "continue_threshold": 1.0,
                }
            )
        selected_projection = next(
            (
                projection
                for projection in compared_actions
                if projection["action"] == comparison["selected_action"]
            ),
            None,
        )
        projected_take = next(
            (
                projection
                for projection in compared_actions
                if projection["action"] == "TAKE"
            ),
            None,
        )
        action = (
            str(comparison["selected_action"])
            if selected_projection is not None
            else "WAIT"
        )
        if action == "END_RUN" or selected_projection is None:
            # Restart is a new run, not a possible completion of the board the
            # player is viewing. Keep that probability in the action comparison,
            # but report the current run as unwinnable after the recommendation
            # to abandon it.
            current_chance = {
                **roster_only_chance,
                "probability": 0.0,
                "relative_to_restart": 0.0,
                "speedrun_value": 0.0,
                "simulation": {
                    **roster_only_chance["simulation"],
                    "probability": 0.0,
                    "speedrun_value": 0.0,
                    "current_board": True,
                },
                "current_board": True,
                "recommended_action": action,
            }
        else:
            current_chance = {
                **roster_only_chance,
                "probability": selected_projection["probability"],
                "relative_to_restart": selected_projection[
                    "relative_to_restart"
                ],
                "speedrun_value": selected_projection["speedrun_value"],
                "simulation": {
                    **selected_projection["simulation"],
                    "current_board": True,
                },
                "current_board": True,
                "recommended_action": action,
            }
        for projection in compared_actions:
            projection["delta"] = round(
                float(projection["probability"])
                - float(current_chance["probability"]),
                6,
            )
        if comparison["restart_guard_applied"]:
            selection_reason = (
                "preserved the run because restart did not clear the "
                "high-confidence abandonment threshold"
            )
        elif comparison["reroll_guard_applied"]:
            selection_reason = (
                "preserved the final reroll because its estimated gain did "
                "not clear the confidence and practical-value hurdles"
            )
        else:
            selection_reason = (
                "highest paired speedrun value"
                if comparison["confidence_label"] == "high"
                else "highest estimated speedrun value; ordering remains uncertain"
            )

        if best_take_option is not None and projected_take is not None:
            best_take_option = {
                **best_take_option,
                "relative_to_restart": projected_take["relative_to_restart"],
                "survival_probability_estimate": projected_take["probability"],
            }
            for detail in candidate_details:
                if detail["id"] == best_take_option["id"]:
                    detail["relative_to_restart"] = projected_take[
                        "relative_to_restart"
                    ]
                    detail["continuation_probability"] = projected_take[
                        "probability"
                    ]
                    break
            projected_roster = roster_cards + [
                self.cards_by_id[best_take_option["id"]]
            ]
            projected_key = (
                tuple(sorted(card.id for card in projected_roster)),
                self.session.team_rerolls,
                self.session.era_rerolls,
            )
            self._simulation_cache[projected_key] = projected_take["simulation"]

        if action == "TAKE" and best_take_option is not None:
            if comparison["restart_guard_applied"]:
                decision = (
                    f"TAKE {best_take_option['player']} at "
                    f"{best_take_option['take_position']} — restart led the "
                    "point estimate but did not reach the 97.5% confidence "
                    "required to abandon a live run."
                )
            elif comparison["reroll_guard_applied"]:
                decision = (
                    f"TAKE {best_take_option['player']} at "
                    f"{best_take_option['take_position']} — preserve the final "
                    "reroll; using it now did not clear both the 90% confidence "
                    f"test and the {comparison['reroll_hurdle']:.1%} "
                    "stage-value hurdle."
                )
            else:
                decision = (
                    f"TAKE {best_take_option['player']} at "
                    f"{best_take_option['take_position']} — paired policy "
                    f"simulation estimates "
                    f"{selected_projection['relative_to_restart']:.2f}× "
                    f"restart speedrun value at "
                    f"{comparison['confidence']:.0%} confidence."
                )
        elif action in {"TEAM_REROLL", "ERA_REROLL"}:
            take_value = (
                float(projected_take["relative_to_restart"])
                if projected_take is not None
                else 0.0
            )
            decision = (
                f"{action.replace('_', ' ')} — paired speedrun value is "
                f"{selected_projection['relative_to_restart']:.2f}× restart "
                f"versus {take_value:.2f}× for the best TAKE."
            )
        elif action == "END_RUN" and selected_projection is not None:
            decision = (
                "END RUN / START OVER — paired same-policy rollouts estimate "
                "the highest successful-runs-per-time value for restarting"
                + (
                    "."
                    if comparison["confidence_label"] == "high"
                    else ", but confidence is low."
                )
            )
        else:
            decision = solved["decision"]

        recommended = (
            best_take_option
            if action == "TAKE" and best_take_option is not None
            else None
        )
        recommended_reroll = next(
            (
                option
                for option in solved["reroll_options"]
                if option["action"].replace(" ", "_") == action
            ),
            None,
        )

        current_best_composite = (
            float(current_best_legal["raw_composite"])
            if current_best_legal is not None
            else None
        )

        def reroll_distribution(
            option: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            if option is None:
                return [], None
            outcomes = option["best_legal_outlook"]["outcomes"]
            count = len(outcomes)
            if not count or current_best_composite is None:
                return outcomes, None
            enriched = []
            for outcome in outcomes:
                delta = float(outcome["raw_composite"]) - current_best_composite
                enriched.append(
                    {
                        **outcome,
                        "probability": round(1.0 / count, 6),
                        "composite_delta": round(delta, 3),
                        "expected_composite_contribution": round(
                            float(outcome["raw_composite"]) / count,
                            6,
                        ),
                    }
                )
            return enriched, {
                "outcome_count": count,
                "current_best_composite": round(current_best_composite, 3),
                "probability_better": round(
                    sum(
                        outcome["composite_delta"] > 0
                        for outcome in enriched
                    )
                    / count,
                    6,
                ),
                "probability_better_by_1": round(
                    sum(
                        outcome["composite_delta"] > 1
                        for outcome in enriched
                    )
                    / count,
                    6,
                ),
                "probability_better_by_2": round(
                    sum(
                        outcome["composite_delta"] > 2
                        for outcome in enriched
                    )
                    / count,
                    6,
                ),
                "probability_worse": round(
                    sum(
                        outcome["composite_delta"] < 0
                        for outcome in enriched
                    )
                    / count,
                    6,
                ),
            }

        team_outcomes, team_distribution = reroll_distribution(team_reroll)
        era_outcomes, era_distribution = reroll_distribution(era_reroll)
        projected_chance = (
            selected_projection if action != "END_RUN" else None
        )
        return {
            **solved,
            "decision": decision,
            "action": action,
            "recommended_card": recommended,
            "recommended_reroll": recommended_reroll,
            "action_selection": {
                "objective": comparison["objective"],
                "reason": selection_reason,
                "confidence": comparison["confidence"],
                "confidence_label": comparison["confidence_label"],
                "confidence_z": comparison["confidence_z"],
                "trials": comparison["trials"],
                "adaptive_rounds": comparison["adaptive_rounds"],
                "paired": comparison["paired"],
                "policy": comparison["policy"],
                "model_leader": comparison["model_leader"],
                "restart_guard_applied": comparison[
                    "restart_guard_applied"
                ],
                "reroll_guard_applied": comparison[
                    "reroll_guard_applied"
                ],
                "reroll_hurdle": comparison["reroll_hurdle"],
                "reroll_improvement": comparison["reroll_improvement"],
                "reroll_confidence": comparison["reroll_confidence"],
                "compared_actions": [
                    {
                        "action": projection["action"],
                        "label": projection["label"],
                        "probability": projection["probability"],
                        "standard_error": projection["standard_error"],
                        "average_turns": projection["average_turns"],
                        "speedrun_value": projection["speedrun_value"],
                        "relative_to_restart": projection[
                            "relative_to_restart"
                        ],
                        "selected": projection["action"] == action,
                    }
                    for projection in compared_actions
                ],
            },
            "candidate_options": candidate_details,
            "board": {
                "team": board["team"],
                "era": board["era"],
                "quality": board["board_quality"],
                "stage_quality": round(stage_quality, 3),
                "stage_open_positions": sorted(stage_open_positions),
                "best_legal": current_best_legal,
                "card_count": board["card_count"],
                "playable_count": board["playable_count"],
                "composite": board["composite"],
                "position_coverage": board["position_coverage"],
            },
            "reroll_expectations": {
                "current_quality": round(stage_quality, 3),
                "team_reroll_average": (
                    team_reroll["expected_best_legal_value"]
                    if team_reroll is not None
                    else None
                ),
                "team_edge": (
                    team_reroll["quality_edge"]
                    if team_reroll is not None
                    else None
                ),
                "team_better_probability": (
                    team_reroll["better_outcome_probability"]
                    if team_reroll is not None
                    else None
                ),
                "team_outcomes": (
                    team_outcomes
                ),
                "team_distribution": team_distribution,
                "era_reroll_average": (
                    era_reroll["expected_best_legal_value"]
                    if era_reroll is not None
                    else None
                ),
                "era_edge": (
                    era_reroll["quality_edge"]
                    if era_reroll is not None
                    else None
                ),
                "era_better_probability": (
                    era_reroll["better_outcome_probability"]
                    if era_reroll is not None
                    else None
                ),
                "era_outcomes": (
                    era_outcomes
                ),
                "era_distribution": era_distribution,
            },
            "chance": current_chance,
            "projected_chance": projected_chance,
        }

    def _roster_chance(self) -> dict[str, Any]:
        roster = [
            self.cards_by_id[spec["id"]]
            for spec in self.session.roster
            if spec["id"] in self.cards_by_id
        ]
        if self.session.result == "82-0":
            return {
                "probability": 1.0,
                "relative_to_restart": 999.0,
                "continue_threshold": 1.0,
                "remaining_picks": 0,
                "required_average_remaining": 0.0,
                "open_positions": [],
            }
        if self.session.result == "missed":
            return {
                "probability": 0.0,
                "relative_to_restart": 0.0,
                "continue_threshold": 1.0,
                "remaining_picks": 0,
                "required_average_remaining": 0.0,
                "open_positions": [],
            }
        chance = dict(roster_outlook(roster, self.metrics))
        chance["simulation"] = self._simulated_chance(roster)
        chance["probability"] = chance["simulation"]["probability"]
        fresh = self._simulated_chance([])
        fresh_probability = float(fresh["probability"])
        current_turns = max(
            float(chance["simulation"].get("average_turns", 0.0)),
            0.25,
        )
        fresh_turns = max(float(fresh.get("average_turns", 5.0)) + 0.75, 0.25)
        current_value = float(chance["probability"]) / current_turns
        restart_value = fresh_probability / fresh_turns
        chance["speedrun_value"] = round(current_value, 8)
        chance["relative_to_restart"] = (
            round(current_value / restart_value, 3)
            if restart_value
            else 0.0
        )
        chance["simulation_baseline_probability"] = fresh_probability
        return chance

    def _simulated_chance(self, roster: list[Card]) -> dict[str, Any]:
        key = (
            tuple(sorted(card.id for card in roster)),
            self.session.team_rerolls,
            self.session.era_rerolls,
        )
        cached = self._simulation_cache.get(key)
        if cached is None:
            cached = simulate_policy_continuation(
                self.cards,
                roster,
                team_rerolls=self.session.team_rerolls,
                era_rerolls=self.session.era_rerolls,
            )
            self._simulation_cache[key] = cached
        return cached

    def _paired_action_comparison(
        self,
        roster: list[Card],
        *,
        current_team: str,
        current_era: str,
        take_card_id: str | None,
    ) -> dict[str, Any]:
        key = (
            tuple(sorted(card.id for card in roster)),
            current_team.upper(),
            current_era.lower(),
            take_card_id,
            self.session.team_rerolls,
            self.session.era_rerolls,
        )
        cached = self._action_comparison_cache.get(key)
        if cached is None:
            cached = compare_speedrun_actions(
                self.cards,
                roster,
                current_team=current_team,
                current_era=current_era,
                take_card_id=take_card_id,
                team_rerolls=self.session.team_rerolls,
                era_rerolls=self.session.era_rerolls,
            )
            self._action_comparison_cache[key] = cached
        return cached

    def _record_chance(self, label: str) -> None:
        chance = self._report()["chance"]
        self.session.record_chance(
            probability=float(chance["probability"]),
            relative_to_restart=float(chance["relative_to_restart"]),
            continue_threshold=float(chance["continue_threshold"]),
            label=label,
        )

    def _chance_with_trend(self, chance: dict[str, Any]) -> dict[str, Any]:
        history = self.session.chance_history
        previous: dict[str, Any] | None = None
        if history:
            last_matches = abs(
                float(history[-1]["probability"])
                - float(chance["probability"])
            ) < 1e-9
            if last_matches and len(history) >= 2:
                previous = history[-2]
            elif not last_matches:
                previous = history[-1]
        delta = (
            float(chance["probability"]) - float(previous["probability"])
            if previous is not None
            else 0.0
        )
        if delta > 0.0005:
            direction = "up"
        elif delta < -0.0005:
            direction = "down"
        else:
            direction = "flat"

        probability = float(chance["probability"])
        relative = float(chance["relative_to_restart"])
        threshold = float(chance["continue_threshold"])
        if probability >= 0.999:
            health = "secured"
        elif relative >= 1.25:
            health = "strong"
        elif relative >= threshold:
            health = "healthy"
        elif relative >= threshold * 0.8:
            health = "fragile"
        else:
            health = "critical"
        return {
            **chance,
            "previous_probability": (
                float(previous["probability"]) if previous is not None else None
            ),
            "delta": round(delta, 4),
            "direction": direction,
            "health": health,
        }

    def _populate_current_board(
        self, visible_player_names: set[str] | None = None
    ) -> None:
        assert self.session.current_team is not None
        assert self.session.current_era is not None
        roster_ids = {spec["id"] for spec in self.session.roster}
        roster_players = {
            self.cards_by_id[card_id].player.casefold()
            for card_id in roster_ids
            if card_id in self.cards_by_id
        }
        card_ids = [
            card.id
            for card in self.cards_by_board[
                (
                    self.session.current_team.upper(),
                    self.session.current_era.lower(),
                )
            ]
            if card.id not in roster_ids
            and card.player.casefold() not in roster_players
            and (
                visible_player_names is None
                or card.player.casefold() in visible_player_names
            )
        ]
        if visible_player_names is not None and not card_ids:
            raise SessionError(
                "None of the visible live-game players matched the local card database."
            )
        self.session.set_candidates(card_ids)

    def _remove_duplicate_player_candidates(self) -> bool:
        """Drop stale offers for a player already committed in this run."""
        committed_players = {
            self.cards_by_id[spec["id"]].player.casefold()
            for spec in self.session.roster
            if spec["id"] in self.cards_by_id
        }
        filtered = [
            spec
            for spec in self.session.candidates
            if (
                spec.get("id") in self.cards_by_id
                and self.cards_by_id[spec["id"]].player.casefold()
                not in committed_players
            )
        ]
        if filtered == self.session.candidates:
            return False
        self.session.candidates = filtered
        return True

    def _validate_board(self, team: str, era: str) -> None:
        if (team.upper(), era.lower()) not in self.boards:
            raise SessionError(f"No card board exists for {team.upper()} {era}.")

    def _save(self) -> None:
        save_session(self.session_path, self.session)


class AppRequestHandler(BaseHTTPRequestHandler):
    service: AppService
    static_root: Path

    def do_GET(self) -> None:
        if not self._request_host_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid request host"})
            return
        path = urlparse(self.path).path
        if path == "/api/catalog":
            self._json(HTTPStatus.OK, self.service.catalog())
            return
        if path == "/api/state":
            self._json(HTTPStatus.OK, self.service.state())
            return
        self._static(path)

    def do_POST(self) -> None:
        if not self._request_host_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid request host"})
            return
        path = urlparse(self.path).path
        if self.headers.get_content_type() != "application/json":
            self._json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"error": "Requests must use application/json"},
            )
            return
        try:
            payload = self._read_json()
            routes = {
                "/api/run/start": lambda: self.service.start(
                    str(payload["team"]),
                    str(payload["era"]),
                    int(payload.get("team_rerolls", 1)),
                    int(payload.get("era_rerolls", 1)),
                ),
                "/api/run/next-spin": lambda: self.service.next_spin(
                    str(payload["team"]), str(payload["era"])
                ),
                "/api/run/team-reroll": lambda: self.service.team_reroll(
                    str(payload["team"])
                ),
                "/api/run/era-reroll": lambda: self.service.era_reroll(
                    str(payload["era"])
                ),
                "/api/run/take": lambda: self.service.take(str(payload["card_id"])),
                "/api/run/end": lambda: self.service.end(
                    str(payload.get("reason", "manual"))
                ),
                "/api/clock/start": self.service.start_clock,
                "/api/clock/pause": self.service.pause_clock,
                "/api/clock/reset": self.service.reset_clock,
                "/api/clock/disable": self.service.disable_clock,
                "/api/chase/reset-clock": self.service.reset_clock,
            }
            action = routes.get(path)
            if action is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown API route"})
                return
            self._json(HTTPStatus.OK, action())
        except (KeyError, TypeError, ValueError, SessionError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64_000:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length)
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _request_host_allowed(self) -> bool:
        host_header = self.headers.get("Host", "")
        try:
            hostname = urlsplit(f"//{host_header}").hostname
        except ValueError:
            return False
        return bool(hostname) and hostname.rstrip(".").lower() in {
            "127.0.0.1",
            "localhost",
        }

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )

    def _static(self, request_path: str) -> None:
        relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        target = (self.static_root / relative).resolve()
        if self.static_root.resolve() not in target.parents and target != self.static_root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)


def create_server(
    *,
    host: str,
    port: int,
    cards_path: str | Path,
    metrics_path: str | Path,
    session_path: str | Path,
    static_root: str | Path,
) -> ThreadingHTTPServer:
    _require_loopback_host(host)
    service = AppService(
        load_cards(cards_path),
        load_metrics(metrics_path),
        session_path,
    )

    class BoundHandler(AppRequestHandler):
        pass

    BoundHandler.service = service
    BoundHandler.static_root = Path(static_root)
    server = ThreadingHTTPServer((host, port), BoundHandler)
    server.service = service  # type: ignore[attr-defined]
    return server


def attach_lifetime_watchdog(
    server: ThreadingHTTPServer,
    *,
    max_lifetime_seconds: float = DEFAULT_SERVER_LIFETIME_SECONDS,
    idle_after_inactive_seconds: float | None = None,
) -> threading.Thread:
    """Close the HTTP server after a hard lifetime, or after the game stays inactive.

    A new run in the same process cancels the inactive timer. Agents must not
    start another `run_app.py` unless the 82-0 game itself was restarted.
    """

    started = time.monotonic()
    inactive_since: float | None = None

    def is_game_active() -> bool:
        service = getattr(server, "service", None)
        if service is None:
            return False
        with service.lock:
            return bool(service.session.active)

    def watch() -> None:
        nonlocal inactive_since
        while True:
            now = time.monotonic()
            if now - started >= max_lifetime_seconds:
                hours = max_lifetime_seconds / 3600
                print(
                    f"Solver reached its {hours:g}-hour lifetime; "
                    "closing this terminal."
                )
                break
            if idle_after_inactive_seconds is not None:
                if is_game_active():
                    inactive_since = None
                else:
                    if inactive_since is None:
                        inactive_since = now
                    elif now - inactive_since >= idle_after_inactive_seconds:
                        print(
                            "No active 82-0 run; closing this solver terminal."
                        )
                        break
            time.sleep(0.25)
        server.shutdown()

    watcher = threading.Thread(
        target=watch,
        name="solver-lifetime",
        daemon=True,
    )
    watcher.start()
    return watcher


def run_server(
    *,
    host: str,
    port: int,
    cards_path: str | Path,
    metrics_path: str | Path,
    session_path: str | Path,
    static_root: str | Path,
    open_browser: bool = True,
    max_lifetime_seconds: float = DEFAULT_SERVER_LIFETIME_SECONDS,
    idle_after_inactive_seconds: float | None = 15 * 60,
) -> None:
    server = create_server(
        host=host,
        port=port,
        cards_path=cards_path,
        metrics_path=metrics_path,
        session_path=session_path,
        static_root=static_root,
    )
    url = f"http://{host}:{server.server_port}"
    print(f"82-0 Speedrun UI: {url}")
    print(f"Persistent run state: {session_path}")
    hours = max_lifetime_seconds / 3600
    print(
        f"This terminal closes after {hours:g} hour(s), or 15 minutes "
        "after the run ends. It does not auto-restart."
    )
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    attach_lifetime_watchdog(
        server,
        max_lifetime_seconds=max_lifetime_seconds,
        idle_after_inactive_seconds=idle_after_inactive_seconds,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping 82-0 Speedrun UI.")
    finally:
        server.server_close()
