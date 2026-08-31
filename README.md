# codesitter

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

Drop a `.codesitter.yaml` in the repo (see `kinocut.codesitter.yaml` for the
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

## Status

v0.1 — engine core, config schema, fix-lane rails, 42 tests green (incl. the
adversarial subset: injection, malformed payloads, fork safety, stale state,
atomicity, cycle lock, misleading success). Roadmap on map #63: gatekeeper
filter stage, scoped learnings, dependency-dashboard state issue, acceptance
metrics surfacing, GitHub-App trigger adapter (v2).
