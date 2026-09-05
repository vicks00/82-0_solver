const ui = {
  saveStatus: document.querySelector("#save-status"),
  runStrip: document.querySelector("#run-strip"),
  runStatus: document.querySelector("#run-status"),
  currentSpin: document.querySelector("#current-spin"),
  rosterCount: document.querySelector("#roster-count"),
  runTimer: document.querySelector("#run-timer"),
  clockToggle: document.querySelector("#clock-toggle"),
  resetClock: document.querySelector("#reset-clock"),
  disableClock: document.querySelector("#disable-clock"),
  teamRerollCount: document.querySelector("#team-reroll-count"),
  eraRerollCount: document.querySelector("#era-reroll-count"),
  chancePanel: document.querySelector("#chance-panel"),
  chanceNumber: document.querySelector("#chance-number"),
  chanceHealth: document.querySelector("#chance-health"),
  chanceDirection: document.querySelector("#chance-direction"),
  chanceExplanation: document.querySelector("#chance-explanation"),
  healthFill: document.querySelector("#health-fill"),
  healthThreshold: document.querySelector("#health-threshold"),
  chanceChart: document.querySelector("#chance-chart"),
  projectedChance: document.querySelector("#projected-chance"),
  projectedLabel: document.querySelector("#projected-label"),
  projectedNumber: document.querySelector("#projected-number"),
  projectedDelta: document.querySelector("#projected-delta"),
  endRun: document.querySelector("#end-run"),
  recommendation: document.querySelector("#recommendation"),
  decision: document.querySelector("#decision"),
  decisionDetail: document.querySelector("#decision-detail"),
  recommendationAction: document.querySelector("#recommendation-action"),
  actionComparison: document.querySelector("#action-comparison"),
  actionConfidence: document.querySelector("#action-confidence"),
  actionValues: document.querySelector("#action-values"),
  spinForm: document.querySelector("#spin-form"),
  spinFormTitle: document.querySelector("#spin-form-title"),
  stepChip: document.querySelector("#step-chip"),
  teamInput: document.querySelector("#team-input"),
  eraInput: document.querySelector("#era-input"),
  spinSubmit: document.querySelector("#spin-submit"),
  teamOptions: document.querySelector("#team-options"),
  eraOptions: document.querySelector("#era-options"),
  rerollControls: document.querySelector("#reroll-controls"),
  teamRerollControl: document.querySelector("#team-reroll-control"),
  eraRerollControl: document.querySelector("#era-reroll-control"),
  teamRerollInput: document.querySelector("#team-reroll-input"),
  eraRerollInput: document.querySelector("#era-reroll-input"),
  teamRerollOptions: document.querySelector("#team-reroll-options"),
  eraRerollOptions: document.querySelector("#era-reroll-options"),
  teamReroll: document.querySelector("#team-reroll"),
  eraReroll: document.querySelector("#era-reroll"),
  boardPanel: document.querySelector("#board-panel"),
  boardTitle: document.querySelector("#board-title"),
  boardQuality: document.querySelector("#board-quality"),
  metricBest: document.querySelector("#metric-best"),
  metricAverage: document.querySelector("#metric-average"),
  metricP90: document.querySelector("#metric-p90"),
  metricP18: document.querySelector("#metric-p18"),
  qualityCurrent: document.querySelector("#quality-current"),
  qualityTeam: document.querySelector("#quality-team"),
  qualityTeamEdge: document.querySelector("#quality-team-edge"),
  qualityEra: document.querySelector("#quality-era"),
  qualityEraEdge: document.querySelector("#quality-era-edge"),
  rerollOutcomes: document.querySelector("#reroll-outcomes"),
  replacementValues: document.querySelector("#replacement-values"),
  scoreLabel: document.querySelector("#score-label"),
  committedScore: document.querySelector("#committed-score"),
  remainingLabel: document.querySelector("#remaining-label"),
  remainingScore: document.querySelector("#remaining-score"),
  scoreNote: document.querySelector("#score-note"),
  playersPanel: document.querySelector("#players-panel"),
  playerSearch: document.querySelector("#player-search"),
  positionFilter: document.querySelector("#position-filter"),
  resultCount: document.querySelector("#result-count"),
  playerRows: document.querySelector("#player-rows"),
  roster: document.querySelector("#roster"),
  history: document.querySelector("#history"),
  toast: document.querySelector("#toast"),
  celebration: document.querySelector("#celebration"),
  confetti: document.querySelector("#confetti"),
  celebrationDetail: document.querySelector("#celebration-detail"),
  closeCelebration: document.querySelector("#close-celebration"),
};

const app = {
  catalog: null,
  state: null,
  candidates: [],
  busy: false,
  lastActive: undefined,
  lastSpinOpen: undefined,
  timerSession: null,
  refreshing: false,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function number(value, digits = 2) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(digits);
}

function percent(value) {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function normalizeEra(value) {
  const raw = value.trim().toLowerCase();
  if (/^\d{4}s$/.test(raw)) return raw;
  if (/^\d{4}$/.test(raw)) return `${raw}s`;
  const match = raw.match(/^(\d{2})s?$/);
  if (!match) return value.trim();
  const short = Number(match[1]);
  return `${short <= 30 ? 2000 + short : 1900 + short}s`;
}

function showToast(message, error = false) {
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", error);
  ui.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => ui.toast.classList.remove("visible"), 3200);
}

function setBusy(busy) {
  app.busy = busy;
  ui.saveStatus.textContent = busy ? "Saving…" : "State saved locally";
  document.querySelectorAll("button").forEach((button) => {
    if (busy) {
      button.dataset.previousDisabled = button.disabled ? "true" : "false";
      button.disabled = true;
    } else if (button.dataset.previousDisabled !== undefined) {
      button.disabled = button.dataset.previousDisabled === "true";
      delete button.dataset.previousDisabled;
    }
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("Solver returned invalid JSON.");
  }
  if (!response.ok) throw new Error(payload.error || "Request failed");
  return payload;
}

async function mutate(path, payload = {}) {
  if (app.busy) return;
  setBusy(true);
  try {
    app.state = await api(path, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
    render();
  }
}

function fillOptions(target, values) {
  target.innerHTML = values
    .map((value) => `<option value="${escapeHtml(value)}"></option>`)
    .join("");
}

function render() {
  const { session, roster, report, history } = app.state;
  ui.runStrip.classList.toggle("active", session.active);
  ui.endRun.hidden = !session.active;
  ui.runStatus.textContent = session.active
    ? `Run ${session.run_number} active`
    : session.result === "82-0"
      ? "82-0 secured"
      : session.result === "missed"
        ? "Run completed — missed"
        : "No active run";
  ui.currentSpin.textContent =
    session.active && session.current_team
      ? `${session.current_team} · ${session.current_era}`
      : "—";
  ui.rosterCount.textContent = `${roster.length} / 5`;
  app.timerSession = session;
  updateTimer();
  renderRerollPill(ui.teamRerollCount, "TEAM", session.team_rerolls, session.active);
  renderRerollPill(ui.eraRerollCount, "ERA", session.era_rerolls, session.active);
  renderChance(
    report.chance,
    app.state.chance_history,
    report.projected_chance,
  );
  renderSpinControls(session, report);
  renderRecommendation(report, session);
  renderActionComparison(report);
  renderBoard(report);
  renderScoreProgress(app.state.score_progress);
  renderRoster(roster);
  renderHistory(history);
  app.candidates = report.candidate_options || [];
  renderPlayers();
  ui.saveStatus.textContent = "State saved locally";
  app.lastActive = session.active;
  app.lastSpinOpen = session.spin_open;
  if (session.result === "82-0") launchCelebration(session);
}

function renderRerollPill(element, label, count, active) {
  element.textContent = `${label} · ${active ? `${count} left` : "—"}`;
  element.classList.toggle("available", active && count > 0);
}

function renderSpinControls(session, report) {
  const waitingForSpin = session.active && !session.spin_open;
  ui.spinForm.hidden = session.active && session.spin_open;
  ui.rerollControls.hidden = !session.active || !session.spin_open;

  if (!session.active) {
    ui.teamInput.disabled = false;
    ui.eraInput.disabled = false;
    ui.spinSubmit.disabled = false;
    if (app.lastActive !== false) {
      ui.teamInput.value = "";
      ui.eraInput.value = "";
      ui.teamRerollInput.value = "";
      ui.eraRerollInput.value = "";
      requestAnimationFrame(() => ui.teamInput.focus());
    }
    ui.spinFormTitle.textContent = "Start a new run";
    ui.stepChip.textContent = "Opening spin";
    ui.spinSubmit.textContent = "Evaluate opening spin";
  } else if (waitingForSpin) {
    ui.teamInput.disabled = false;
    ui.eraInput.disabled = false;
    ui.spinSubmit.disabled = false;
    ui.spinFormTitle.textContent = "Enter the next spin";
    ui.stepChip.textContent = `Pick ${app.state.roster.length + 1} of 5`;
    ui.spinSubmit.textContent = "Evaluate next spin";
    if (app.lastActive !== true || app.lastSpinOpen !== false) {
      ui.teamInput.value = "";
      ui.eraInput.value = "";
    }
  }

  if (!session.active || !session.spin_open) return;
  const otherTeams = app.catalog.teams.filter(
    (team) =>
      team !== session.current_team &&
      app.catalog.valid_boards.some(
        (board) => board.team === team && board.era === session.current_era,
      ),
  );
  const otherEras = app.catalog.eras.filter(
    (era) =>
      era !== session.current_era &&
      app.catalog.valid_boards.some(
        (board) => board.team === session.current_team && board.era === era,
      ),
  );
  fillOptions(ui.teamRerollOptions, otherTeams);
  fillOptions(ui.eraRerollOptions, otherEras);
  ui.teamReroll.disabled = session.team_rerolls <= 0;
  ui.teamRerollInput.disabled = session.team_rerolls <= 0;
  ui.eraReroll.disabled = session.era_rerolls <= 0;
  ui.eraRerollInput.disabled = session.era_rerolls <= 0;
  ui.teamReroll.textContent =
    session.team_rerolls > 0 ? `Use TEAM (${session.team_rerolls})` : "TEAM used";
  ui.eraReroll.textContent =
    session.era_rerolls > 0 ? `Use ERA (${session.era_rerolls})` : "ERA used";
  ui.teamRerollControl.classList.toggle(
    "recommended",
    report.action === "TEAM_REROLL",
  );
  ui.eraRerollControl.classList.toggle(
    "recommended",
    report.action === "ERA_REROLL",
  );
}

function renderRecommendation(report, session) {
  ui.recommendation.className = "recommendation";
  ui.recommendationAction.innerHTML = "";

  if (session.result === "82-0") {
    ui.recommendation.classList.add("take");
    ui.decision.textContent = "82-0 SECURED";
    ui.decisionDetail.textContent =
      `Final composite ${number(session.final_score, 3)}. ` +
      "The timer is stopped and the completed roster remains visible.";
  } else if (session.result === "missed") {
    ui.recommendation.classList.add("end-run");
    ui.decision.textContent = "RUN COMPLETE — MISSED";
    ui.decisionDetail.textContent =
      `Final composite ${number(session.final_score, 3)} did not reach 109.5.`;
  } else if (report.action === "TAKE" && report.recommended_card) {
    const card = report.recommended_card;
    ui.recommendation.classList.add("take");
    ui.decision.textContent = `TAKE — ${card.player} → ${card.take_position}`;
    ui.decisionDetail.textContent =
      card.final_score !== null
        ? `Exact projected final score ${number(card.final_score, 3)} · ` +
          `${card.final_score >= 109.5 ? "wins by" : "misses by"} ` +
          `${number(Math.abs(card.final_score - 109.5), 3)}.`
        : `Composite ${number(card.raw_composite)} · ` +
          `projected chance ${percent(report.projected_chance?.probability)}. ` +
          `Paired speedrun value ${number(card.relative_to_restart, 2)}× restarting · ` +
          `remaining cards need ${number(card.required_average_remaining, 2)} average.`;
    ui.recommendationAction.innerHTML = `
      <button class="button button-take" data-take="${escapeHtml(card.id)}">
        TAKE RECOMMENDED
      </button>`;
  } else if (report.action === "TEAM_REROLL") {
    ui.decision.textContent = "TEAM REROLL";
    renderRerollRecommendation(
      report,
      `${report.decision} Keep the current era and enter the newly rolled team below.`,
    );
  } else if (report.action === "ERA_REROLL") {
    ui.decision.textContent = "ERA REROLL";
    renderRerollRecommendation(
      report,
      `${report.decision} Keep the current team and enter the newly rolled era below.`,
    );
  } else if (report.action === "END_RUN") {
    ui.recommendation.classList.add("end-run");
    ui.decision.textContent = "END RUN / START OVER";
    ui.decisionDetail.textContent = report.decision;
    ui.recommendationAction.innerHTML =
      '<button class="button button-danger" data-end>END RUN NOW</button>';
  } else if (report.action === "NEXT_SPIN") {
    ui.decision.textContent = "ENTER NEXT TEAM + ERA";
    ui.decisionDetail.textContent =
      "The last pick is saved. Enter the next spin to continue with the same roster and remaining rerolls.";
  } else {
    ui.decision.textContent = report.decision || "START A NEW RUN";
    ui.decisionDetail.textContent =
      "Enter the team and era shown by the game to get the recommendation.";
  }
}

function renderActionComparison(report) {
  const selection = report.action_selection;
  const actions = selection?.compared_actions || [];
  ui.actionComparison.hidden = !actions.length;
  if (!actions.length) return;

  const confidence = Number(selection.confidence || 0);
  const guardNote = selection.restart_guard_applied
    ? " · restart blocked because abandonment confidence was below 97.5%"
    : selection.reroll_guard_applied
      ? ` · final reroll preserved: gain did not clear ${percent(selection.reroll_hurdle)} plus 90% confidence`
      : "";
  ui.actionConfidence.textContent =
    `${selection.confidence_label || "low"} confidence · ` +
    `${percent(confidence)} · ${selection.trials.toLocaleString()} paired futures` +
    guardNote;
  ui.actionValues.innerHTML = actions
    .map(
      (action) => `
        <article class="action-value ${action.selected ? "selected" : ""}">
          <span>${escapeHtml(action.label)}</span>
          <strong>${number(action.relative_to_restart, 2)}× restart</strong>
          <small>
            ${percent(action.probability)} completion ·
            ${number(Number(action.speedrun_value) * 100, 3)} wins / 100 turns
          </small>
        </article>`,
    )
    .join("");
}

function renderRerollRecommendation(report, fallback) {
  const outlook = report.recommended_reroll?.final_turn_outlook;
  if (!outlook) {
    ui.decisionDetail.textContent = fallback;
    return;
  }
  ui.decisionDetail.textContent =
    `${outlook.winning_outcome_count} of ${outlook.outcome_count} possible ` +
    `reroll boards win immediately (${percent(outlook.win_probability)}).`;
  const winners = outlook.winning_outcomes
    .slice(0, 6)
    .map(
      (outcome) =>
        `<span><b>${escapeHtml(outcome.team)} ${escapeHtml(outcome.era)}</b> · ` +
        `${escapeHtml(outcome.player)} → ${number(outcome.final_score, 2)}</span>`,
    )
    .join("");
  ui.recommendationAction.innerHTML = `
    <div class="winning-paths">
      <small>Immediate winning outcomes</small>
      ${winners}
    </div>`;
}

function renderBoard(report) {
  const visible = Boolean(report.board);
  ui.boardPanel.hidden = !visible;
  ui.playersPanel.hidden = !visible;
  if (!visible) return;

  const { board, reroll_expectations: expectations } = report;
  const bestLegal = board.best_legal;
  ui.boardTitle.textContent = `${board.team} · ${board.era}`;
  ui.boardQuality.textContent = number(board.stage_quality, 3);
  ui.metricBest.textContent = number(bestLegal?.raw_composite, 3);
  ui.metricAverage.textContent = bestLegal?.player || "No legal fit";
  ui.metricP90.textContent = bestLegal?.take_position || "—";
  ui.metricP18.textContent = bestLegal?.open_after?.join(" · ") || "None";
  ui.qualityCurrent.textContent = number(expectations.current_quality, 3);
  ui.qualityTeam.textContent = number(expectations.team_reroll_average, 3);
  ui.qualityEra.textContent = number(expectations.era_reroll_average, 3);
  renderEdge(
    ui.qualityTeamEdge,
    expectations.team_edge,
    expectations.team_better_probability,
  );
  renderEdge(
    ui.qualityEraEdge,
    expectations.era_edge,
    expectations.era_better_probability,
  );
  renderRerollOutcomes(expectations);
  const openPositions = new Set(report.open_positions || []);
  ui.replacementValues.innerHTML = ["PG", "SG", "SF", "PF", "C"]
    .map((position) => {
      const replacement = report.position_replacement_model[position];
      return `
        <div
          class="replacement-value ${openPositions.has(position) ? "open" : ""}"
          title="Accepted-board cutoff ${number(replacement.cutoff, 2)}; ${replacement.accepted_boards} qualifying boards"
        >
          <span>${position}</span>
          <strong>${number(replacement.mean, 2)}</strong>
        </div>`;
    })
    .join("");
}

function renderEdge(element, edge, betterProbability = null) {
  if (edge === null || edge === undefined) {
    element.textContent = "unavailable";
    element.className = "";
    return;
  }
  element.textContent =
    `${edge >= 0 ? "+" : ""}${number(edge, 3)} vs current` +
    (betterProbability === null
      ? ""
      : ` · ${percent(betterProbability)} outcomes better`);
  element.className = edge >= 0 ? "positive" : "negative";
}

function renderRerollOutcomes(expectations) {
  const groups = [
    [
      "TEAM",
      expectations.team_outcomes || [],
      expectations.team_distribution,
    ],
    [
      "ERA",
      expectations.era_outcomes || [],
      expectations.era_distribution,
    ],
  ].filter(([, outcomes]) => outcomes.length);
  ui.rerollOutcomes.innerHTML = groups
    .map(
      ([label, outcomes, distribution]) => `
        <div>
          <span class="label">${label} reroll · best legal card by outcome</span>
          ${
            distribution
              ? `<p class="reroll-distribution-summary">
                  Better ${percent(distribution.probability_better)} ·
                  better by 1+ ${percent(distribution.probability_better_by_1)} ·
                  better by 2+ ${percent(distribution.probability_better_by_2)} ·
                  worse ${percent(distribution.probability_worse)}
                </p>`
              : ""
          }
          <div class="outcome-list">
            ${outcomes
              .slice(0, label === "ERA" ? outcomes.length : 8)
              .map(
                (outcome) => `
                  <span>
                    <b>${escapeHtml(outcome.team)} ${escapeHtml(outcome.era)}</b>
                    ${escapeHtml(outcome.player)}
                    <i>
                      ${number(outcome.raw_composite, 2)}
                      ${outcome.composite_delta === undefined
                        ? ""
                        : `· ${Number(outcome.composite_delta) >= 0 ? "+" : ""}${number(outcome.composite_delta, 2)} vs current`}
                      · ${percent(outcome.probability)}
                    </i>
                  </span>`,
              )
              .join("")}
          </div>
        </div>`,
    )
    .join("");
}

function renderChance(chance, history, projected) {
  const health = chance.health || "healthy";
  ui.chancePanel.className = `chance-panel ${health}`;
  ui.chanceNumber.textContent = percent(chance.probability);
  ui.chanceHealth.textContent = health;

  const deltaPoints = Number(chance.delta || 0) * 100;
  if (chance.direction === "up") {
    ui.chanceDirection.className = "up";
    ui.chanceDirection.textContent =
      `▲ +${deltaPoints.toFixed(1)} percentage points`;
  } else if (chance.direction === "down") {
    ui.chanceDirection.className = "down";
    ui.chanceDirection.textContent =
      `▼ ${deltaPoints.toFixed(1)} percentage points`;
  } else {
    ui.chanceDirection.className = "";
    ui.chanceDirection.textContent = "No material change";
  }

  const explanations = {
    secured: "The completed roster crossed 109.5. The chase is complete.",
    strong:
      `This board, its legal picks, and remaining rerolls are included. ${number(chance.relative_to_restart, 2)}× restart speedrun value.`,
    healthy:
      `This board, its legal picks, and remaining rerolls are included. ${number(chance.relative_to_restart, 2)}× restart speedrun value.`,
    fragile:
      `This board, its legal picks, and remaining rerolls are included. ${number(chance.relative_to_restart, 2)}× restart speedrun value.`,
    critical:
      `This board cannot complete the current run under the recommended policy. Restart odds are shown only in the action comparison.`,
  };
  const simulationNote = chance.simulation
    ? ` Simulated from ${chance.simulation.trials.toLocaleString()} actual-board futures.`
    : "";
  ui.chanceExplanation.textContent = explanations[health] + simulationNote;

  const scaleMax = 1.5;
  ui.healthFill.style.width =
    `${Math.min(100, (chance.relative_to_restart / scaleMax) * 100)}%`;
  ui.healthThreshold.style.left =
    `${Math.min(100, (chance.continue_threshold / scaleMax) * 100)}%`;
  if (projected) {
    const deltaPoints = Number(projected.delta || 0) * 100;
    ui.projectedChance.hidden = false;
    ui.projectedLabel.textContent = `Projected · ${projected.label}`;
    ui.projectedNumber.textContent = percent(projected.probability);
    ui.projectedDelta.textContent =
      `${deltaPoints >= 0 ? "+" : ""}${deltaPoints.toFixed(1)} points`;
    ui.projectedDelta.className =
      deltaPoints > 0.05 ? "up" : deltaPoints < -0.05 ? "down" : "";
  } else {
    ui.projectedChance.hidden = true;
  }
  renderChanceChart(history);
}

function renderChanceChart(history) {
  const points = (history || []).slice(-14);
  if (!points.length) {
    ui.chanceChart.innerHTML = "";
    return;
  }
  const values = points.map((point) => Number(point.probability));
  const maxValue = Math.max(0.01, ...values) * 1.12;
  const width = 220;
  const height = 64;
  const pad = 5;
  const coordinates = values.map((value, index) => {
    const x =
      values.length === 1
        ? width / 2
        : pad + (index / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - (value / maxValue) * (height - pad * 2);
    return [x, y];
  });
  const line = coordinates.map(([x, y]) => `${x},${y}`).join(" ");
  const area =
    `${pad},${height - pad} ` +
    `${line} ${coordinates.at(-1)[0]},${height - pad}`;
  const dots = coordinates
    .map(
      ([x, y], index) =>
        `<circle class="trend-dot" cx="${x}" cy="${y}" r="${index === coordinates.length - 1 ? 3.5 : 2}"></circle>`,
    )
    .join("");
  ui.chanceChart.innerHTML = `
    <line class="grid-line" x1="0" y1="${height - pad}" x2="${width}" y2="${height - pad}"></line>
    <polygon class="trend-area" points="${area}"></polygon>
    <polyline class="trend-line" points="${line}"></polyline>
    ${dots}`;
}

function renderRoster(roster) {
  const positions = ["PG", "SG", "SF", "PF", "C"];
  const byPosition = Object.fromEntries(
    roster.map((card) => [card.assigned_position, card]),
  );
  ui.roster.innerHTML = positions
    .map((position) => {
      const card = byPosition[position];
      if (!card) {
        return `
          <div class="roster-slot empty">
            <span class="slot-position">${position}</span>
            <div><strong>Open slot</strong><small>Waiting for a legal pick</small></div>
          </div>`;
      }
      return `
        <div class="roster-slot">
          <span class="slot-position">${position}</span>
          <div>
            <strong>${escapeHtml(card.player)}</strong>
            <div class="roster-badges">${badgesMarkup(card.badges)}</div>
            <small>${escapeHtml(card.team)} · ${escapeHtml(card.era)} · ${escapeHtml(card.positions.join("/"))}</small>
          </div>
          <span class="slot-score">${number(card.raw_composite)}</span>
        </div>`;
    })
    .join("");
}

function renderScoreProgress(progress) {
  const complete = progress.complete;
  ui.scoreLabel.textContent = complete
    ? "Final adjusted score"
    : "Committed adjusted score";
  ui.committedScore.textContent =
    `${number(progress.adjusted_committed_score, 3)} / ${number(progress.threshold, 1)}`;
  ui.remainingLabel.textContent = complete
    ? progress.wins
      ? "Winning margin"
      : "Missed by"
    : "Approx. still needed";
  const amount = complete
    ? Math.abs(progress.adjusted_committed_score - progress.threshold)
    : progress.approximate_remaining;
  ui.remainingScore.textContent = number(amount, 3);
  ui.remainingScore.className =
    complete && progress.wins ? "score-win" : complete ? "score-loss" : "";
  ui.scoreNote.textContent = complete
    ? "This is the exact final score."
    : "Approximate until the fifth card sets historical STL/BLK imputation.";
}

function badgesMarkup(badges = []) {
  if (!badges.length) return "";
  return `<span class="badges">${badges
    .map(
      (badge) =>
        `<span class="badge badge-${escapeHtml(badge.kind)}"${
          badge.kind === "flex" ? "" : ` title="${escapeHtml(badge.label)}"`
        }>${
          badge.icon ? escapeHtml(badge.icon) : ""
        }${
          badge.kind === "flex" ? "" : `<i>${escapeHtml(badge.label)}</i>`
        }</span>`,
    )
    .join("")}</span>`;
}

function renderPlayers() {
  const query = ui.playerSearch.value.trim().toLowerCase();
  const position = ui.positionFilter.value;
  const recommendedId = app.state?.report?.recommended_card?.id;
  const filtered = app.candidates.filter((card) => {
    const text = `${card.player} ${card.positions.join(" ")}`.toLowerCase();
    return (!query || text.includes(query)) &&
      (!position || card.positions.includes(position));
  });
  ui.resultCount.textContent = `${filtered.length} cards`;
  if (!filtered.length) {
    ui.playerRows.innerHTML =
      '<tr><td colspan="12" class="empty-state">No matching cards.</td></tr>';
    return;
  }
  ui.playerRows.innerHTML = filtered
    .map(
      (card, index) => `
        <tr class="${card.id === recommendedId ? "recommended-player" : ""}">
          <td class="rank">${index + 1}</td>
          <td class="player-name">${escapeHtml(card.player)}${badgesMarkup(card.badges)}</td>
          <td><span class="position-tags">${card.positions
            .map((item) => `<span class="position-tag">${item}</span>`)
            .join("")}</span></td>
          <td class="composite">${number(card.raw_composite, 3)}</td>
          <td class="${card.margin_to_82 === null ? "" : card.margin_to_82 >= 0 ? "final-win" : "final-loss"}">
            ${
              card.final_score === null
                ? "—"
                : `${number(card.final_score, 3)} (${card.margin_to_82 >= 0 ? "+" : ""}${number(card.margin_to_82, 3)})`
            }
          </td>
          <td>${number(card.pts, 1)}</td>
          <td>${number(card.reb, 1)}</td>
          <td>${number(card.ast, 1)}</td>
          <td>${card.stl === null ? "N/A" : number(card.stl, 1)}</td>
          <td>${card.blk === null ? "N/A" : number(card.blk, 1)}</td>
          <td class="${card.legal ? "fit" : "illegal"}">
            ${card.legal
              ? `→ ${card.take_position} · ${number(card.relative_to_restart, 2)}×`
              : "No fit"}
          </td>
          <td>
            <button
              class="button button-secondary table-take"
              data-take="${escapeHtml(card.id)}"
              ${card.legal ? "" : "disabled"}
            >TAKE</button>
          </td>
        </tr>`,
    )
    .join("");
}

function renderHistory(history) {
  if (!history.length) {
    ui.history.innerHTML = '<li class="empty-state">No actions recorded yet.</li>';
    return;
  }
  ui.history.innerHTML = [...history]
    .reverse()
    .map((event) => `<li>${historyLabel(event)}</li>`)
    .join("");
}

function historyLabel(event) {
  const labels = {
    start: `<strong>Started run</strong> · ${event.team} ${event.era}`,
    next_spin: `<strong>Next spin</strong> · ${event.team} ${event.era}`,
    offer: `<strong>Loaded board</strong> · ${event.card_ids?.length || 0} cards`,
    take: `<strong>Took card</strong> · ${escapeHtml(event.card_id)}`,
    team_reroll: `<strong>TEAM reroll</strong> · ${event.from} → ${event.to}`,
    era_reroll: `<strong>ERA reroll</strong> · ${event.from} → ${event.to}`,
    end: `<strong>Ended run</strong> · ${escapeHtml(event.reason)}`,
    complete: `<strong>${event.result === "82-0" ? "82-0 secured" : "Run missed"}</strong> · ${number(event.final_score, 3)}`,
    clock_started: "<strong>Clock started</strong>",
    clock_paused: "<strong>Clock paused</strong>",
    clock_reset: "<strong>Clock reset</strong>",
    clock_disabled: "<strong>Clock turned off</strong>",
  };
  return labels[event.event] || `<strong>${escapeHtml(event.event)}</strong>`;
}

function updateTimer() {
  const session = app.timerSession;
  if (!session?.clock_enabled) {
    ui.runTimer.textContent = "OFF";
    ui.clockToggle.textContent = "Start clock";
    ui.resetClock.hidden = true;
    ui.disableClock.hidden = true;
    return;
  }
  ui.resetClock.hidden = false;
  ui.disableClock.hidden = false;
  ui.clockToggle.textContent = session.clock_running ? "Pause" : "Resume";
  let elapsed = Number(session.clock_elapsed_seconds || 0) * 1000;
  if (session.clock_running && session.clock_segment_started_at) {
    elapsed += Math.max(
      0,
      Date.now() - new Date(session.clock_segment_started_at).getTime(),
    );
  }
  ui.runTimer.textContent = formatDuration(elapsed);
}

function formatDuration(elapsed) {
  const totalSeconds = elapsed / 1000;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return (
    `${hours ? `${String(hours).padStart(2, "0")}:` : ""}` +
    `${String(minutes).padStart(2, "0")}:` +
    `${seconds.toFixed(1).padStart(4, "0")}`
  );
}

function launchCelebration(session) {
  const celebrationKey = `82-0-celebrated-${session.run_number}-${session.chase_finished_at}`;
  if (sessionStorage.getItem(celebrationKey)) return;
  sessionStorage.setItem(celebrationKey, "true");
  ui.celebrationDetail.textContent =
    `Final composite ${number(session.final_score, 3)} · ` +
    (session.clock_enabled
      ? `Clock ${formatDuration(Number(session.clock_elapsed_seconds || 0) * 1000)}`
      : "Clock was off");
  const colors = ["#76e6a5", "#ff6b2c", "#f7ca62", "#ffffff", "#61a8ff"];
  ui.confetti.innerHTML = Array.from({ length: 90 }, (_, index) => {
    const left = (index * 37) % 100;
    const delay = (index % 15) * 0.08;
    const duration = 2.6 + (index % 9) * 0.16;
    const drift = `${((index * 53) % 180) - 90}px`;
    const color = colors[index % colors.length];
    return `<i class="confetti-piece" style="left:${left}%;background:${color};animation-delay:${delay}s;animation-duration:${duration}s;--drift:${drift}"></i>`;
  }).join("");
  ui.celebration.hidden = false;
}

ui.spinForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const team = ui.teamInput.value.trim().toUpperCase();
  const era = normalizeEra(ui.eraInput.value);
  const path = app.state.session.active
    ? "/api/run/next-spin"
    : "/api/run/start";
  mutate(path, { team, era });
});

ui.teamReroll.addEventListener("click", () => {
  mutate("/api/run/team-reroll", {
    team: ui.teamRerollInput.value.trim().toUpperCase(),
  });
});

ui.eraReroll.addEventListener("click", () => {
  mutate("/api/run/era-reroll", {
    era: normalizeEra(ui.eraRerollInput.value),
  });
});

ui.endRun.addEventListener("click", () => {
  if (confirm("End this run and clear the active roster?")) {
    mutate("/api/run/end", { reason: "manual" });
  }
});

ui.resetClock.addEventListener("click", () => {
  if (confirm("Reset the stopwatch to zero?")) {
    mutate("/api/clock/reset");
  }
});

ui.clockToggle.addEventListener("click", () => {
  mutate(
    app.state.session.clock_running
      ? "/api/clock/pause"
      : "/api/clock/start",
  );
});

ui.disableClock.addEventListener("click", () => {
  if (confirm("Turn off and clear the stopwatch?")) {
    mutate("/api/clock/disable");
  }
});

ui.closeCelebration.addEventListener("click", () => {
  ui.celebration.hidden = true;
  ui.confetti.innerHTML = "";
});

document.addEventListener("click", (event) => {
  const take = event.target.closest("[data-take]");
  if (take) mutate("/api/run/take", { card_id: take.dataset.take });
  const end = event.target.closest("[data-end]");
  if (end) mutate("/api/run/end", { reason: "policy" });
});

ui.playerSearch.addEventListener("input", renderPlayers);
ui.positionFilter.addEventListener("change", renderPlayers);

async function initialize() {
  try {
    [app.catalog, app.state] = await Promise.all([
      api("/api/catalog"),
      api("/api/state"),
    ]);
    fillOptions(ui.teamOptions, app.catalog.teams);
    fillOptions(ui.eraOptions, app.catalog.eras);
    render();
  } catch (error) {
    ui.saveStatus.textContent = "Connection failed";
    showToast(error.message, true);
  }
}

async function refreshState() {
  if (app.busy || app.refreshing || !app.state) return;
  app.refreshing = true;
  try {
    const state = await api("/api/state");
    if (!app.busy) {
      app.state = state;
      render();
    }
  } catch {
    ui.saveStatus.textContent = "Solver disconnected";
  } finally {
    app.refreshing = false;
  }
}

initialize();
setInterval(updateTimer, 100);
setInterval(refreshState, 1200);
