from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionError(ValueError):
    """Raised when a run-state transition is not legal."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
    path.chmod(0o644)


@dataclass
class RunSession:
    """Persistent state for exactly one 82-0 speedrun at a time."""

    active: bool = False
    run_number: int = 0
    chase_started_at: str | None = None
    chase_finished_at: str | None = None
    clock_enabled: bool = False
    clock_running: bool = False
    clock_elapsed_seconds: float = 0.0
    clock_segment_started_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result: str | None = None
    final_score: float | None = None
    current_team: str | None = None
    current_era: str | None = None
    spin_open: bool = False
    team_rerolls: int = 0
    era_rerolls: int = 0
    roster: list[dict[str, str]] = field(default_factory=list)
    live_positions: dict[str, str] = field(default_factory=dict)
    candidates: list[dict[str, str]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    chance_history: list[dict[str, Any]] = field(default_factory=list)
    abort_below_probability: float = 0.18
    preserve_rerolls_above_probability: float = 0.62

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunSession:
        if data.get("schema_version", 1) != 1:
            raise SessionError("Unsupported session file version")
        return cls(
            active=bool(data.get("active", False)),
            run_number=int(data.get("run_number", 0)),
            chase_started_at=data.get("chase_started_at"),
            chase_finished_at=data.get("chase_finished_at"),
            clock_enabled=bool(data.get("clock_enabled", False)),
            clock_running=bool(data.get("clock_running", False)),
            clock_elapsed_seconds=float(
                data.get("clock_elapsed_seconds", 0.0)
            ),
            clock_segment_started_at=data.get("clock_segment_started_at"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            result=data.get("result"),
            final_score=(
                float(data["final_score"])
                if data.get("final_score") is not None
                else None
            ),
            current_team=data.get("current_team"),
            current_era=data.get("current_era"),
            spin_open=bool(data.get("spin_open", bool(data.get("candidates")))),
            team_rerolls=int(data.get("team_rerolls", 0)),
            era_rerolls=int(data.get("era_rerolls", 0)),
            roster=list(data.get("roster", [])),
            live_positions=dict(data.get("live_positions", {})),
            candidates=list(data.get("candidates", [])),
            history=list(data.get("history", [])),
            chance_history=list(data.get("chance_history", [])),
            abort_below_probability=float(
                data.get("abort_below_probability", 0.18)
            ),
            preserve_rerolls_above_probability=float(
                data.get("preserve_rerolls_above_probability", 0.62)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "active": self.active,
            "run_number": self.run_number,
            "chase_started_at": self.chase_started_at,
            "chase_finished_at": self.chase_finished_at,
            "clock_enabled": self.clock_enabled,
            "clock_running": self.clock_running,
            "clock_elapsed_seconds": self.clock_elapsed_seconds,
            "clock_segment_started_at": self.clock_segment_started_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "final_score": self.final_score,
            "current_team": self.current_team,
            "current_era": self.current_era,
            "spin_open": self.spin_open,
            "team_rerolls": self.team_rerolls,
            "era_rerolls": self.era_rerolls,
            "roster": self.roster,
            "live_positions": self.live_positions,
            "candidates": self.candidates,
            "history": self.history,
            "chance_history": self.chance_history,
            "abort_below_probability": self.abort_below_probability,
            "preserve_rerolls_above_probability": (
                self.preserve_rerolls_above_probability
            ),
        }

    def solver_state(self) -> dict[str, Any]:
        if not self.active:
            raise SessionError("No active run. Start a new run first.")
        return {
            "roster": self.roster,
            "candidates": self.candidates,
            "current_team": self.current_team,
            "current_era": self.current_era,
            "team_rerolls": self.team_rerolls,
            "era_rerolls": self.era_rerolls,
            "abort_below_probability": self.abort_below_probability,
            "preserve_rerolls_above_probability": (
                self.preserve_rerolls_above_probability
            ),
        }

    def start(
        self,
        team: str,
        era: str,
        *,
        team_rerolls: int,
        era_rerolls: int,
    ) -> None:
        if self.active:
            raise SessionError("A run is already active. End it before starting over.")
        if team_rerolls < 0 or era_rerolls < 0:
            raise SessionError("Reroll counts cannot be negative.")
        completed_chase = self.result == "82-0"
        if completed_chase:
            self.chance_history = []
        self.active = True
        self.run_number += 1
        self.started_at = _timestamp()
        self.finished_at = None
        self.result = None
        self.final_score = None
        self.current_team = team.upper()
        self.current_era = era
        self.spin_open = True
        self.team_rerolls = team_rerolls
        self.era_rerolls = era_rerolls
        self.roster = []
        self.live_positions = {}
        self.candidates = []
        self.history.append(
            {
                "at": _timestamp(),
                "event": "start",
                "run_number": self.run_number,
                "team": self.current_team,
                "era": self.current_era,
                "team_rerolls": team_rerolls,
                "era_rerolls": era_rerolls,
            }
        )

    def set_candidates(self, card_ids: list[str]) -> None:
        self._require_active()
        if not self.spin_open:
            raise SessionError("Enter the next team and era before adding an offer.")
        if not card_ids:
            raise SessionError("Provide at least one offered card ID.")
        if len(set(card_ids)) != len(card_ids):
            raise SessionError("The same card cannot be offered twice.")
        self.candidates = [{"id": card_id} for card_id in card_ids]
        self.history.append(
            {
                "at": _timestamp(),
                "event": "offer",
                "card_ids": card_ids,
            }
        )

    def take(self, card_id: str) -> None:
        self._require_active()
        if {"id": card_id} not in self.candidates:
            raise SessionError("That card is not in the active offer.")
        if len(self.roster) >= 5:
            raise SessionError("The roster is already full.")
        self.roster.append({"id": card_id})
        self.live_positions = {}
        self.candidates = []
        self.spin_open = False
        self.history.append(
            {"at": _timestamp(), "event": "take", "card_id": card_id}
        )

    def set_live_positions(self, positions: dict[str, str]) -> None:
        self._require_active()
        roster_ids = {spec["id"] for spec in self.roster}
        if set(positions) != roster_ids:
            raise SessionError(
                "Live lineup must assign every committed player exactly once."
            )
        if len(set(positions.values())) != len(positions):
            raise SessionError("Live lineup cannot use a position twice.")
        self.live_positions = positions
        self.history.append(
            {
                "at": _timestamp(),
                "event": "lineup",
                "positions": positions.copy(),
            }
        )

    def reroll_team(self, new_team: str) -> None:
        self._require_active()
        if not self.spin_open:
            raise SessionError("TEAM reroll is only available on an active spin.")
        if self.team_rerolls <= 0:
            raise SessionError("No TEAM rerolls remain.")
        old_team = self.current_team
        self.team_rerolls -= 1
        self.current_team = new_team.upper()
        self.candidates = []
        self.history.append(
            {
                "at": _timestamp(),
                "event": "team_reroll",
                "from": old_team,
                "to": self.current_team,
                "remaining": self.team_rerolls,
            }
        )

    def reroll_era(self, new_era: str) -> None:
        self._require_active()
        if not self.spin_open:
            raise SessionError("ERA reroll is only available on an active spin.")
        if self.era_rerolls <= 0:
            raise SessionError("No ERA rerolls remain.")
        old_era = self.current_era
        self.era_rerolls -= 1
        self.current_era = new_era
        self.candidates = []
        self.history.append(
            {
                "at": _timestamp(),
                "event": "era_reroll",
                "from": old_era,
                "to": self.current_era,
                "remaining": self.era_rerolls,
            }
        )

    def advance_spin(self, team: str, era: str) -> None:
        self._require_active()
        if self.spin_open:
            raise SessionError("Resolve the current spin before entering the next one.")
        old_team = self.current_team
        old_era = self.current_era
        self.current_team = team.upper()
        self.current_era = era
        self.spin_open = True
        self.candidates = []
        self.history.append(
            {
                "at": _timestamp(),
                "event": "next_spin",
                "from_team": old_team,
                "from_era": old_era,
                "team": self.current_team,
                "era": self.current_era,
            }
        )

    def end(self, reason: str = "manual") -> None:
        self._require_active()
        self.finished_at = _timestamp()
        self.result = "ended"
        self.final_score = None
        self.history.append(
            {
                "at": _timestamp(),
                "event": "end",
                "reason": reason,
                "team": self.current_team,
                "era": self.current_era,
                "roster": self.roster.copy(),
            }
        )
        self.active = False
        self.current_team = None
        self.current_era = None
        self.spin_open = False
        self.team_rerolls = 0
        self.era_rerolls = 0
        self.roster = []
        self.live_positions = {}
        self.candidates = []

    def complete(self, *, success: bool, final_score: float) -> None:
        self._require_active()
        self.finished_at = _timestamp()
        self.result = "82-0" if success else "missed"
        self.final_score = final_score
        if success and self.clock_enabled:
            self.chase_finished_at = self.finished_at
            self.pause_clock(record_history=False)
        self.history.append(
            {
                "at": self.finished_at,
                "event": "complete",
                "result": self.result,
                "final_score": final_score,
                "roster": self.roster.copy(),
            }
        )
        self.active = False
        self.spin_open = False
        self.candidates = []

    def clock_total_seconds(self) -> float:
        elapsed = self.clock_elapsed_seconds
        if self.clock_running and self.clock_segment_started_at:
            started = datetime.fromisoformat(self.clock_segment_started_at)
            elapsed += (datetime.now(timezone.utc) - started).total_seconds()
        return max(0.0, elapsed)

    def start_clock(self) -> None:
        if self.clock_running:
            return
        if not self.clock_enabled:
            self.clock_elapsed_seconds = 0.0
            self.chase_started_at = _timestamp()
            self.chase_finished_at = None
        self.clock_enabled = True
        self.clock_running = True
        self.clock_segment_started_at = _timestamp()
        self.history.append(
            {"at": self.clock_segment_started_at, "event": "clock_started"}
        )

    def pause_clock(self, *, record_history: bool = True) -> None:
        if not self.clock_enabled or not self.clock_running:
            return
        self.clock_elapsed_seconds = self.clock_total_seconds()
        self.clock_running = False
        self.clock_segment_started_at = None
        if record_history:
            self.history.append(
                {"at": _timestamp(), "event": "clock_paused"}
            )

    def reset_clock(self) -> None:
        if not self.clock_enabled:
            return
        self.clock_elapsed_seconds = 0.0
        self.chase_started_at = _timestamp()
        self.chase_finished_at = None
        self.clock_segment_started_at = (
            self.chase_started_at if self.clock_running else None
        )
        self.history.append(
            {
                "at": self.chase_started_at,
                "event": "clock_reset",
            }
        )

    def disable_clock(self) -> None:
        self.clock_enabled = False
        self.clock_running = False
        self.clock_elapsed_seconds = 0.0
        self.clock_segment_started_at = None
        self.chase_started_at = None
        self.chase_finished_at = None
        self.history.append(
            {"at": _timestamp(), "event": "clock_disabled"}
        )

    def record_chance(
        self,
        *,
        probability: float,
        relative_to_restart: float,
        continue_threshold: float,
        label: str,
    ) -> None:
        self.chance_history.append(
            {
                "at": _timestamp(),
                "run_number": self.run_number,
                "roster_size": len(self.roster),
                "probability": probability,
                "relative_to_restart": relative_to_restart,
                "continue_threshold": continue_threshold,
                "label": label,
            }
        )
        self.chance_history = self.chance_history[-200:]

    def remove_previous_completed_chase(self) -> bool:
        if not self.active or not self.chance_history:
            return False
        completed_indexes = [
            index
            for index, entry in enumerate(self.chance_history)
            if float(entry.get("probability", 0.0)) >= 0.999
            and int(entry.get("run_number", 0)) < self.run_number
        ]
        if not completed_indexes:
            return False
        self.chance_history = self.chance_history[
            completed_indexes[-1] + 1 :
        ]
        return True

    def _require_active(self) -> None:
        if not self.active:
            raise SessionError("No active run. Start a new run first.")


def load_session(path: str | Path) -> RunSession:
    source = Path(path)
    if not source.exists():
        return RunSession()
    with source.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SessionError("Session file must contain a JSON object.")
    return RunSession.from_dict(payload)


def save_session(path: str | Path, session: RunSession) -> None:
    _atomic_json(Path(path), session.to_dict())
