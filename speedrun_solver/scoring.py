from __future__ import annotations

from collections.abc import Iterable

from .models import Card

POSITIONS = ("PG", "SG", "SF", "PF", "C")
POSITION_INDEX = {position: index for index, position in enumerate(POSITIONS)}
WEIGHTS = {
    "pts": 0.3448,
    "reb": 0.6297,
    "ast": 0.6143,
    "stl": 1.1475,
    "blk": 1.25,
}
THRESHOLD = 109.5

# This remains a prototype tie-breaker until the policy engine evaluates the
# continuation value of each legal assignment directly.
POSITION_SCARCITY = {"PG": 0.8, "SG": 1.0, "SF": 1.2, "PF": 0.35, "C": 0.0}


def raw_composite(
    pts: float,
    reb: float,
    ast: float,
    stl: float | None,
    blk: float | None,
) -> float:
    return (
        WEIGHTS["pts"] * pts
        + WEIGHTS["reb"] * reb
        + WEIGHTS["ast"] * ast
        + WEIGHTS["stl"] * (stl or 0.0)
        + WEIGHTS["blk"] * (blk or 0.0)
    )


def exact_team_score(cards: Iterable[Card]) -> float:
    roster = tuple(cards)
    pts = sum(card.pts for card in roster)
    reb = sum(card.reb for card in roster)
    ast = sum(card.ast for card in roster)
    known_stl = [card.stl for card in roster if card.stl is not None]
    known_blk = [card.blk for card in roster if card.blk is not None]
    roster_size = len(roster)
    stl = sum(known_stl) * roster_size / len(known_stl) if known_stl else 0.0
    blk = sum(known_blk) * roster_size / len(known_blk) if known_blk else 0.0
    return raw_composite(pts, reb, ast, stl, blk)


def assignments(cards: Iterable[Card]) -> list[dict[str, str]]:
    roster = tuple(cards)
    results: list[dict[str, str]] = []

    def visit(index: int, used: set[str], current: dict[str, str]) -> None:
        if index == len(roster):
            results.append(current.copy())
            return
        card = roster[index]
        if not card.playable:
            return
        for position in card.positions:
            if position in POSITION_INDEX and position not in used:
                used.add(position)
                current[card.id] = position
                visit(index + 1, used, current)
                current.pop(card.id)
                used.remove(position)

    visit(0, set(), {})
    return results


def best_assignment(cards: Iterable[Card]) -> dict[str, str]:
    roster = tuple(cards)
    legal = assignments(roster)
    if not legal:
        return {}
    return max(
        legal,
        key=lambda assignment: sum(
            POSITION_SCARCITY[assignment[card.id]] for card in roster
        ),
    )


def open_positions(cards: Iterable[Card]) -> set[str]:
    roster = tuple(cards)
    assignment = best_assignment(roster)
    if roster and not assignment:
        return set()
    return set(POSITIONS) - set(assignment.values())


def display_assignment(cards: Iterable[Card], assignment: dict[str, str]) -> dict[str, str]:
    by_id = {card.id: card.player for card in cards}
    return {
        position: by_id[card_id]
        for card_id, position in sorted(assignment.items(), key=lambda item: POSITION_INDEX[item[1]])
    }
