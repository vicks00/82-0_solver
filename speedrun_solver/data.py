from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import Card

CARD_COLUMNS = (
    "id",
    "player",
    "team",
    "era",
    "positions",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "stl_historically_unavailable",
    "blk_historically_unavailable",
    "raw_composite",
    "source_contribution",
    "source_value",
    "flex_score",
    "tier",
    "tier_label",
    "overall_rank",
    "spin_rank",
    "perfect_share",
    "playable",
)


def optional_float(value: str | None) -> float | None:
    if value is None or value.strip().lower() in {"", "n/a", "na", "null", "none"}:
        return None
    return float(value)


def optional_int(value: str | None) -> int | None:
    parsed = optional_float(value)
    return None if parsed is None else int(parsed)


def parse_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no", ""}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def load_cards(path: str | Path) -> list[Card]:
    source = Path(path)
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(CARD_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{source} is missing card columns: {sorted(missing)}")
        cards = [
            Card(
                id=row["id"],
                player=row["player"],
                team=row["team"],
                era=row["era"],
                positions=tuple(
                    position.strip()
                    for position in row["positions"].split("/")
                    if position.strip()
                ),
                pts=float(row["pts"]),
                reb=float(row["reb"]),
                ast=float(row["ast"]),
                stl=optional_float(row["stl"]),
                blk=optional_float(row["blk"]),
                raw_composite=float(row["raw_composite"]),
                source_contribution=float(row["source_contribution"]),
                source_value=float(row["source_value"]),
                flex_score=float(row["flex_score"]),
                tier=row["tier"],
                tier_label=row["tier_label"],
                overall_rank=optional_int(row["overall_rank"]),
                spin_rank=optional_int(row["spin_rank"]),
                perfect_share=optional_float(row["perfect_share"]),
                stl_historically_unavailable=parse_bool(
                    row["stl_historically_unavailable"]
                ),
                blk_historically_unavailable=parse_bool(
                    row["blk_historically_unavailable"]
                ),
                playable=parse_bool(row["playable"]),
            )
            for row in reader
        ]

    ids = [card.id for card in cards]
    keys = [card.key for card in cards]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{source} contains duplicate card IDs")
    if len(keys) != len(set(keys)):
        raise ValueError(f"{source} contains duplicate team/era/player keys")
    return cards


def load_metrics(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != 1 or not isinstance(payload.get("boards"), list):
        raise ValueError(f"{path} is not a supported team-era metrics file")
    return payload


def find_one(cards: list[Card], spec: dict[str, Any]) -> Card:
    if spec.get("id"):
        matches = [card for card in cards if card.id == spec["id"]]
    else:
        matches = cards
        if spec.get("player"):
            requested = str(spec["player"]).casefold()
            exact = [card for card in matches if card.player.casefold() == requested]
            matches = exact or [
                card for card in matches if requested in card.player.casefold()
            ]
        if spec.get("team"):
            matches = [
                card for card in matches if card.team.upper() == str(spec["team"]).upper()
            ]
        if spec.get("era"):
            matches = [
                card for card in matches if card.era.lower() == str(spec["era"]).lower()
            ]
    if len(matches) != 1:
        raise ValueError(f"Could not uniquely resolve {spec}; matches={len(matches)}")
    return matches[0]


def board_index(metrics: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (board["team"].upper(), board["era"].lower()): board
        for board in metrics["boards"]
    }
