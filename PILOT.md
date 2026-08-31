# The pilot program (live 2026-08-31)

Five repos: kinocut, Epoch, devarch-framework, Innerscape, Elixis (every org
repo that ran CodeRabbit). Live posting, review-only (fix lane off), balanced
tone with fork hard-override, qwen3.8-27b brain + DeepSeek-V4-Flash-0731
fallback, hourly runner at :20.

## Monitoring (codesitter PM)

- **Telemetry** = the runner's hourly one-line-per-repo reports (scanned /
  reviewed / dep_skipped / model_down) + `~/.codesitter/*.state.json`.
- **PM review cadence**: each session reads the runner reports since last
  look; anything anomalous (crash loops, model_down persistence, double
  posts) files to the map (.github #63) and BUG-SMELL-REGISTRY per
  empower-orchestrator law.
- **Acceptance metrics** (Greptile lesson): watch address-rate of posted
  findings per repo; a repo whose findings are never addressed = tuning
  conversation, not louder reviewing.

## Expansion beyond the pilot

New repo = a `.codesitter.yaml` (in-repo) + a central config in this repo +
one line in the runner prompt. Criteria for admitting repo #6+: the pilot
shows (a) no double-post/marker incidents, (b) model route stability, (c) at
least one addressed finding per active repo. Pilot window: 2 weeks or first
incident-free 100 reviews, whichever first.
