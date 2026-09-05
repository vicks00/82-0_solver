from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .data import CARD_COLUMNS
from .metrics import derive_metrics
from .models import Card
from .scoring import POSITION_INDEX, raw_composite

DEFAULT_SOURCE_URL = "https://82-0-guide.com/data/rankings.json"
USER_AGENT = "82-0-speedrun-solver/1.0 (+local research importer)"
SOURCE_REQUIRED_FIELDS = {
    "id",
    "player",
    "team",
    "era",
    "positions",
    "ppg",
    "rpg",
    "apg",
    "spg",
    "bpg",
    "contribution",
    "value",
    "flexScore",
}


class ImportValidationError(ValueError):
    pass


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    path.chmod(0o644)


def _atomic_json(path: Path, payload: Any) -> None:
    content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    _atomic_bytes(path, (content + "\n").encode("utf-8"))


def _request_with_retries(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    retries: int = 3,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            last_error = requests.HTTPError(
                f"Transient HTTP {response.status_code} from {url}",
                response=response,
            )
        except requests.RequestException as error:
            last_error = error
        if attempt + 1 < retries:
            time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def _robots_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _assert_robots_allowed(
    session: requests.Session,
    source_url: str,
    *,
    timeout: float,
) -> None:
    robots_url = _robots_url(source_url)
    response = _request_with_retries(session, robots_url, timeout=timeout)
    response.raise_for_status()
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())
    if not parser.can_fetch(USER_AGENT, source_url):
        raise PermissionError(f"robots.txt does not allow importing {source_url}")


def fetch_source(
    source_url: str,
    cache_dir: str | Path,
    *,
    refresh: bool = False,
    timeout: float = 30.0,
    min_request_interval: float = 0.25,
) -> tuple[bytes, dict[str, Any]]:
    cache = Path(cache_dir)
    payload_path = cache / "rankings.json"
    metadata_path = cache / "rankings.http.json"
    if payload_path.exists() and not refresh:
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.exists()
            else {}
        )
        metadata["cache_status"] = "hit"
        return payload_path.read_bytes(), metadata

    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    _assert_robots_allowed(session, source_url, timeout=timeout)
    time.sleep(max(0.0, min_request_interval))

    previous = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    conditional_headers: dict[str, str] = {}
    if previous.get("etag"):
        conditional_headers["If-None-Match"] = previous["etag"]
    if previous.get("last_modified"):
        conditional_headers["If-Modified-Since"] = previous["last_modified"]

    response = _request_with_retries(
        session,
        source_url,
        headers=conditional_headers,
        timeout=timeout,
    )
    if response.status_code == 304:
        if not payload_path.exists():
            raise RuntimeError("Server returned 304 but no cached payload exists")
        previous["cache_status"] = "revalidated"
        previous["checked_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(metadata_path, previous)
        return payload_path.read_bytes(), previous

    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "json" not in content_type.lower():
        raise ImportValidationError(
            f"Expected JSON from {source_url}, received {content_type!r}"
        )
    payload = response.content
    metadata = {
        "url": source_url,
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "cache_status": "refreshed",
    }
    _atomic_bytes(payload_path, payload)
    _atomic_json(metadata_path, metadata)
    return payload, metadata


def load_source(
    *,
    input_json: str | Path | None = None,
    source_url: str = DEFAULT_SOURCE_URL,
    cache_dir: str | Path = ".cache/82-0-guide",
    refresh: bool = False,
    timeout: float = 30.0,
    min_request_interval: float = 0.25,
) -> tuple[bytes, dict[str, Any]]:
    if input_json is not None:
        path = Path(input_json)
        return path.read_bytes(), {
            "url": path.resolve().as_uri(),
            "cache_status": "local-input",
        }
    return fetch_source(
        source_url,
        cache_dir,
        refresh=refresh,
        timeout=timeout,
        min_request_interval=min_request_interval,
    )


def _number(
    row: dict[str, Any],
    field: str,
    *,
    nullable: bool = False,
) -> float | None:
    value = row.get(field)
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImportValidationError(
            f"Card {row.get('id', '<unknown>')} has invalid {field}: {value!r}"
        )
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ImportValidationError(
            f"Card {row.get('id', '<unknown>')} has invalid {field}: {value!r}"
        )
    return parsed


def normalize_source(payload: dict[str, Any]) -> tuple[list[Card], list[dict[str, Any]]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ImportValidationError("Source payload must contain a rows array")

    cards: list[Card] = []
    anomalies: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ImportValidationError(f"Row {index} is not an object")
        missing = SOURCE_REQUIRED_FIELDS - set(row)
        if missing:
            raise ImportValidationError(
                f"Row {index} is missing source fields: {sorted(missing)}"
            )

        card_id = str(row["id"]).strip()
        player = str(row["player"]).strip()
        team = str(row["team"]).strip().upper()
        era = str(row["era"]).strip()
        if not card_id or not player or not team or not era:
            raise ImportValidationError(f"Row {index} has an empty identity field")
        key = (team, era.lower(), player.casefold())
        if card_id in seen_ids:
            raise ImportValidationError(f"Duplicate source card ID: {card_id}")
        if key in seen_keys:
            raise ImportValidationError(
                f"Duplicate team/era/player key: {team} / {era} / {player}"
            )
        seen_ids.add(card_id)
        seen_keys.add(key)

        source_positions = row["positions"]
        if not isinstance(source_positions, list):
            raise ImportValidationError(f"Card {card_id} positions must be an array")
        positions = tuple(
            dict.fromkeys(str(position).strip().upper() for position in source_positions)
        )
        invalid_positions = [
            position for position in positions if position not in POSITION_INDEX
        ]
        playable = bool(positions) and not invalid_positions
        if not playable:
            anomalies.append(
                {
                    "id": card_id,
                    "player": player,
                    "team": team,
                    "era": era,
                    "issue": "missing_positions"
                    if not positions
                    else "invalid_positions",
                    "positions": list(positions),
                }
            )

        pts = _number(row, "ppg")
        reb = _number(row, "rpg")
        ast = _number(row, "apg")
        stl = _number(row, "spg", nullable=True)
        blk = _number(row, "bpg", nullable=True)
        contribution = _number(row, "contribution")
        source_value = _number(row, "value")
        flex_score = _number(row, "flexScore")
        assert pts is not None and reb is not None and ast is not None
        assert contribution is not None and source_value is not None
        assert flex_score is not None
        composite = raw_composite(pts, reb, ast, stl, blk)
        if abs(composite - contribution) > 0.01:
            raise ImportValidationError(
                f"Card {card_id} composite differs from source contribution: "
                f"{composite:.6f} vs {contribution:.6f}"
            )
        if abs((contribution + flex_score) - source_value) > 0.01:
            raise ImportValidationError(
                f"Card {card_id} source value is not contribution + flexScore"
            )

        cards.append(
            Card(
                id=card_id,
                player=player,
                team=team,
                era=era,
                positions=positions,
                pts=pts,
                reb=reb,
                ast=ast,
                stl=stl,
                blk=blk,
                raw_composite=composite,
                source_contribution=contribution,
                source_value=source_value,
                flex_score=flex_score,
                tier=str(row.get("tier", "Unrated")),
                tier_label=str(row.get("tierLabel", "")),
                overall_rank=_optional_int(row.get("overallRank")),
                spin_rank=_optional_int(row.get("promptRank")),
                perfect_share=_optional_float(row.get("perfectShare")),
                stl_historically_unavailable=stl is None,
                blk_historically_unavailable=blk is None,
                playable=playable,
            )
        )
    return cards, anomalies


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImportValidationError(f"Expected an optional number, received {value!r}")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ImportValidationError(f"Expected a finite number, received {value!r}")
    return parsed


def _optional_int(value: Any) -> int | None:
    parsed = _optional_float(value)
    return None if parsed is None else int(parsed)


def _card_row(card: Card) -> dict[str, Any]:
    return {
        "id": card.id,
        "player": card.player,
        "team": card.team,
        "era": card.era,
        "positions": "/".join(card.positions),
        "pts": card.pts,
        "reb": card.reb,
        "ast": card.ast,
        "stl": "" if card.stl is None else card.stl,
        "blk": "" if card.blk is None else card.blk,
        "stl_historically_unavailable": str(
            card.stl_historically_unavailable
        ).lower(),
        "blk_historically_unavailable": str(
            card.blk_historically_unavailable
        ).lower(),
        "raw_composite": round(card.raw_composite, 6),
        "source_contribution": card.source_contribution,
        "source_value": card.source_value,
        "flex_score": card.flex_score,
        "tier": card.tier,
        "tier_label": card.tier_label,
        "overall_rank": "" if card.overall_rank is None else card.overall_rank,
        "spin_rank": "" if card.spin_rank is None else card.spin_rank,
        "perfect_share": "" if card.perfect_share is None else card.perfect_share,
        "playable": str(card.playable).lower(),
    }


def write_cards(path: str | Path, cards: list[Card]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=target.parent,
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=CARD_COLUMNS)
        writer.writeheader()
        writer.writerows(_card_row(card) for card in cards)
        temporary = Path(handle.name)
    os.replace(temporary, target)
    target.chmod(0o644)


def import_cards(
    *,
    output_dir: str | Path,
    input_json: str | Path | None = None,
    source_url: str = DEFAULT_SOURCE_URL,
    cache_dir: str | Path = ".cache/82-0-guide",
    refresh: bool = False,
    timeout: float = 30.0,
    min_request_interval: float = 0.25,
) -> dict[str, Any]:
    raw_payload, http_metadata = load_source(
        input_json=input_json,
        source_url=source_url,
        cache_dir=cache_dir,
        refresh=refresh,
        timeout=timeout,
        min_request_interval=min_request_interval,
    )
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as error:
        raise ImportValidationError(f"Source is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ImportValidationError("Source JSON root must be an object")

    cards, anomalies = normalize_source(payload)
    output = Path(output_dir)
    write_cards(output / "cards.csv", cards)
    source_metadata = {
        "guide_url": http_metadata.get("url", source_url),
        "dataset": payload.get("source", {}).get("dataset"),
        "source_note": payload.get("source", {}).get("note"),
        "generated_at": payload.get("generatedAt"),
        "sha256": hashlib.sha256(raw_payload).hexdigest(),
    }
    metrics = derive_metrics(
        cards,
        generated_at=payload.get("generatedAt"),
        source=source_metadata,
    )
    _atomic_json(output / "team_era_metrics.json", metrics)

    report = {
        "schema_version": 1,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source": source_metadata,
        "cache_status": http_metadata.get("cache_status"),
        "row_count": len(cards),
        "unique_key_count": len({card.key for card in cards}),
        "team_count": len({card.team for card in cards}),
        "era_count": len({card.era for card in cards}),
        "board_count": len({(card.team, card.era) for card in cards}),
        "playable_count": sum(card.playable for card in cards),
        "missing_stl_count": sum(card.stl is None for card in cards),
        "missing_blk_count": sum(card.blk is None for card in cards),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
    _atomic_json(output / "import_report.json", report)
    return report
