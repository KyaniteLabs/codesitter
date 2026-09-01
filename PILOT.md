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

## Wave 2 (2026-08-31, CEO order "deploy all")

28 repos added (all originally-ours, no forks, no collabs, ≥14d quiet): chance, reverse-engineering, research-scout, cerafica-api, cerafica-client, kyanite-landing, tradesflow, vocal-layer-studio, handoff-cms, Achiote, unstuck-coach-protocol, voice-to-sculpture-app, research-pipeline-prod, Creator-kit, dev-learning-archaeologist, content-production-system, small-business-skills, unstuck-coach, achiote-food-memory-researcher, codex-small-business-skills, web-typography-skill, personal-llm, unstuck-coach-live, checkyourself, tastecheck, complyos, evo-x2-ec. **liminal held** (Sinter team repo — #999 conversation, not unilateral).

Pilot total: **32 repos** (5 wave-1 + 27 wave-2). All configs verified on main (32/32 ok, 0 alerts). Runner auto-discovers via glob — no prompt edit needed (which would re-pause the automation).
