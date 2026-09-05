from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .models import Card
from .scoring import POSITION_INDEX, POSITIONS, exact_team_score

COMPOSITE_THRESHOLDS = (18.0, 20.0, 22.0)


def quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def distribution(values: Iterable[float]) -> dict[str, Any]:
    samples = list(values)
    if not samples:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
            "probability_ge": {str(int(value)): 0.0 for value in COMPOSITE_THRESHOLDS},
        }
    return {
        "count": len(samples),
        "mean": round(statistics.fmean(samples), 3),
        "median": round(statistics.median(samples), 3),
        "p75": round(quantile(samples, 0.75), 3),
        "p90": round(quantile(samples, 0.90), 3),
        "max": round(max(samples), 3),
        "probability_ge": {
            str(int(threshold)): round(
                sum(value >= threshold for value in samples) / len(samples), 6
            )
            for threshold in COMPOSITE_THRESHOLDS
        },
    }


def best_legal_assignment(cards: Iterable[Card]) -> dict[str, Any] | None:
    playable = tuple(card for card in cards if card.playable)
    # mask -> (composite sum, ((card id, position), ...))
    states: dict[int, tuple[float, tuple[tuple[str, str], ...]]] = {0: (0.0, ())}
    for card in playable:
        updated = dict(states)
        for mask, (score, selected) in states.items():
            for position in card.positions:
                position_index = POSITION_INDEX.get(position)
                if position_index is None:
                    continue
                bit = 1 << position_index
                if mask & bit:
                    continue
                candidate = (
                    score + card.raw_composite,
                    selected + ((card.id, position),),
                )
                current = updated.get(mask | bit)
                if current is None or candidate[0] > current[0]:
                    updated[mask | bit] = candidate
        states = updated

    full_mask = (1 << len(POSITIONS)) - 1
    result = states.get(full_mask)
    if result is None:
        return None
    score, selected = result
    by_id = {card.id: card for card in playable}
    selected_cards = [by_id[card_id] for card_id, _ in selected]
    assignment = {
        position: card_id
        for card_id, position in sorted(
            selected, key=lambda item: POSITION_INDEX[item[1]]
        )
    }
    return {
        "raw_composite_sum": round(score, 3),
        "team_score_with_historical_adjustment": round(
            exact_team_score(selected_cards), 3
        ),
        "assignment": assignment,
    }


def _top_cards(cards: list[Card], limit: int = 10) -> list[dict[str, Any]]:
    return [
        {
            "id": card.id,
            "player": card.player,
            "raw_composite": round(card.raw_composite, 3),
            "positions": list(card.positions),
        }
        for card in sorted(cards, key=lambda card: card.raw_composite, reverse=True)[
            :limit
        ]
    ]


def board_metrics(team: str, era: str, cards: list[Card]) -> dict[str, Any]:
    playable = [card for card in cards if card.playable]
    overall = distribution(card.raw_composite for card in playable)
    by_position: dict[str, Any] = {}
    for position in POSITIONS:
        eligible = [card for card in playable if position in card.positions]
        by_position[position] = {
            **distribution(card.raw_composite for card in eligible),
            "top_cards": _top_cards(eligible, 5),
        }

    legal = best_legal_assignment(playable)
    best_card = overall["max"] or 0.0
    p90 = overall["p90"] or 0.0
    legal_average = (
        legal["raw_composite_sum"] / len(POSITIONS) if legal is not None else 0.0
    )
    board_quality = 0.45 * best_card + 0.35 * legal_average + 0.20 * p90
    return {
        "team": team,
        "era": era,
        "card_count": len(cards),
        "playable_count": len(playable),
        "unplayable_count": len(cards) - len(playable),
        "position_coverage": [
            position
            for position in POSITIONS
            if any(position in card.positions for card in playable)
        ],
        "composite": overall,
        "positions": by_position,
        "top_cards": _top_cards(playable),
        "best_legal_assignment": legal,
        "board_quality": round(board_quality, 3),
    }


def derive_metrics(
    cards: Iterable[Card],
    *,
    generated_at: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card_list = list(cards)
    grouped: dict[tuple[str, str], list[Card]] = defaultdict(list)
    for card in card_list:
        grouped[(card.team, card.era)].append(card)

    boards = [
        board_metrics(team, era, board_cards)
        for (team, era), board_cards in sorted(grouped.items())
    ]
    playable = [card for card in card_list if card.playable]
    global_positions = {
        position: distribution(
            card.raw_composite for card in playable if position in card.positions
        )
        for position in POSITIONS
    }
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "source": source or {},
        "card_count": len(card_list),
        "playable_count": len(playable),
        "board_count": len(boards),
        "board_quality_formula": (
            "0.45*best_raw_composite + "
            "0.35*best_legal_raw_composite_average + 0.20*p90_raw_composite"
        ),
        "global_positions": global_positions,
        "boards": boards,
    }
