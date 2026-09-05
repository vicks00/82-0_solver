from __future__ import annotations

import json
from pathlib import Path

from speedrun_solver.importer import normalize_source
from speedrun_solver.metrics import derive_metrics

FIXTURE = Path(__file__).parent / "fixtures" / "rankings_sample.json"


def test_metrics_are_deterministic_and_use_distinct_cards() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cards, _ = normalize_source(payload)

    first = derive_metrics(
        cards,
        generated_at=payload["generatedAt"],
        source=payload["source"],
    )
    second = derive_metrics(
        cards,
        generated_at=payload["generatedAt"],
        source=payload["source"],
    )
    assert first == second

    assignment = first["boards"][0]["best_legal_assignment"]["assignment"]
    assert set(assignment) == {"PG", "SG", "SF", "PF", "C"}
    assert len(set(assignment.values())) == 5
    assert first["boards"][0]["positions"]["PG"]["count"] == 2
