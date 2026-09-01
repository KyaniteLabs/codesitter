# The pilot program (live 2026-08-31; renamed + consolidated 2026-09-01)

**32 repos** — 5 wave-1 org repos (kinocut, Epoch, devarch-framework,
Innerscape, Elixis) + 26 wave-2 repos (org + owner's personal; originally-ours
only, no forks/collabs; `voice-to-sculpture-app` removed — repo never existed
under that spelling; **liminal held** — Sinter's repo, #999 conversation, not
unilateral) + **KyaniteLabs/fl4write itself as #32 (2026-09-01, CEO CI-failure
directive: own-repo CI red summons review+fix — the bot dogfoods on its own
repo)**. Full product live: review + gatekeeper + metrics + **fix lane** +
**issues lane** (all four enabled 2026-09-01, CEO order) + **post-merge
review mode** (PM-2, 2026-09-01; fleet-enabled — reviews PRs merged since a
per-repo watermark, findings as post-merge comments, fixes as follow-up PRs —
the answer to this org's ~60s merges the open-PR poller never sees, LEARNINGS
#24) + **CI watch** (CEO directive 2026-09-01: red default-branch HEAD on an
own repo → findings from failing checks' annotations → fix-lane PR; no-fix →
escalation issue; SHA-keyed, never re-acts on the same head; own-repos only —
forks/upstream structurally out). Brain (TRANSITION):
today DeepSeek-V4-Flash-0731 via deepinfra (the $40-budget ledger route) —
**the CEO is building a local-inference floor with multiple models + a
consensus system** (2026-09-01); when it lands, the model routes in these
configs change and the fallback==primary warning becomes moot. Coordinate
with that lane before touching model routing. Identity:
`fl4write[bot]` (GitHub App "Fl4wRite", ID 3592379; per-repo installation
resolution across the org AND user-account installations).

## The runner (single-host law)

- **Host**: nucbox `simon@100.113.174.74`, clone at `~/workspaces/fl4write`,
  crontab `0 * * * * ~/workspaces/fl4write/run-cycle.sh` (self-updating —
  pulls main first; model key read from `~/.bashrc`, quote-stripped).
- **Log**: `~/workspaces/fl4write/runner.log` — per-cycle summary line, ERR
  lines, and per-repo ALERT lines (adoption-lost etc.; surfaced 2026-09-01 —
  an "ok" status used to hide alerts).
- The zcode/laptop-hosted runner automation was RETIRED 2026-09-01: two
  hosts with independent state files = duplicate posts (LEARNINGS #17).
  One runner, one state dir. Do not re-add a second host.

## Monitoring (fl4write PM)

- **Telemetry** = the hourly runner.log line + `~/.fl4write/*.state.json`.
  A green cycle is `31 ok / 0 errors` with zero ALERT lines.
- **PM review cadence**: each session reads runner.log since last look;
  anything anomalous (crash loops, model_down persistence, double posts,
  ALERT repeats) files to the map (KyaniteLabs/.github #63) and
  BUG-SMELL-REGISTRY.md per empower-orchestrator law.
- **Acceptance metrics** (Greptile lesson): watch address-rate of posted
  findings per repo; a repo whose findings are never addressed = tuning
  conversation, not louder reviewing.
- **Racing-branch surveillance**: config-presence check every cycle. Five
  adoption losses so far (Innerscape ×1, Elixis ×2, devarch-framework ×1,
  tastecheck ×1, content-production-system ×1). An ALERT means: re-adopt on
  current main, then verify CONTENTS-ON-MAIN — never trust the merge event.

## Pilot soak (clock restarted 2026-09-01)

Day 1 of 14. Criteria before repo #32 or more autonomy: **14 incident-free
days OR 100 incident-free reviews** — zero double-posts, zero email storms,
model-route stability, surveillance proven. Incidents so far (all fixed with
regression tests, see LEARNINGS.md): the email storm (#17), the rename-sweep
URL bug (#18), the app-slug identity change (#20). Soak counts post-fix days.

## Expansion beyond the pilot

Unchanged ladder (each gate before the next): acceptance metrics surfaced →
fix-lane first real fix verified → issues-lane behavior contract
(BEHAVIOR.md covers PR review only) → gatekeeper tuning from live data →
repo #32+. Adding a repo = a `<repo>.fl4write.yaml` in this repo + the
in-repo config (direct contents-PUT where allowed; **8 repos have rulesets
requiring PRs — PUT 409s; research-scout allows squash merges only**).
