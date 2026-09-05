from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    player: str
    team: str
    era: str
    positions: tuple[str, ...]
    pts: float
    reb: float
    ast: float
    stl: float | None
    blk: float | None
    raw_composite: float
    source_contribution: float
    source_value: float
    flex_score: float
    tier: str = "Unrated"
    tier_label: str = ""
    overall_rank: int | None = None
    spin_rank: int | None = None
    perfect_share: float | None = None
    stl_historically_unavailable: bool = False
    blk_historically_unavailable: bool = False
    playable: bool = True

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.team.upper(), self.era.lower(), self.player.casefold())

    @property
    def display_key(self) -> str:
        return f"{self.team} / {self.era} / {self.player}"
