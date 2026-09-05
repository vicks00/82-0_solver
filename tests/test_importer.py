from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from speedrun_solver.data import load_cards, load_metrics
from speedrun_solver.importer import (
    ImportValidationError,
    import_cards,
    normalize_source,
)

FIXTURE = Path(__file__).parent / "fixtures" / "rankings_sample.json"


def test_offline_import_writes_normalized_artifacts(tmp_path: Path) -> None:
    report = import_cards(output_dir=tmp_path, input_json=FIXTURE)

    assert report["row_count"] == 7
    assert report["unique_key_count"] == 7
    assert report["playable_count"] == 6
    assert report["anomaly_count"] == 1
    assert report["missing_stl_count"] == 1
    assert report["missing_blk_count"] == 1

    cards = load_cards(tmp_path / "cards.csv")
    unknown = next(card for card in cards if card.id == "unknown_atl_2020s")
    assert not unknown.playable
    assert unknown.stl_historically_unavailable
    assert unknown.blk_historically_unavailable

    metrics = load_metrics(tmp_path / "team_era_metrics.json")
    assert metrics["card_count"] == 7
    assert metrics["playable_count"] == 6
    assert metrics["board_count"] == 1
    board = metrics["boards"][0]
    assert board["composite"]["probability_ge"]["20"] == pytest.approx(
        1 / 6, abs=1e-6
    )
    assert board["best_legal_assignment"]["assignment"]["PG"] == "alpha_atl_2020s"


def test_duplicate_composite_key_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    duplicate = copy.deepcopy(payload["rows"][0])
    duplicate["id"] = "different_id"
    payload["rows"].append(duplicate)

    with pytest.raises(ImportValidationError, match="Duplicate team/era/player key"):
        normalize_source(payload)


def test_schema_drift_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del payload["rows"][0]["ppg"]

    with pytest.raises(ImportValidationError, match="missing source fields"):
        normalize_source(payload)


def test_composite_mismatch_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["rows"][0]["contribution"] = 99

    with pytest.raises(ImportValidationError, match="differs from source"):
        normalize_source(payload)
