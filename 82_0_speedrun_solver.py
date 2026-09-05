#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any

from speedrun_solver.data import (
    board_index,
    find_one,
    load_cards,
    load_metrics,
)
from speedrun_solver.engine import solve
from speedrun_solver.models import Card
from speedrun_solver.session import (
    SessionError,
    load_session,
    save_session,
)


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--state")
    parser.add_argument(
        "--session",
        help="Persistent session JSON. Starts an interactive speedrun loop.",
    )
    parser.add_argument("--cards", default=str(root / "data" / "cards.csv"))
    parser.add_argument(
        "--team-era-metrics",
        default=str(root / "data" / "team_era_metrics.json"),
    )
    return parser


def print_session_help() -> None:
    print(
        """Commands:
  start TEAM ERA [team-rerolls] [era-rerolls]
  next TEAM ERA
  offer CARD_ID [CARD_ID ...]
  take CARD_ID
  team TEAM
  era ERA
  status
  end
  help
  quit

Use the exact card ID from the database for offers, e.g.
offer oscar_robertson_sac_1960s
The session is saved after every state-changing command."""
    )


def _validate_board(
    boards: dict[tuple[str, str], dict[str, Any]],
    team: str,
    era: str,
) -> None:
    if (team.upper(), era.lower()) not in boards:
        raise SessionError(f"No card board exists for {team.upper()} {era}.")


def run_session(
    session_path: str | Path,
    cards: list[Card],
    metrics: dict[str, Any],
) -> None:
    session = load_session(session_path)
    boards = board_index(metrics)
    print(f"82-0 session: {Path(session_path)}")
    if session.active:
        print(
            f"Resumed run {session.run_number}: "
            f"{session.current_team} {session.current_era}, "
            f"{len(session.roster)} picks, "
            f"{session.team_rerolls} TEAM / "
            f"{session.era_rerolls} ERA rerolls."
        )
    else:
        print("No active run. Use: start TEAM ERA [team-rerolls] [era-rerolls]")

    while True:
        try:
            raw = input("82-0> ").strip()
        except EOFError:
            print()
            return
        if not raw:
            continue
        try:
            command = shlex.split(raw)
        except ValueError as error:
            print(f"Invalid command: {error}")
            continue
        verb, *arguments = command
        verb = verb.lower()
        try:
            changed = False
            if verb in {"quit", "exit"}:
                return
            if verb == "help":
                print_session_help()
            elif verb == "start":
                if len(arguments) not in {2, 4}:
                    raise SessionError(
                        "Usage: start TEAM ERA [team-rerolls] [era-rerolls]"
                    )
                team, era = arguments[:2]
                _validate_board(boards, team, era)
                team_rerolls, era_rerolls = (
                    (int(arguments[2]), int(arguments[3]))
                    if len(arguments) == 4
                    else (1, 1)
                )
                session.start(
                    team,
                    era,
                    team_rerolls=team_rerolls,
                    era_rerolls=era_rerolls,
                )
                changed = True
            elif verb == "offer":
                for card_id in arguments:
                    find_one(cards, {"id": card_id})
                session.set_candidates(arguments)
                changed = True
            elif verb == "next":
                if len(arguments) != 2:
                    raise SessionError("Usage: next TEAM ERA")
                _validate_board(boards, arguments[0], arguments[1])
                session.advance_spin(arguments[0], arguments[1])
                changed = True
            elif verb == "take":
                if len(arguments) != 1:
                    raise SessionError("Usage: take CARD_ID")
                session.take(arguments[0])
                changed = True
            elif verb == "team":
                if len(arguments) != 1:
                    raise SessionError("Usage: team TEAM")
                if not session.current_era:
                    raise SessionError("No active run. Start one first.")
                _validate_board(boards, arguments[0], session.current_era)
                session.reroll_team(arguments[0])
                changed = True
            elif verb == "era":
                if len(arguments) != 1:
                    raise SessionError("Usage: era ERA")
                if not session.current_team:
                    raise SessionError("No active run. Start one first.")
                _validate_board(boards, session.current_team, arguments[0])
                session.reroll_era(arguments[0])
                changed = True
            elif verb == "end":
                session.end()
                changed = True
            elif verb == "status":
                if not session.active:
                    print(
                        "No active run. Completed/abandoned runs: "
                        f"{session.run_number}."
                    )
                else:
                    print(
                        json.dumps(
                            solve(session.solver_state(), cards, metrics),
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
            else:
                raise SessionError(f"Unknown command: {verb}. Type help.")

            if changed:
                save_session(session_path, session)
                if verb == "end":
                    print("Run ended and state cleared. Use start for a new run.")
                elif session.active:
                    print(
                        json.dumps(
                            solve(session.solver_state(), cards, metrics),
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
        except (SessionError, ValueError) as error:
            print(f"Error: {error}")


def main() -> None:
    arguments = build_parser().parse_args()
    if not arguments.state and not arguments.session:
        raise SystemExit("Provide --state for one decision or --session for a run.")
    if arguments.state and arguments.session:
        raise SystemExit("Use either --state or --session, not both.")
    cards = load_cards(arguments.cards)
    metrics = load_metrics(arguments.team_era_metrics)
    if arguments.session:
        run_session(arguments.session, cards, metrics)
        return
    assert arguments.state is not None
    with Path(arguments.state).open(encoding="utf-8") as handle:
        state = json.load(handle)
    print(json.dumps(solve(state, cards, metrics), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
