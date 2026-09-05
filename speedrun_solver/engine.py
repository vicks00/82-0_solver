from __future__ import annotations

import random
import statistics
from collections import defaultdict
from typing import Any

from .data import board_index, find_one
from .models import Card
from .scoring import (
    THRESHOLD,
    POSITIONS,
    assignments,
    best_assignment,
    display_assignment,
    exact_team_score,
    open_positions,
)

RESTART_OVERHEAD_TURNS = 0.75
ACCEPTED_BOARD_QUANTILE = 0.75
_POSITION_MODEL_CACHE: dict[
    str,
    tuple[
        dict[str, tuple[float, ...]],
        dict[str, dict[str, float | int]],
        float,
    ],
] = {}


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def empirical_position_model(
    metrics: dict[str, Any],
) -> tuple[
    dict[str, tuple[float, ...]],
    dict[str, dict[str, float | int]],
    float,
]:
    source = metrics.get("source", {})
    cache_key = str(
        source.get("sha256")
        or metrics.get("generated_at")
        or metrics.get("card_count")
    )
    cached = _POSITION_MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    samples: dict[str, tuple[float, ...]] = {}
    summary: dict[str, dict[str, float | int]] = {}
    for position in POSITIONS:
        board_bests = [
            float(board["positions"][position]["max"])
            for board in metrics["boards"]
            if board["positions"][position]["max"] is not None
        ]
        cutoff = _quantile(board_bests, ACCEPTED_BOARD_QUANTILE)
        accepted = tuple(value for value in board_bests if value >= cutoff)
        samples[position] = accepted
        summary[position] = {
            "source_boards": len(board_bests),
            "accepted_boards": len(accepted),
            "acceptance_quantile": ACCEPTED_BOARD_QUANTILE,
            "cutoff": round(cutoff, 3),
            "mean": round(statistics.fmean(accepted), 3),
            "max": round(max(accepted), 3),
        }

    fresh_probability = continuation_probability(
        [],
        set(POSITIONS),
        samples,
    )
    result = (samples, summary, fresh_probability)
    _POSITION_MODEL_CACHE[cache_key] = result
    return result


def continuation_probability(
    cards: list[Card],
    opens: set[str],
    position_samples: dict[str, tuple[float, ...]],
    *,
    trials: int = 15_000,
    seed: int = 17,
) -> float:
    if not opens:
        return 1.0 if exact_team_score(cards) >= THRESHOLD else 0.0
    current = sum(card.raw_composite for card in cards)
    missing_defense = sum(card.stl is None or card.blk is None for card in cards)
    latent_historical_bonus = missing_defense * 2.45
    need = THRESHOLD - current - latent_historical_bonus
    generator = random.Random(seed)
    hits = 0
    for _ in range(trials):
        total = 0.0
        for position in sorted(opens):
            total += generator.choice(position_samples[position])
        hits += total >= need
    return hits / trials


def practical_ceiling(
    cards: list[Card],
    opens: set[str],
    position_samples: dict[str, tuple[float, ...]],
) -> float:
    return sum(card.raw_composite for card in cards) + sum(
        max(position_samples[position]) for position in opens
    )


def speedrun_value(probability: float, remaining_picks: float) -> float:
    """Approximate successes per future spin from the current decision point."""
    return probability / max(float(remaining_picks), 0.25)


def stage_continue_margin(remaining_picks: int) -> float:
    """Tolerance for model uncertainty, tightening as rescue options disappear."""
    return {
        4: 0.72,
        3: 0.80,
        2: 0.88,
        1: 0.96,
        0: 1.00,
    }.get(remaining_picks, 0.72)


def roster_outlook(
    roster: list[Card],
    metrics: dict[str, Any],
) -> dict[str, float | int | list[str]]:
    position_samples, _, fresh_probability = empirical_position_model(metrics)
    opens = open_positions(roster)
    probability = continuation_probability(roster, opens, position_samples)
    remaining_picks = len(opens)
    restart_value = speedrun_value(
        fresh_probability,
        len(POSITIONS) + RESTART_OVERHEAD_TURNS,
    )
    continuation_value = speedrun_value(probability, remaining_picks)
    relative = continuation_value / restart_value if restart_value else 0.0
    estimated_score = sum(card.raw_composite for card in roster) + 2.45 * sum(
        card.stl is None or card.blk is None for card in roster
    )
    required_average = (
        max(0.0, THRESHOLD - estimated_score) / remaining_picks
        if remaining_picks
        else 0.0
    )
    return {
        "probability": round(probability, 4),
        "remaining_picks": remaining_picks,
        "relative_to_restart": round(relative, 3),
        "continue_threshold": stage_continue_margin(remaining_picks),
        "required_average_remaining": round(required_average, 3),
        "open_positions": sorted(opens),
    }


def board_quality_for_positions(
    board: dict[str, Any], open_positions: set[str] | None = None
) -> float:
    if not open_positions:
        return float(board["board_quality"])
    position_values = []
    for position in sorted(open_positions):
        metrics = board["positions"].get(position)
        if not metrics or metrics["count"] == 0:
            continue
        position_values.append(
            0.65 * float(metrics["max"]) + 0.35 * float(metrics["p90"])
        )
    return (
        sum(position_values) / len(position_values)
        if position_values
        else float(board["board_quality"])
    )


def reroll_expected_quality(
    boards: dict[tuple[str, str], dict[str, Any]],
    team: str,
    era: str,
    kind: str,
    open_positions: set[str] | None = None,
) -> float | None:
    if kind == "TEAM":
        pool = [
            board_quality_for_positions(board, open_positions)
            for (board_team, board_era), board in boards.items()
            if board_era == era.lower() and board_team != team.upper()
        ]
    else:
        pool = [
            board_quality_for_positions(board, open_positions)
            for (board_team, board_era), board in boards.items()
            if board_team == team.upper() and board_era != era.lower()
        ]
    return sum(pool) / len(pool) if pool else None


def best_legal_candidate_outlook(
    roster: list[Card],
    board_cards: list[Card],
    position_model: dict[str, dict[str, float | int]],
) -> dict[str, Any] | None:
    roster_ids = {card.id for card in roster}
    roster_players = {card.player.casefold() for card in roster}
    best: dict[str, Any] | None = None
    for card in board_cards:
        if (
            not card.playable
            or card.id in roster_ids
            or card.player.casefold() in roster_players
        ):
            continue
        proposed = roster + [card]
        legal_assignments = assignments(proposed)
        if not legal_assignments:
            continue
        final_score = exact_team_score(proposed) if len(proposed) == 5 else None
        estimated_committed = sum(
            selected.raw_composite for selected in proposed
        ) + 2.45 * sum(
            selected.stl is None or selected.blk is None
            for selected in proposed
        )
        for assignment in legal_assignments:
            opens = set(POSITIONS) - set(assignment.values())
            path_value = (
                final_score
                if final_score is not None
                else estimated_committed
                + sum(float(position_model[position]["mean"]) for position in opens)
            )
            candidate = {
                "card_id": card.id,
                "player": card.player,
                "raw_composite": round(card.raw_composite, 3),
                "take_position": assignment[card.id],
                "open_after": sorted(opens),
                "path_value": round(path_value, 3),
                "final_score": (
                    round(final_score, 3) if final_score is not None else None
                ),
            }
            if best is None or candidate["path_value"] > best["path_value"]:
                best = candidate
    return best


def reroll_best_legal_outlook(
    roster: list[Card],
    cards: list[Card],
    *,
    team: str,
    era: str,
    kind: str,
    position_model: dict[str, dict[str, float | int]],
    current_best: dict[str, Any] | None,
) -> dict[str, Any] | None:
    cards_by_board: dict[tuple[str, str], list[Card]] = defaultdict(list)
    for card in cards:
        if card.playable:
            cards_by_board[(card.team.upper(), card.era.lower())].append(card)
    if kind == "TEAM":
        keys = [
            key
            for key in cards_by_board
            if key[1] == era.lower() and key[0] != team.upper()
        ]
    else:
        keys = [
            key
            for key in cards_by_board
            if key[0] == team.upper() and key[1] != era.lower()
        ]
    outcomes: list[dict[str, Any]] = []
    for board_team, board_era in sorted(keys):
        best = best_legal_candidate_outlook(
            roster,
            cards_by_board[(board_team, board_era)],
            position_model,
        )
        if best is None:
            continue
        outcomes.append(
            {
                "team": board_team,
                "era": next(
                    card.era
                    for card in cards_by_board[(board_team, board_era)]
                ),
                **best,
            }
        )
    if not outcomes:
        return None
    current_value = (
        float(current_best["path_value"])
        if current_best is not None
        else 0.0
    )
    expected_value = statistics.fmean(
        float(outcome["path_value"]) for outcome in outcomes
    )
    better = [
        outcome
        for outcome in outcomes
        if float(outcome["path_value"]) > current_value
    ]
    return {
        "outcome_count": len(outcomes),
        "expected_best_legal_value": round(expected_value, 3),
        "current_best_legal_value": round(current_value, 3),
        "value_edge": round(expected_value - current_value, 3),
        "better_outcome_count": len(better),
        "better_outcome_probability": round(len(better) / len(outcomes), 6),
        "outcomes": sorted(
            outcomes,
            key=lambda outcome: outcome["path_value"],
            reverse=True,
        ),
    }


def final_turn_reroll_outlook(
    roster: list[Card],
    cards: list[Card],
    *,
    team: str,
    era: str,
    kind: str,
) -> dict[str, Any] | None:
    if len(roster) != 4:
        return None
    cards_by_board: dict[tuple[str, str], list[Card]] = defaultdict(list)
    roster_ids = {card.id for card in roster}
    roster_players = {card.player.casefold() for card in roster}
    for card in cards:
        if (
            card.playable
            and card.id not in roster_ids
            and card.player.casefold() not in roster_players
        ):
            cards_by_board[(card.team.upper(), card.era.lower())].append(card)

    if kind == "TEAM":
        eligible_boards = [
            key
            for key in cards_by_board
            if key[1] == era.lower() and key[0] != team.upper()
        ]
    else:
        eligible_boards = [
            key
            for key in cards_by_board
            if key[0] == team.upper() and key[1] != era.lower()
        ]
    if not eligible_boards:
        return None

    outcomes: list[dict[str, Any]] = []
    for board_team, board_era in sorted(eligible_boards):
        best_card: Card | None = None
        best_score: float | None = None
        best_position: str | None = None
        for card in cards_by_board[(board_team, board_era)]:
            final_roster = roster + [card]
            assignment = best_assignment(final_roster)
            if not assignment:
                continue
            score = exact_team_score(final_roster)
            if best_score is None or score > best_score:
                best_score = score
                best_card = card
                best_position = assignment[card.id]
        if best_card is None or best_score is None:
            continue
        outcomes.append(
            {
                "team": board_team,
                "era": next(
                    card.era
                    for card in cards_by_board[(board_team, board_era)]
                ),
                "card_id": best_card.id,
                "player": best_card.player,
                "position": best_position,
                "final_score": round(best_score, 3),
                "wins": best_score >= THRESHOLD,
            }
        )

    if not outcomes:
        return None
    winning = [outcome for outcome in outcomes if outcome["wins"]]
    return {
        "outcome_count": len(outcomes),
        "winning_outcome_count": len(winning),
        "win_probability": round(len(winning) / len(outcomes), 6),
        "expected_best_final_score": round(
            statistics.fmean(outcome["final_score"] for outcome in outcomes),
            3,
        ),
        "winning_outcomes": sorted(
            winning,
            key=lambda outcome: outcome["final_score"],
            reverse=True,
        ),
    }


def solve(
    state: dict[str, Any],
    cards: list[Card],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    position_samples, position_model, fresh_probability = (
        empirical_position_model(metrics)
    )
    roster = [find_one(cards, spec) for spec in state.get("roster", [])]
    candidates = [find_one(cards, spec) for spec in state.get("candidates", [])]
    team = state.get("current_team")
    era = state.get("current_era")
    team_rerolls = int(state.get("team_rerolls", 0))
    era_rerolls = int(state.get("era_rerolls", 0))
    configured_margin = state.get("continue_vs_restart_margin")
    preserve_reroll_ratio = float(state.get("preserve_reroll_ratio", 1.25))

    current_assignment = best_assignment(roster)
    current_opens = open_positions(roster)
    output: dict[str, Any] = {
        "objective": "82-0 or bust / speedrun",
        "model_status": (
            "Complete card database with empirical accepted-board positional "
            "replacement distributions; action policy remains simulated."
        ),
        "current_assignment": display_assignment(roster, current_assignment),
        "open_positions": sorted(current_opens),
        "current_practical_ceiling": round(
            practical_ceiling(roster, current_opens, position_samples), 2
        ),
        "stage": len(roster) + 1,
        "fresh_run_probability_estimate": round(fresh_probability, 4),
        "restart_speedrun_value": round(
            speedrun_value(
                fresh_probability,
                len(POSITIONS) + RESTART_OVERHEAD_TURNS,
            ),
            6,
        ),
        "restart_turn_equivalent": len(POSITIONS) + RESTART_OVERHEAD_TURNS,
        "position_replacement_model": position_model,
    }

    candidate_options: list[dict[str, Any]] = []
    roster_players = {card.player.casefold() for card in roster}
    for card in candidates:
        if card.player.casefold() in roster_players:
            continue
        new_roster = roster + [card]
        assignment = best_assignment(new_roster)
        if not assignment:
            continue
        opens = open_positions(new_roster)
        probability = continuation_probability(
            new_roster,
            opens,
            position_samples,
        )
        remaining_picks = len(opens)
        continuation_value = speedrun_value(probability, remaining_picks)
        restart_value = speedrun_value(
            fresh_probability,
            len(POSITIONS) + RESTART_OVERHEAD_TURNS,
        )
        relative_value = (
            continuation_value / restart_value if restart_value else 0.0
        )
        continue_threshold = (
            float(configured_margin)
            if configured_margin is not None
            else stage_continue_margin(remaining_picks)
        )
        estimated_score = sum(
            selected.raw_composite for selected in new_roster
        ) + 2.45 * sum(
            selected.stl is None or selected.blk is None
            for selected in new_roster
        )
        required_average = (
            max(0.0, THRESHOLD - estimated_score) / remaining_picks
            if remaining_picks
            else 0.0
        )
        final_score = exact_team_score(new_roster) if len(new_roster) == 5 else None
        candidate_options.append(
            {
                "id": card.id,
                "player": card.player,
                "take_position": assignment[card.id],
                "assignment_after_pick": display_assignment(
                    new_roster, assignment
                ),
                "raw_composite": round(card.raw_composite, 2),
                "source_flex_value": round(card.source_value, 2),
                "open_after": sorted(opens),
                "survival_probability_estimate": round(probability, 3),
                "remaining_picks": remaining_picks,
                "required_average_remaining": round(required_average, 3),
                "continuation_speedrun_value": round(continuation_value, 6),
                "restart_speedrun_value": round(restart_value, 6),
                "relative_to_restart": round(relative_value, 3),
                "continue_threshold": continue_threshold,
                "practical_ceiling_after_pick": round(
                    practical_ceiling(
                        new_roster,
                        opens,
                        position_samples,
                    ),
                    3,
                ),
                "final_score": (
                    round(final_score, 2) if final_score is not None else None
                ),
                "82_0": (
                    final_score >= THRESHOLD if final_score is not None else None
                ),
            }
        )
    candidate_options.sort(
        key=lambda option: (
            option["82_0"] is True,
            option["survival_probability_estimate"],
            option["raw_composite"],
        ),
        reverse=True,
    )
    output["candidate_options"] = candidate_options

    boards = board_index(metrics)
    current_best_legal = best_legal_candidate_outlook(
        roster,
        candidates,
        position_model,
    )
    output["current_best_legal_outlook"] = current_best_legal
    current_board = (
        boards.get((str(team).upper(), str(era).lower()))
        if team and era
        else None
    )
    current_quality = (
        board_quality_for_positions(current_board, current_opens)
        if current_board is not None
        else None
    )
    reroll_options: list[dict[str, Any]] = []
    for kind, count in (("TEAM", team_rerolls), ("ERA", era_rerolls)):
        if count <= 0 or current_quality is None or not team or not era:
            continue
        best_legal_outlook = reroll_best_legal_outlook(
            roster,
            cards,
            team=str(team),
            era=str(era),
            kind=kind,
            position_model=position_model,
            current_best=current_best_legal,
        )
        if best_legal_outlook is None:
            continue
        expected = float(
            best_legal_outlook["expected_best_legal_value"]
        )
        edge = float(best_legal_outlook["value_edge"])
        preserve_penalty = max(0.8, 3.1 - 0.5 * len(roster))
        final_outlook = final_turn_reroll_outlook(
            roster,
            cards,
            team=str(team),
            era=str(era),
            kind=kind,
        )
        exact_relative = None
        exact_worth = False
        if final_outlook is not None:
            exact_value = speedrun_value(
                float(final_outlook["win_probability"]),
                1.0,
            )
            restart_value = speedrun_value(
                fresh_probability,
                len(POSITIONS) + RESTART_OVERHEAD_TURNS,
            )
            exact_relative = exact_value / restart_value if restart_value else 0.0
            exact_worth = (
                float(final_outlook["win_probability"]) > 0
                and exact_relative >= stage_continue_margin(1)
            )
        reroll_options.append(
            {
                "action": f"{kind} REROLL",
                "current_board_quality": best_legal_outlook[
                    "current_best_legal_value"
                ],
                "expected_board_quality": round(expected, 3),
                "quality_edge": round(edge, 3),
                "current_best_legal_value": best_legal_outlook[
                    "current_best_legal_value"
                ],
                "expected_best_legal_value": best_legal_outlook[
                    "expected_best_legal_value"
                ],
                "better_outcome_probability": best_legal_outlook[
                    "better_outcome_probability"
                ],
                "best_legal_outlook": best_legal_outlook,
                "preserve_penalty": round(preserve_penalty, 3),
                "worth_now": exact_worth or edge > preserve_penalty,
                "basis": (
                    "exact final-turn board enumeration"
                    if final_outlook is not None
                    else "best legal candidate on each possible reroll board"
                ),
                "open_positions": sorted(current_opens),
                "final_turn_outlook": final_outlook,
                "relative_to_restart": (
                    round(exact_relative, 3)
                    if exact_relative is not None
                    else None
                ),
            }
        )
    output["reroll_options"] = reroll_options

    best = candidate_options[0] if candidate_options else None
    worthwhile = [option for option in reroll_options if option["worth_now"]]
    if not candidate_options:
        if worthwhile:
            reroll = max(worthwhile, key=lambda option: option["quality_edge"])
            decision = (
                f"{reroll['action']} — the current board is weak relative to "
                "the data-derived alternative."
            )
        else:
            decision = "AWAIT PLAYER OFFER — current spin is worth playing."
    elif best["82_0"]:
        decision = (
            f"TAKE {best['player']} at {best['take_position']} — projected "
            f"{best['final_score']:.2f}; 82-0 secured."
        )
    else:
        take_probability = best["survival_probability_estimate"]
        relative_value = best["relative_to_restart"]
        continue_margin = best["continue_threshold"]
        if relative_value >= preserve_reroll_ratio:
            decision = (
                f"TAKE {best['player']} at {best['take_position']} — "
                f"speedrun value is {relative_value:.2f}× restarting; "
                "preserve rerolls."
            )
        elif worthwhile:
            reroll = max(
                worthwhile,
                key=lambda option: (
                    (
                        option["final_turn_outlook"]["win_probability"]
                        if option["final_turn_outlook"] is not None
                        else -1
                    ),
                    option["quality_edge"],
                ),
            )
            if reroll["final_turn_outlook"] is not None:
                outlook = reroll["final_turn_outlook"]
                decision = (
                    f"{reroll['action']} — {outlook['winning_outcome_count']} of "
                    f"{outlook['outcome_count']} possible reroll boards "
                    f"({outlook['win_probability']:.1%}) contain a legal "
                    "82-0 finish."
                )
            else:
                decision = (
                    f"{reroll['action']} — current heuristic continuation is "
                    f"~{take_probability:.0%}, and the data-derived board edge "
                    "justifies spending a flip."
                )
        elif best["practical_ceiling_after_pick"] < THRESHOLD:
            decision = (
                "END RUN / START OVER — practical remaining-slot ceiling "
                "cannot reach 109.5."
            )
        elif relative_value >= continue_margin:
            decision = (
                f"TAKE {best['player']} at {best['take_position']} — "
                f"{take_probability:.1%} continuation is {relative_value:.2f}× "
                "the stage-adjusted restart pace."
            )
        else:
            decision = (
                "END RUN / START OVER — current path has "
                f"{relative_value:.2f}× the success-per-time value of restarting, "
                f"below the stage-{len(roster) + 1} threshold of "
                f"{continue_margin:.2f}×."
            )
    output["decision"] = decision
    return output
