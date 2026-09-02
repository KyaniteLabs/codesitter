# ISSUES-BEHAVIOR.md — the issues-lane behavior contract (L5, 2026-09-02)

BEHAVIOR.md governs PR review. This contract governs the ISSUES lane
(`issues.py`, `--issues`) — its own surface, its own laws.

## Identity and posture
- Posts as FL4WRITE via the persistent-comment law: ONE triage comment per
  issue, created once, then EDITED IN PLACE on re-triage. Never a second
  comment; markers + author-verified lookup exactly as PR review.
- Comment-only. The issues lane never: changes labels via API, closes/
  reopens issues, assigns people, or opens new issues (the single bounded
  exception: ci_watch escalation issues, separately gated).

## Triage behavior
- Trigger: new issues only (state `last_triaged_number` watermark; the
  one-state-owner law — the lane mutates the engine dict, never loads/saves).
- Content: labels (existing repo labels only), duplicate hint (never auto-
  closes), a DRAFT reply clearly marked as a draft, urgency low/medium/high,
  regression flag. All model output passes scrub; issue text is DATA.
- Model contract: the lane sends its OWN triage system prompt (audit A6b —
  it used to receive the analyzer's), parsed via envelope-key extraction;
  ANY failure returns None (fail-open = skip the issue, never a bad triage).
- Human surface: the triage comment always ends with the "draft, not a
  decision" footer; humans act, the bot informs.

## Rails (asserted in code, not just config)
- `issues_enabled` default false — the lane is opt-in per repo.
- Rate: one triage comment per issue per lifetime unless the issue body
  changes materially (edit-in-place covers re-triage without re-notify).
- No secrets in triage output (scrub gate); no links to private internals.

## Known limits (documented, not drifted)
- Duplicate detection is hint-only (no cross-issue API writes).
- The lane runs on the hourly cycle; no webhook trigger (v1 polling posture).
