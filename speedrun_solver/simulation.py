from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from .models import Card
from .scoring import POSITIONS, THRESHOLD, best_assignment, exact_team_score

DEFAULT_TRIALS = 400
ADAPTIVE_MAX_TRIALS = 1_200
REROLL_TURN_COST = 0.15
RESTART_TURN_COST = 0.75
DECISION_Z = 1.96


def _seed_for(
    roster: Iterable[Card],
    team_rerolls: int,
    era_rerolls: int,
) -> int:
    identity = "|".join(
        sorted(card.id for card in roster)
        + [str(team_rerolls), str(era_rerolls)]
    )
    return int.from_bytes(
        hashlib.blake2b(identity.encode(), digest_size=8).digest(),
        "big",
    )


def _index_boards(cards: Iterable[Card]) -> dict[tuple[str, str], list[Card]]:
    boards: dict[tuple[str, str], list[Card]] = defaultdict(list)
    for card in cards:
        if card.playable:
            boards[(card.team.upper(), card.era.lower())].append(card)
    for board_cards in boards.values():
        board_cards.sort(key=lambda card: card.raw_composite, reverse=True)
    return dict(boards)


def _best_legal_card(roster: list[Card], board_cards: list[Card]) -> Card | None:
    best_card: Card | None = None
    best_key: tuple[float, float] | None = None
    roster_ids = {selected.id for selected in roster}
    roster_players = {selected.player.casefold() for selected in roster}
    for card in board_cards:
        if card.id in roster_ids or card.player.casefold() in roster_players:
            continue
        proposed = roster + [card]
        assignment = best_assignment(proposed)
        if not assignment:
            continue
        # On the final card, the game score itself is the only objective.
        if len(proposed) == 5:
            key = (exact_team_score(proposed), card.raw_composite)
        else:
            # Composite remains the greedy baseline, while the number of
            # remaining legal open slots breaks ties in favor of flexibility.
            open_count = 5 - len(assignment)
            key = (card.raw_composite, float(open_count))
        if best_key is None or key > best_key:
            best_card = card
            best_key = key
    return best_card


def _random_alternate_board(
    boards: dict[tuple[str, str], list[Card]],
    team: str,
    era: str,
    kind: str,
    generator: random.Random,
) -> tuple[str, str] | None:
    if kind == "TEAM":
        options = [
            key
            for key in boards
            if key[1] == era.lower() and key[0] != team.upper()
        ]
    else:
        options = [
            key
            for key in boards
            if key[0] == team.upper() and key[1] != era.lower()
        ]
    return generator.choice(options) if options else None


def _play_final_turn(
    roster: list[Card],
    board_key: tuple[str, str],
    boards: dict[tuple[str, str], list[Card]],
    team_rerolls: int,
    era_rerolls: int,
    generator: random.Random,
) -> bool:
    team, era = board_key
    card = _best_legal_card(roster, boards[board_key])
    if card is not None and exact_team_score(roster + [card]) >= THRESHOLD:
        return True

    # Final-turn rerolls are evaluated as actual random alternate boards, not
    # average board quality. Spend each available reroll only after the
    # current board cannot finish the run.
    if team_rerolls:
        alternate = _random_alternate_board(
            boards, team, era, "TEAM", generator
        )
        if alternate is not None:
            team, era = alternate
            card = _best_legal_card(roster, boards[alternate])
            if card is not None and exact_team_score(roster + [card]) >= THRESHOLD:
                return True
    if era_rerolls:
        alternate = _random_alternate_board(
            boards, team, era, "ERA", generator
        )
        if alternate is not None:
            card = _best_legal_card(roster, boards[alternate])
            if card is not None and exact_team_score(roster + [card]) >= THRESHOLD:
                return True
    return False


def _complete_trial(
    simulated_roster: list[Card],
    boards: dict[tuple[str, str], list[Card]],
    board_keys: tuple[tuple[str, str], ...],
    team_rerolls: int,
    era_rerolls: int,
    generator: random.Random,
) -> bool:
    while len(simulated_roster) < 4:
        board = generator.choice(board_keys)
        card = _best_legal_card(simulated_roster, boards[board])
        if card is None:
            return False
        simulated_roster.append(card)
    if len(simulated_roster) != 4:
        return exact_team_score(simulated_roster) >= THRESHOLD
    final_board = generator.choice(board_keys)
    return _play_final_turn(
        simulated_roster,
        final_board,
        boards,
        team_rerolls,
        era_rerolls,
        generator,
    )


def _simulation_result(
    wins: int,
    trials: int,
    *,
    method: str,
    assumptions: list[str],
) -> dict[str, Any]:
    probability = wins / trials
    standard_error = (
        (probability * (1.0 - probability) / trials) ** 0.5
        if trials
        else 0.0
    )
    return {
        "probability": round(probability, 6),
        "wins": wins,
        "trials": trials,
        "standard_error": round(standard_error, 6),
        "method": method,
        "assumptions": assumptions,
    }


def simulate_completion_probability(
    cards: list[Card],
    roster: list[Card],
    *,
    team_rerolls: int,
    era_rerolls: int,
    trials: int = DEFAULT_TRIALS,
) -> dict[str, Any]:
    """Estimate 82-0 probability from random future actual team-era boards.

    The model samples uniformly from the imported valid boards, greedily takes
    the best legal current-board card, and samples remaining rerolls only on
    the final turn. It intentionally avoids the former independent
    best-quartile-per-position assumption.
    """
    boards = _index_boards(cards)
    board_keys = tuple(boards)
    if len(roster) >= 5:
        won = exact_team_score(roster) >= THRESHOLD
        return {
            "probability": 1.0 if won else 0.0,
            "wins": int(won),
            "trials": 1,
            "method": "exact completed roster",
            "assumptions": [],
        }

    generator = random.Random(_seed_for(roster, team_rerolls, era_rerolls))
    wins = 0
    for _ in range(trials):
        wins += _complete_trial(
            list(roster),
            boards,
            board_keys,
            team_rerolls,
            era_rerolls,
            generator,
        )
    return _simulation_result(
        wins,
        trials,
        method="actual-board Monte Carlo",
        assumptions=[
            "Future valid team-era boards are sampled uniformly.",
            "The best legal card on each future board is taken greedily.",
            "Remaining TEAM/ERA rerolls are sampled as random alternate boards on the final turn.",
        ],
    )


def simulate_reroll_action_probability(
    cards: list[Card],
    roster: list[Card],
    outcome_card_ids: list[str],
    *,
    team_rerolls_after: int,
    era_rerolls_after: int,
    trials: int = DEFAULT_TRIALS,
) -> dict[str, Any]:
    boards = _index_boards(cards)
    board_keys = tuple(boards)
    cards_by_id = {card.id: card for card in cards}
    outcome_cards = [
        cards_by_id[card_id]
        for card_id in outcome_card_ids
        if card_id in cards_by_id
    ]
    if not outcome_cards:
        return _simulation_result(
            0,
            trials,
            method="reroll-action Monte Carlo",
            assumptions=["No legal reroll outcomes were available."],
        )
    extra_seed = int.from_bytes(
        hashlib.blake2b(
            "|".join(sorted(outcome_card_ids)).encode(),
            digest_size=8,
        ).digest(),
        "big",
    )
    generator = random.Random(
        _seed_for(roster, team_rerolls_after, era_rerolls_after)
        ^ extra_seed
    )
    wins = 0
    for _ in range(trials):
        rerolled_card = generator.choice(outcome_cards)
        wins += _complete_trial(
            list(roster) + [rerolled_card],
            boards,
            board_keys,
            team_rerolls_after,
            era_rerolls_after,
            generator,
        )
    return _simulation_result(
        wins,
        trials,
        method="reroll-action Monte Carlo",
        assumptions=[
            "Each legal reroll destination is sampled uniformly.",
            "The best legal card on the resulting board is committed.",
            "The spent reroll is removed from all remaining simulations.",
        ],
    )


def _scenario_uniform(seed: int, channel: str, index: int) -> float:
    payload = f"{seed}|{channel}|{index}".encode()
    value = int.from_bytes(
        hashlib.blake2b(payload, digest_size=8).digest(),
        "big",
    )
    return value / float(2**64)


def _scenario_choice(
    values: tuple[tuple[str, str], ...],
    seed: int,
    channel: str,
    index: int,
) -> tuple[str, str] | None:
    if not values:
        return None
    uniform = _scenario_uniform(seed, channel, index)
    return values[min(int(uniform * len(values)), len(values) - 1)]


class _PolicyRollout:
    """Shared future policy used by every compared current action."""

    def __init__(self, cards: list[Card]) -> None:
        self.cards_by_id = {card.id: card for card in cards}
        self.boards = _index_boards(cards)
        self.board_keys = tuple(sorted(self.boards))

    @lru_cache(maxsize=200_000)
    def best_legal_id(
        self,
        roster_ids: tuple[str, ...],
        board_key: tuple[str, str],
    ) -> str | None:
        roster = [self.cards_by_id[card_id] for card_id in roster_ids]
        card = _best_legal_card(roster, self.boards[board_key])
        return card.id if card is not None else None

    @lru_cache(maxsize=100_000)
    def reroll_destinations(
        self,
        board_key: tuple[str, str],
        kind: str,
    ) -> tuple[tuple[str, str], ...]:
        team, era = board_key
        if kind == "TEAM":
            return tuple(
                key
                for key in self.board_keys
                if key[1] == era and key[0] != team
            )
        return tuple(
            key
            for key in self.board_keys
            if key[0] == team and key[1] != era
        )

    @lru_cache(maxsize=200_000)
    def expected_reroll_quality(
        self,
        roster_ids: tuple[str, ...],
        board_key: tuple[str, str],
        kind: str,
    ) -> float:
        roster = [self.cards_by_id[card_id] for card_id in roster_ids]
        assignment = best_assignment(roster)
        occupied = set(assignment.values()) if assignment else set()
        open_positions = tuple(
            position for position in POSITIONS if position not in occupied
        )
        values = [
            self.approximate_board_quality(open_positions, destination)
            for destination in self.reroll_destinations(board_key, kind)
        ]
        values = [value for value in values if math.isfinite(value)]
        return sum(values) / len(values) if values else -math.inf

    @lru_cache(maxsize=200_000)
    def approximate_board_quality(
        self,
        open_positions: tuple[str, ...],
        board_key: tuple[str, str],
    ) -> float:
        opens = set(open_positions)
        values = [
            card.raw_composite + 0.12 * card.flex_score
            for card in self.boards[board_key]
            if opens.intersection(card.positions)
        ]
        return max(values) if values else -math.inf

    def choose_board_action(
        self,
        roster_ids: tuple[str, ...],
        board_key: tuple[str, str],
        team_rerolls: int,
        era_rerolls: int,
    ) -> str:
        current_id = self.best_legal_id(roster_ids, board_key)
        if current_id is None:
            if team_rerolls and self.reroll_destinations(board_key, "TEAM"):
                return "TEAM_REROLL"
            if era_rerolls and self.reroll_destinations(board_key, "ERA"):
                return "ERA_REROLL"
            return "FAIL"

        if len(roster_ids) == 4:
            roster = [self.cards_by_id[card_id] for card_id in roster_ids]
            current_wins = (
                exact_team_score(roster + [self.cards_by_id[current_id]])
                >= THRESHOLD
            )
            if current_wins:
                return "TAKE"
            if team_rerolls:
                return "TEAM_REROLL"
            if era_rerolls:
                return "ERA_REROLL"
            return "TAKE"

        current = self.cards_by_id[current_id]
        current_quality = current.raw_composite + 0.12 * current.flex_score
        alternatives: list[tuple[float, str]] = []
        if team_rerolls:
            alternatives.append(
                (
                    self.expected_reroll_quality(
                        roster_ids, board_key, "TEAM"
                    ),
                    "TEAM_REROLL",
                )
            )
        if era_rerolls:
            alternatives.append(
                (
                    self.expected_reroll_quality(
                        roster_ids, board_key, "ERA"
                    ),
                    "ERA_REROLL",
                )
            )
        expected, action = max(alternatives, default=(-math.inf, "TAKE"))
        # Earlier stages preserve rerolls unless the complete card-transition
        # distribution shows a material immediate improvement.
        preservation_cost = max(0.35, 1.5 - 0.3 * len(roster_ids))
        return action if expected > current_quality + preservation_cost else "TAKE"

    def play_board(
        self,
        roster_ids: tuple[str, ...],
        board_key: tuple[str, str],
        team_rerolls: int,
        era_rerolls: int,
        *,
        seed: int,
        spin_index: int,
        channel_prefix: str,
    ) -> tuple[tuple[str, ...], int, int, float, bool]:
        turn_cost = 0.0
        while True:
            action = self.choose_board_action(
                roster_ids,
                board_key,
                team_rerolls,
                era_rerolls,
            )
            if action == "FAIL":
                return roster_ids, team_rerolls, era_rerolls, turn_cost, False
            if action == "TAKE":
                card_id = self.best_legal_id(roster_ids, board_key)
                if card_id is None:
                    return roster_ids, team_rerolls, era_rerolls, turn_cost, False
                return (
                    tuple(sorted((*roster_ids, card_id))),
                    team_rerolls,
                    era_rerolls,
                    turn_cost,
                    True,
                )

            kind = "TEAM" if action == "TEAM_REROLL" else "ERA"
            destinations = self.reroll_destinations(board_key, kind)
            destination = _scenario_choice(
                destinations,
                seed,
                f"{channel_prefix}-{kind.lower()}",
                spin_index,
            )
            if destination is None:
                return roster_ids, team_rerolls, era_rerolls, turn_cost, False
            if kind == "TEAM":
                team_rerolls -= 1
            else:
                era_rerolls -= 1
            turn_cost += REROLL_TURN_COST
            board_key = destination

    def run_continuation(
        self,
        roster: list[Card],
        *,
        team_rerolls: int,
        era_rerolls: int,
        seed: int,
        first_board: tuple[str, str] | None = None,
        first_board_channel: str = "future",
    ) -> tuple[bool, float]:
        roster_ids = tuple(sorted(card.id for card in roster))
        return self._run_continuation_ids(
            roster_ids,
            team_rerolls,
            era_rerolls,
            seed,
            first_board,
            first_board_channel,
        )

    @lru_cache(maxsize=100_000)
    def _run_continuation_ids(
        self,
        roster_ids: tuple[str, ...],
        team_rerolls: int,
        era_rerolls: int,
        seed: int,
        first_board: tuple[str, str] | None,
        first_board_channel: str,
    ) -> tuple[bool, float]:
        turns = 0.0
        spin_index = 0
        board_key = first_board
        while len(roster_ids) < 5:
            if board_key is None:
                board_key = _scenario_choice(
                    self.board_keys,
                    seed,
                    "future-board",
                    spin_index,
                )
                turns += 1.0
            if board_key is None:
                return False, turns
            (
                roster_ids,
                team_rerolls,
                era_rerolls,
                reroll_cost,
                took,
            ) = self.play_board(
                roster_ids,
                board_key,
                team_rerolls,
                era_rerolls,
                seed=seed,
                spin_index=spin_index,
                channel_prefix=first_board_channel,
            )
            turns += reroll_cost
            if not took:
                return False, turns
            board_key = None
            spin_index += 1
        completed = [self.cards_by_id[card_id] for card_id in roster_ids]
        return exact_team_score(completed) >= THRESHOLD, turns


_POLICY_ROLLOUTS: dict[int, _PolicyRollout] = {}


def _policy_for(cards: list[Card]) -> _PolicyRollout:
    key = id(cards)
    policy = _POLICY_ROLLOUTS.get(key)
    if policy is None or len(policy.cards_by_id) != len(cards):
        policy = _PolicyRollout(cards)
        _POLICY_ROLLOUTS[key] = policy
    return policy


def _projection(
    action: str,
    outcomes: list[tuple[bool, float]],
    restart_value: float | None = None,
) -> dict[str, Any]:
    trials = len(outcomes)
    wins = sum(won for won, _ in outcomes)
    probability = wins / trials if trials else 0.0
    observed_turns = (
        sum(turns for _, turns in outcomes) / trials if trials else math.inf
    )
    # Selecting the current card still costs time even when no future spin
    # remains. The floor also keeps paired final-turn comparisons finite.
    average_turns = max(observed_turns, 0.25)
    speedrun_value = probability / average_turns
    standard_error = (
        math.sqrt(probability * (1.0 - probability) / trials)
        if trials
        else 0.0
    )
    value_standard_error = (
        standard_error / average_turns if average_turns > 0 else 0.0
    )
    return {
        "action": action,
        "probability": round(probability, 6),
        "wins": wins,
        "trials": trials,
        "average_turns": round(average_turns, 4),
        "speedrun_value": round(speedrun_value, 8),
        "standard_error": round(standard_error, 6),
        "value_standard_error": round(value_standard_error, 8),
        "relative_to_restart": (
            round(speedrun_value / restart_value, 3)
            if restart_value
            else (1.0 if action == "END_RUN" else 0.0)
        ),
        "simulation": {
            "probability": round(probability, 6),
            "wins": wins,
            "trials": trials,
            "standard_error": round(standard_error, 6),
            "average_turns": round(average_turns, 4),
            "speedrun_value": round(speedrun_value, 8),
            "method": "paired stage-aware policy Monte Carlo",
            "assumptions": [
                "Every action uses identical downstream board and reroll scenarios.",
                "Future TEAM and ERA rerolls use the same stage-aware rollout policy.",
                "Restart overhead is charged; already elapsed time is excluded.",
            ],
        },
    }


def _paired_confidence(
    best_action: str,
    runner_up: str,
    outcomes: dict[str, list[tuple[bool, float]]],
    projections: dict[str, dict[str, Any]],
) -> tuple[float, float]:
    best_turns = float(projections[best_action]["average_turns"])
    other_turns = float(projections[runner_up]["average_turns"])
    differences = [
        (float(best_won) / best_turns) - (float(other_won) / other_turns)
        for (best_won, _), (other_won, _) in zip(
            outcomes[best_action],
            outcomes[runner_up],
            strict=True,
        )
    ]
    if len(differences) < 2:
        return 0.5, 0.0
    mean = sum(differences) / len(differences)
    variance = sum((value - mean) ** 2 for value in differences) / (
        len(differences) - 1
    )
    standard_error = math.sqrt(variance / len(differences))
    if standard_error == 0:
        return (1.0 if mean > 0 else 0.5), math.inf if mean > 0 else 0.0
    z_score = mean / standard_error
    confidence = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
    return confidence, z_score


def simulate_policy_continuation(
    cards: list[Card],
    roster: list[Card],
    *,
    team_rerolls: int,
    era_rerolls: int,
    trials: int = DEFAULT_TRIALS,
) -> dict[str, Any]:
    policy = _policy_for(cards)
    outcomes = [
        policy.run_continuation(
            roster,
            team_rerolls=team_rerolls,
            era_rerolls=era_rerolls,
            seed=trial,
        )
        for trial in range(trials)
    ]
    result = _projection("CONTINUE", outcomes)
    return result["simulation"]


def compare_speedrun_actions(
    cards: list[Card],
    roster: list[Card],
    *,
    current_team: str,
    current_era: str,
    take_card_id: str | None,
    team_rerolls: int,
    era_rerolls: int,
    initial_trials: int = DEFAULT_TRIALS,
    max_trials: int = ADAPTIVE_MAX_TRIALS,
) -> dict[str, Any]:
    """Compare current actions using paired scenarios and speedrun value."""

    policy = _policy_for(cards)
    current_board = (current_team.upper(), current_era.lower())
    cards_by_id = policy.cards_by_id
    action_names = ["TAKE"] if take_card_id in cards_by_id else []
    if team_rerolls and policy.reroll_destinations(current_board, "TEAM"):
        action_names.append("TEAM_REROLL")
    if era_rerolls and policy.reroll_destinations(current_board, "ERA"):
        action_names.append("ERA_REROLL")
    action_names.append("END_RUN")
    outcomes: dict[str, list[tuple[bool, float]]] = {
        action: [] for action in action_names
    }

    def run_action(action: str, seed: int) -> tuple[bool, float]:
        if action == "TAKE":
            return policy.run_continuation(
                roster + [cards_by_id[str(take_card_id)]],
                team_rerolls=team_rerolls,
                era_rerolls=era_rerolls,
                seed=seed,
            )
        if action in {"TEAM_REROLL", "ERA_REROLL"}:
            kind = "TEAM" if action == "TEAM_REROLL" else "ERA"
            destination = _scenario_choice(
                policy.reroll_destinations(current_board, kind),
                seed,
                f"current-{kind.lower()}",
                0,
            )
            if destination is None:
                return False, REROLL_TURN_COST
            won, turns = policy.run_continuation(
                roster,
                team_rerolls=team_rerolls - (kind == "TEAM"),
                era_rerolls=era_rerolls - (kind == "ERA"),
                seed=seed,
                first_board=destination,
                first_board_channel="current-reroll",
            )
            return won, turns + REROLL_TURN_COST
        won, turns = policy.run_continuation(
            [],
            team_rerolls=1,
            era_rerolls=1,
            seed=seed,
        )
        return won, turns + RESTART_TURN_COST

    target_trials = initial_trials
    adaptive_rounds = 0
    confidence = 0.5
    z_score = 0.0
    while True:
        start = len(next(iter(outcomes.values())))
        for trial in range(start, target_trials):
            seed = trial
            for action in action_names:
                outcomes[action].append(run_action(action, seed))

        preliminary = {
            action: _projection(action, values)
            for action, values in outcomes.items()
        }
        restart_value = float(preliminary["END_RUN"]["speedrun_value"])
        projections = {
            action: _projection(action, values, restart_value)
            for action, values in outcomes.items()
        }
        priority = {"TAKE": 3, "TEAM_REROLL": 2, "ERA_REROLL": 2, "END_RUN": 0}
        ranked = sorted(
            action_names,
            key=lambda action: (
                projections[action]["speedrun_value"],
                priority[action],
            ),
            reverse=True,
        )
        selected, runner_up = ranked[:2]
        confidence, z_score = _paired_confidence(
            selected,
            runner_up,
            outcomes,
            projections,
        )
        if confidence >= 0.975 or target_trials >= max_trials:
            break
        target_trials = min(target_trials + initial_trials, max_trials)
        adaptive_rounds += 1

    model_leader = selected
    restart_guard_applied = False
    reroll_guard_applied = False
    reroll_hurdle = 0.0
    reroll_improvement = None
    reroll_confidence = None
    if selected == "END_RUN" and confidence < 0.975:
        selected = max(
            (action for action in ranked if action != "END_RUN"),
            key=lambda action: (
                projections[action]["speedrun_value"],
                priority[action],
            ),
        )
        runner_up = "END_RUN"
        restart_guard_applied = True
    elif (
        selected in {"TEAM_REROLL", "ERA_REROLL"}
        and "TAKE" in projections
        and team_rerolls + era_rerolls == 1
    ):
        take_value = float(projections["TAKE"]["speedrun_value"])
        reroll_value = float(projections[selected]["speedrun_value"])
        reroll_improvement = (
            (reroll_value / take_value) - 1.0
            if take_value > 0
            else None
        )
        reroll_confidence, _ = _paired_confidence(
            selected,
            "TAKE",
            outcomes,
            projections,
        )
        remaining_after_take = max(4 - len(roster), 0)
        reroll_hurdle = 0.025 * remaining_after_take
        if (
            reroll_improvement is not None
            and (
                reroll_improvement < reroll_hurdle
                or reroll_confidence < 0.9
            )
        ):
            selected = "TAKE"
            runner_up = model_leader
            reroll_guard_applied = True

    for action, projection in projections.items():
        projection["selected"] = action == selected
        projection["label"] = (
            f"Take {cards_by_id[str(take_card_id)].player}"
            if action == "TAKE"
            else action.replace("_", " ").title()
        )

    return {
        "selected_action": selected,
        "runner_up": runner_up,
        "model_leader": model_leader,
        "restart_guard_applied": restart_guard_applied,
        "reroll_guard_applied": reroll_guard_applied,
        "reroll_hurdle": round(reroll_hurdle, 4),
        "reroll_improvement": (
            round(reroll_improvement, 4)
            if reroll_improvement is not None and math.isfinite(reroll_improvement)
            else reroll_improvement
        ),
        "reroll_confidence": (
            round(reroll_confidence, 4)
            if reroll_confidence is not None
            else None
        ),
        "confidence": round(confidence, 4),
        "confidence_z": round(z_score, 3),
        "confidence_label": (
            "high" if confidence >= 0.975 else "moderate"
            if confidence >= 0.9 else "low"
        ),
        "trials": target_trials,
        "adaptive_rounds": adaptive_rounds,
        "paired": True,
        "objective": "maximize estimated successful 82-0 runs per turn",
        "policy": "shared stage-aware TAKE/TEAM/ERA rollout policy",
        "actions": [projections[action] for action in action_names],
    }
