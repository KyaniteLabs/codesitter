# FL4WRITE (`fl4write`)

**Capability-grounded review:** every finding cites one of 19 production-hardening capabilities (from the org's own CheckYourself system). Readiness score per repo.

**Day-1 state (2026-09-02):** 54 repos across GitHub + Forgejo (own bot identity on both); five review modes live (open-PR, post-merge, retro, ci_watch, omnisweep full-tree); fix lane working (first real fix: Epoch #199); verify-tests runs the diff's own tests deterministically; plus-ultra telemetry stream + Quality Loop (issue #5). 224 tests.

*Official stylization (CEO, 2026-09-01): **FL4WRITE**. Identity surfaces unchanged by law: repo/package `fl4write`, env vars `CODESITTER_*`, markers `fl4write:v1:`, bot logins.*

Self-hosted, multi-forge code review bot — the org's CodeRabbit replacement.
Chartered by the CEO 2026-08-31; built under wayfinder map
[KyaniteLabs/.github #63](https://github.com/KyaniteLabs/.github/issues/63)
(ralplan consensus-approved; behavior contract = BEHAVIOR.md from ticket #64;
best-practices register = ticket #70).

## What it does

One poll-invariant cycle per run: collect open PRs (GitHub primary + Forgejo
mirror, SHA-deduped) → scrub all untrusted text → LLM-brained findings
(champion route + fallback) → ground every finding (rule in vocab, severity in
vocab, path in diff — ungrounded findings are dropped+logged, never posted) →
render the persistent comment (one per PR, edited in place, 🆕 deltas) →
hand actionable findings to the fix lane. **v0.1 ships the fix lane as a
tested library** (rails: fork comment-only, bot PRs read-only, merge
re-verifies authorship+CI at the call site, depth cap escalates) — engine
wiring lands with the first live deployment (#69), not before.

## Safety architecture (the parts that are laws, not features)

- **State correctness never depends on timestamps**: re-review fires on
  `head_sha != last_reviewed_sha`, so missed events self-heal next cycle.
  Atomic writes (kill-mid-write safe), cycle lock (no double-post), corrupt
  state = bounded reconcile.
- **The model is never on a direct path to a write.** Its output is data
  until code validates it (grounding + scrub); actions are code-gated.
- **Scrub gate**: control/bidi/zero-width chars, data: URLs, base64 images,
  remote src=, hidden HTML, and our own comment markers are neutralized on
  everything crossing the trust boundary (PR bodies, commit text, findings).
- **Fix-lane rails asserted in code at call sites**: fork = comment-only;
  bot-authored dependency PRs = read-only; merge re-verifies authorship+CI
  regardless of config.
- **Tone is a renderer-only preset** (`quiet|balanced|assertive|roast`); the
  analyzer is tone-blind; forks are hard-overridden to `balanced`; Critical
  findings always render urgency.

## Adding a repo

Drop a `.fl4write.yaml` in the repo (see `kinocut.fl4write.yaml` for the
reference instance): forge bindings (exactly one `primary`, others `mirror`),
model routes, repo law as `review:` rules, severity vocab, tone, fix-lane
autonomy, known-env failures. Config validates fail-loud at startup.

## Deployment

v1 trigger = cron (the engine's entry point takes a normalized trigger —
cron is an adapter, not the architecture; the flip list for an event adapter:
hosted brain / acceptable standing listener / existing self-hosted runner).
Run in shadow mode (`shadow: true`) first — findings log, nothing posts.
Cutover checklist: 48h shadow diff reviewed → host decision recorded (always-on
host OR explicitly accepted sleep gap) → PAT scopes enumerated + rotation set.

## Status — v0.4.0 ALL COMPONENTS BUILT (pilot live on 31 repos)

**v0.2.0 adds the four remaining planned components:**
- **Fix-lane executor** (`executor.py`): real worktree → model patch → test → PR → CI-gated merge of OWN PRs (authorship asserted in code). Closes the loop: FL4WRITE can now FIX what it finds, not just report it.
- **Gatekeeper nit-filter** (`gatekeeper.py`): staff-engineer second pass that kills nits before posting (fail-open on model down). The Greptile 79%-nits lesson, implemented.
- **Issues lane** (`issues.py`): GitHub + Forgejo issue triage — duplicate detection, label routing, answer drafting, regression flags. Comment-only (never closes or reassigns). Enable via `--issues` flag.
- **Acceptance metrics** (`metrics.py`): address-rate tracking per cycle (surfaced as `acceptance=NN%` in the runner report once findings accumulate). The quality signal that tells us if findings are being acted on.

**Usage:** `python3 -m fl4write.cli <config> [--live] [--fixes] [--issues]`

v0.4.0 runs in production on **31 repos** (see PILOT.md) — all four lanes
live (review, gatekeeper, fix, issues), posting as `fl4write[bot]`. 60+
tests green; the build has passed two adversarial gates (the original 8-blocker
review, and the 2026-09-01 six-lane audit — ~60 findings fixed; see
LEARNINGS.md #25). The runner is a nucbox crontab (`0 * * * *`) executing
`run-cycle.sh`; the zcode-hosted laptop automation was retired 2026-09-01
(single-host law — see LEARNINGS #17). PM seat: see fl4write issue #3 (the
PM-2 handoff charter). Roadmap on map #63: post-merge review mode (top priority), GitHub-App event
trigger (v2), and **model-routing transition: a local multi-model inference
floor with a consensus system is being built by the CEO** — configs will
migrate off single-route deepseek when it lands.
