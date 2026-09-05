# 82-0 Speedrun Solver

A data-backed decision prototype for the basketball game 82-0. The objective is
to reach 82-0 quickly or abandon an inefficient run, not to maximize score
beyond the winning threshold.

The solver currently emits one of:

- `TAKE`
- `TEAM REROLL`
- `ERA REROLL`
- `END RUN / START OVER`

It re-evaluates every legal position assignment whenever a candidate is added.
The browser application keeps the active roster, rerolls, spin, assignments,
and history in a persistent local session file.

## Current status

The data foundation is complete. The project imports the public structured
dataset exposed by [82-0 Guide](https://82-0-guide.com/) instead of scraping
HTML pages. The snapshot generated on 2026-08-16 contains:

- 10,626 unique team/era/player cards
- 30 teams, 7 eras, and 180 populated team-era boards
- 10,621 cards with known legal positions
- 759 rows with unavailable historical steals and blocks
- 5 preserved but non-playable rows whose source position is unknown

The action policy is still a simulation, but player and positional values come
from the full database. Names are labels only: no production decision is keyed
to a specific player. Future replacement values are derived from the best
eligible PG/SG/SF/PF/C cards on qualifying team-era boards.

## Setup

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

## Open the browser application

```bash
.venv/bin/python scripts/run_app.py
```

The application opens at `http://127.0.0.1:8765` and saves the active run to
`data/active_run.json` after every action. Stopping and reopening the server
resumes that run.

The browser workflow is:

1. Type or select the opening team and era.
2. Read the prominent TAKE, TEAM REROLL, ERA REROLL, or END RUN recommendation.
3. Follow the color-coded 82-0 probability, change from the previous action,
   stage-adjusted health, and recent chance graph.
4. Review every card's composite and position fit, plus current-board and
   expected-reroll quality.
5. Commit the recommended pick. The roster is saved and every flexible player
   is reassigned to the best legal position.
6. Enter the next normal spin, or use one of the remaining reroll controls.

TEAM and ERA controls show their remaining count, exclude the component already
on screen, and become disabled after use. The roster and history panels make
the persistent state visible throughout the run. The stopwatch is OFF by
default and never runs unless the user starts it. It can be paused/resumed,
reset to zero, or turned off and cleared completely. When enabled it survives
browser refreshes and continues across `END RUN / START OVER`; an 82-0 result
pauses it automatically. Clock state never affects solver decisions.

To run without opening a browser automatically:

```bash
.venv/bin/python scripts/run_app.py --no-browser
```

That process closes after 6 hours, or 15 minutes after the run is no longer
active. Starting a new 82-0 game in the same process keeps it alive. It does
not auto-restart; run the command again only for a new game.

```bash
.venv/bin/python scripts/run_app.py --no-browser --max-lifetime-hours 6
```

The HTTP server stays on loopback, rejects hostile `Host` headers, requires
JSON for API writes, and sends CSP, anti-framing, no-sniff, and no-referrer
headers.

## Import the card database

Use the cached source if one is present:

```bash
.venv/bin/python scripts/import_cards.py
```

Revalidate the cache and fetch a newer public snapshot:

```bash
.venv/bin/python scripts/import_cards.py --refresh
```

The importer:

- checks `robots.txt` before a network refresh
- identifies itself with a descriptive user agent
- uses timeouts, retry backoff, and a request interval
- caches the static JSON and revalidates it with HTTP cache headers
- validates schema, uniqueness, positions, numeric values, and scoring
- writes files atomically

For a reproducible offline import:

```bash
.venv/bin/python scripts/import_cards.py \
  --input-json tests/fixtures/rankings_sample.json \
  --output-dir /tmp/82-0-data
```

Generated artifacts:

- `data/cards.csv` — normalized complete card universe
- `data/team_era_metrics.json` — derived board and position distributions
- `data/import_report.json` — source checksum, counts, and anomalies

The source response cache lives under `.cache/` and is not part of the solver
data contract.

## Card schema

The stable identity is the source `id`; `(team, era, player)` is also validated
as unique. Each normalized row includes:

- player, team, era, and slash-separated legal positions
- PTS, REB, AST, STL, and BLK
- explicit historical-unavailable flags for STL and BLK
- `raw_composite`, computed with the solver formula
- the guide's `source_contribution`, `source_value`, and flexibility score
- overall rank, spin rank, perfect-lineup share, and playable status

`source_value` is not the basketball composite: it includes a flexibility
bonus. The solver uses `raw_composite`, which matches source `contribution`
within import tolerance.

## Scoring

```text
Composite =
  0.3448*PTS + 0.6297*REB + 0.6143*AST + 1.1475*STL + 1.25*BLK
```

The working 82-0 threshold is `109.5`. For a completed lineup, unavailable
historical steals or blocks are filled using the average of known lineup
values, matching the reverse-engineered model.

## Team-era metrics

Metrics are calculated from normalized cards, not hand-maintained tiers. Each
board includes:

- card counts, position coverage, and top cards
- composite mean, median, p75, p90, and maximum
- probabilities of a card reaching 18, 20, and 22 composite
- the same distributions and top cards for every eligible position
- the best distinct-card legal five-position assignment by raw composite
- a documented board-quality score for descriptive board reporting

## Stage-aware speedrun policy

The displayed continuation probability is not compared to a fixed percentage
cutoff. A low absolute percentage is normal early in an 82-0 run. Instead, the
engine compares:

```text
current continuation probability / remaining picks
```

against:

```text
fresh-run probability / (five picks + restart overhead)
```

This approximates success per future unit of time. Early picks use a wider
tolerance for simulation uncertainty and future rescue cards; the threshold
tightens as open positions disappear. For example, opening Karl Malone or
Dwyane Wade can be worth taking even when the absolute continuation estimate
is only a few percent, because that path remains competitive with paying the
restart cost. Later in the run, the same percentage can correctly trigger an
abort because fewer remaining cards can rescue the roster.

Reroll decisions do not use board average, p90, or depth. For every possible
TEAM/ERA reroll destination, the engine selects that board's single best legal
card after enumerating all full-roster position assignments. It then averages
those best-card outcomes because the reroll destination itself is random, and
shows how often a reroll outcome improves on the current best legal pick. The
policy remains a heuristic until exact game draw weighting and measured action
timings are available, but decisions are explicitly conditioned on run stage,
position flexibility, remaining positions, and restart pace.

When a reroll is available, the browser also simulates complete futures for
the best TAKE with the reroll preserved and for each reroll action with that
reroll consumed. This prevents a generic "healthy path, save the reroll" rule
from overriding a reroll that materially improves completion probability.

Action selection is probability-first. It chooses the action with the highest
estimated 82-0 completion probability; when Monte Carlo confidence intervals
overlap, it treats those actions as statistically tied and uses expected
remaining time as the tie-breaker. Player names, teams, eras, and hand-written
game scenarios never participate in policy scoring. Curated player-name badges
are presentation-only.

The positional continuation model has no hardcoded player names or fixed
position means. For each position, it takes the best eligible card from every
team-era board, uses the upper quartile as the empirical distribution of boards
that a speedrun policy would actually continue, and simulates future
replacement value from those samples. This allows a lower-composite scarce
position to beat a higher-composite replaceable position when it reduces
expected time to 82-0.

The displayed 82-0 probability is recorded after every opening spin, normal
spin, TEAM/ERA reroll, committed pick, and restart. Green means the current
path meets or beats its stage-adjusted continuation threshold, yellow means it
is fragile, and red means its success-per-time value has fallen materially
below restarting. This avoids treating every naturally low opening percentage
as a bad run.

The displayed percentage comes from a conservative actual-board Monte Carlo,
not independent elite outcomes per position. It samples future valid
team-era boards from the imported game universe, enforces legal assignments,
scores full rosters exactly, and explicitly samples remaining final-turn
rerolls. Until the game's exact spin weighting is known, it is a calibrated
estimate rather than a literal guarantee.

The main percentage always describes the currently committed roster. While a
board is open, a separate `Projected` value shows the estimate if the
recommended TAKE or final-turn reroll is committed. This prevents a projected
pick from appearing in the current percentage before the user actually takes
it. END RUN decisions use that same projected Monte Carlo value relative to
the simulated fresh-run baseline, so the recommendation and displayed model
cannot silently use different probability systems.

When the fifth committed card produces a final composite of at least 109.5,
the chase clock stops and the browser displays an 82-0 celebration with the
final score and total elapsed chase time.

The roster panel shows committed adjusted score and the approximate amount
still needed to reach 109.5. Because historical cards can have unavailable
STL/BLK, that partial remainder is explicitly labelled approximate. On the
fifth-card board, every legal candidate instead shows its exact projected
final score and the precise winning or losing margin.

With four players already committed, rerolls no longer use average board
quality as a proxy. The engine enumerates every legal alternate TEAM or ERA
board, finds its best legal fifth card after full position reassignment, and
counts exactly how many outcomes cross 109.5. A one-spin reroll with any
meaningful immediate-win probability is compared against the much larger
expected cost of restarting the entire chase. The UI displays that exact
percentage and the specific winning team-era/player outcomes.

## Run the solver

### Persistent speedrun session

This is the normal speedrun mode. It stores the active run after every
transition, so closing the terminal or restarting the command does not lose
the roster, current team/era, rerolls, or decision history.

```bash
.venv/bin/python 82_0_speedrun_solver.py --session data/active_run.json
```

Commands:

```text
start DAL 1980s 1 1
next MIA 2000s
offer CARD_ID [CARD_ID ...]
take CARD_ID
team LAC
era 1970s
status
end
quit
```

`start` creates a new run. `team` and `era` consume their corresponding
reroll, replace the current spin, and clear the old offer. `take` commits an
offered card to the roster and clears the offer. `end` clears the active run,
but retains its history, and waits for the next `start`.

Use exact card IDs for offers. For example:

```text
offer oscar_robertson_sac_1960s jerry_lucas_sac_1960s
take oscar_robertson_sac_1960s
```

### One-off decision

```bash
.venv/bin/python 82_0_speedrun_solver.py --state examples/state.json
```

Card specs should use exact source IDs when possible:

```json
{"id": "oscar_robertson_sac_1960s"}
```

Exact player/team/era lookup remains available for hand-authored states.

## Test

```bash
.venv/bin/python -m pytest
```

The test suite is offline and covers import validation, historical defense,
unknown positions, derived metrics, flexible-player reassignment, and a CLI
smoke run.

## Next milestone

The next phase is a calibrated action evaluator that compares TAKE, TEAM
REROLL, ERA REROLL, and RESTART through simulation or dynamic programming. It
also needs measured game timings and exact candidate-generation rules before
it can optimize expected minutes per successful 82-0 run.

## Attribution

Player data is imported from the public dataset at
`https://82-0-guide.com/data/rankings.json`, which identifies
`https://www.82-0.com/players_flat.json` as its inspected source. 82-0 Guide is
an unofficial fan analysis site and is not affiliated with 82-0.com or the NBA.
