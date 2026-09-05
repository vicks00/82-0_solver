from __future__ import annotations

from pathlib import Path

from speedrun_solver.badges import player_badges
from speedrun_solver.models import Card


def card(
    *,
    player: str,
    tier: str,
    positions: tuple[str, ...],
) -> Card:
    return Card(
        id="test",
        player=player,
        team="TST",
        era="2020s",
        positions=positions,
        pts=1,
        reb=1,
        ast=1,
        stl=1,
        blk=1,
        raw_composite=1,
        source_contribution=1,
        source_value=1,
        flex_score=0,
        tier=tier,
    )


def test_s_tier_identity_badge_is_presentation_only() -> None:
    badges = player_badges(
        card(player="Wilt Chamberlain", tier="S+", positions=("C",))
    )
    assert {"kind": "identity", "icon": "🛸", "label": "THE STILT"} in badges
    assert not any(badge["kind"] == "tier" for badge in badges)


def test_elite_flexible_player_gets_flex_badge() -> None:
    badges = player_badges(
        card(
            player="LeBron James",
            tier="S",
            positions=("PG", "SG", "SF", "PF", "C"),
        )
    )
    assert any(badge["kind"] == "identity" for badge in badges)
    assert {
        "kind": "flex",
        "icon": "💎",
        "label": "5-position versatility",
    } in badges


def test_flex_gems_escalate_from_three_to_five_positions() -> None:
    three = player_badges(
        card(player="Role Player", tier="A", positions=("PG", "SG", "SF"))
    )
    four = player_badges(
        card(
            player="Role Player",
            tier="A",
            positions=("PG", "SG", "SF", "PF"),
        )
    )

    assert {"kind": "flex", "icon": "🔹", "label": "3-position versatility"} in three
    assert {"kind": "flex", "icon": "🔷", "label": "4-position versatility"} in four


def test_major_non_elite_player_gets_nickname_without_emoji() -> None:
    badges = player_badges(
        card(player="Pete Maravich", tier="B", positions=("PG",))
    )

    assert badges == [
        {"kind": "nickname", "icon": "", "label": "PISTOL PETE"}
    ]


def test_unrated_player_has_no_badges() -> None:
    assert player_badges(
        card(player="Role Player", tier="F", positions=("PG",))
    ) == []


def test_roster_badges_render_outside_truncated_name_line() -> None:
    app_js = (
        Path(__file__).resolve().parents[1] / "web" / "app.js"
    ).read_text(encoding="utf-8")
    assert '<div class="roster-badges">${badgesMarkup(card.badges)}</div>' in app_js
