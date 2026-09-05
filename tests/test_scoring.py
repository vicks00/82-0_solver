from __future__ import annotations

import pytest

from speedrun_solver.models import Card
from speedrun_solver.scoring import (
    best_assignment,
    exact_team_score,
    open_positions,
    raw_composite,
)


def make_card(
    card_id: str,
    player: str,
    positions: tuple[str, ...],
    *,
    pts: float = 10,
    reb: float = 5,
    ast: float = 3,
    stl: float | None = 1,
    blk: float | None = 1,
) -> Card:
    composite = raw_composite(pts, reb, ast, stl, blk)
    return Card(
        id=card_id,
        player=player,
        team="TST",
        era="2020s",
        positions=positions,
        pts=pts,
        reb=reb,
        ast=ast,
        stl=stl,
        blk=blk,
        raw_composite=composite,
        source_contribution=composite,
        source_value=composite,
        flex_score=0,
        stl_historically_unavailable=stl is None,
        blk_historically_unavailable=blk is None,
    )


def test_historical_defense_uses_known_lineup_average() -> None:
    roster = [
        make_card("a", "A", ("PG",), stl=1),
        make_card("b", "B", ("SG",), stl=3),
        make_card("c", "C", ("SF",), stl=None),
        make_card("d", "D", ("PF",), stl=None),
        make_card("e", "E", ("C",), stl=None),
    ]

    expected = raw_composite(
        pts=50,
        reb=25,
        ast=15,
        stl=10,
        blk=5,
    )
    assert exact_team_score(roster) == pytest.approx(expected)


def test_flexible_player_is_reassigned_for_new_point_guard() -> None:
    flexible = make_card("flex", "Flexible", ("PG", "PF"))
    point_guard = make_card("guard", "Point Guard", ("PG",))
    assignment = best_assignment([flexible, point_guard])

    assert assignment == {"flex": "PF", "guard": "PG"}
    assert open_positions([flexible, point_guard]) == {"SG", "SF", "C"}


def test_unplayable_card_has_no_legal_assignment() -> None:
    card = make_card("unknown", "Unknown", ())
    card = Card(
        **{
            field: getattr(card, field)
            for field in card.__dataclass_fields__
            if field != "playable"
        },
        playable=False,
    )
    assert best_assignment([card]) == {}
    assert open_positions([card]) == set()
