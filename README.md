# FL4WRITE (`fl4write`)

**Capability-grounded review:** findings ground in the configured rule set (the org's own CheckYourself capabilities merge into every config); the ``general`` rule remains the bounded fallback for defects no capability names (F2-004 doc truth). Readiness score per repo.

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

## Status — v0.4+ production (fleet of 129 central configs; see PILOT.md)

All five review modes live (open-PR, post-merge, retro audit, ci_watch,
omnisweep) plus gatekeeper, verify-tests and acceptance metrics. The issues
triage lane is available per-repo via `issues_enabled` + `--issues` (opt-in;
no fleet repo has enabled it yet — luna F3-004 doc truth).
**Usage:** `python3 -m fl4write.cli <config> [--live] [--fixes] [--issues]`
(mode flag typos are refused — unknown flags exit 2).

Current fleet state (2026-09-04, MECE audit round 1): **129 central configs**
across GitHub + Forgejo cycling ~100 repos/hour on the nucbox runner
(`run-cycle.sh`, hourly crontab, single-host law — LEARNINGS #17). **400+
tests green** (426 collected / 423 passing + 3 live-eval as of the MECE
round-4 desk pass), ruff clean, CI on every push. Quality loop on
issue #5; desk charter + incident history on issue #3 and map #63.

Honest status line (post 2026-09-03 adjudication): the bot is NOT yet
declared fit-for-use at scale — the desk's own adjudicated sample found the
majority of posted Criticals were false positives (see #5 and LEARNINGS
#38-42). Severity-integrity gates, execution-evidence test gating, adapter
containment and the scrub/injection surface were rebuilt under the readiness
gauntlet; phase-2 citation grounding (findings must quote the reviewed
code's bytes) is the remaining gate before re-quoting Q1.
