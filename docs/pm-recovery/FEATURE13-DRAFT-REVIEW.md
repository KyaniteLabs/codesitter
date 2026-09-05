# Feature 13 unmerged-draft review

## Verdict

**DRAFT: REJECT for shipment; acceptable only as a clearly marked, local-only prototype with forge publication disabled.** The candidate fixes round-16's shallow `green_baseline` validation defect and its focused tests pass, but five safety defects remain. The authenticated atomic fix-plus-regression-pin API, full recon-to-fix-to-refresh workflow, own-repository dogfood, quorum approval, and three clean rounds are still absent. No exhaustive certification or deployment approval is warranted.

Reviewed the uncommitted candidate on `feature/exhaustive-loop-draft` without edits, commits, live models, network mutations, deployment, or delegation. Codegraph reported that this worktree has no `.codegraph` index; `jcode`/`jdoc` were unavailable, so the review used scoped reads and searches as fallback.

## Reproduced defects

### F13-D01 — Critical — forged clean counters bypass all three rounds

`_load_state` validates field types but does not bind `consecutive_green`, `green_sha`, `green_baseline`, and the ledger's trailing green rows (`fl4write/exhaustive.py:105-148`). `run()` then returns success when the persisted counter is 3 and the SHA matches, even with no ledger or JUnit evidence (`fl4write/exhaustive.py:533-535`).

Probe: a version-2 state with `round=0`, `ledger=[]`, `consecutive_green=3`, `green_sha=<current HEAD>`, and `certified_sha=null` was accepted; `run()` returned `0` unchanged. This permits success with zero rounds.

Fix: validate counter/ledger/SHA/baseline consistency as one state machine. Require exactly `consecutive_green` trailing green rows for `green_sha`, each with valid test evidence, and refuse any success path without those rows.

### F13-D02 — Major — forge outage advances the clean counter and changes the retry body

The candidate persists a green round before calling `_publish` (`fl4write/exhaustive.py:620-652`). A failed PATCH therefore returns deferred while keeping the round green. On retry, it performs another round instead of retrying the same publication (`fl4write/exhaustive.py:547-670`).

Probe: first-round PATCH failure returned `2` with `round=1`, `consecutive_green=1`. The next invocation produced `round=2`, `consecutive_green=2`; the second PATCH body differed. This contradicts outage-does-not-count semantics and the documented identical-retry claim.

Fix: persist an exact pending-publication body/hash and replay it before any new round; do not commit the green counter until required publication succeeds.

### F13-D03 — Major — published ledger can leak private absolute paths

`_public_value` strips directory components only for two manifest keys; other strings receive no local-path redaction (`fl4write/exhaustive.py:397-414`). Findings include archived source evidence and messages.

Probe: synthetic absolute home-directory paths in archived evidence and finding
messages survived `_ledger_body` verbatim. The example paths are omitted here.

Fix: publish a strict allow-listed DTO; redact machine-local identifiers in every public string and pin nested values.

### F13-D04 — Major — caller-selected issue is overwritten without ownership proof

`_publish` accepts any positive issue number and calls `update_issue` directly (`fl4write/exhaustive.py:430-434`). Both adapters issue an unconditional body-replacing PATCH (`fl4write/forges.py:680-685`, `fl4write/forges.py:978-983`). There is no marker, author, or compare-before-write check.

Fix: require a product-minted ownership marker plus repository/issue identity, fetch and verify it before every PATCH, and fail closed on mismatch.

### F13-D05 — Major — green evidence artifacts remain mutable

Only the archive and pack manifest become read-only. Coverage, JUnit, worker request/result, and ledger input remain writable after green rows reference them (`fl4write/exhaustive.py:311-333`, `fl4write/exhaustive.py:598-635`).

Probe modes: coverage `0600`, JUnit `0644`, ledger input `0600`, worker request `0600`, worker result `0644`.

Fix: finalize a content-addressed read-only bundle and re-hash every referenced artifact before publication, certification, and recovery.

## Verified scope

- `python3 -m pytest -q tests/test_exhaustive.py tests/test_round15.py tests/test_pm_recovery.py`: **93 passed in 18.49s**.
- Candidate SHA-256: exhaustive module `af746a37df176ba33fd0da84fc5101e6f4403bddfc0b24f8b96519e3bed3d716`; candidate tests `c3e102e04fb2fe3cba663358f94ea5296b9ee81b349831e7b8456803071d3b11`; usage doc `2568ad22febca39a45cb7824562b1d7ab911cfa7a9de87fd706cc0e283c9b886`.
- Round-16's malformed baseline defect is now deeply validated and pinned at `run()` (`fl4write/exhaustive.py:130-133`; `tests/test_exhaustive.py:92-104`).
- `docs/pm-recovery/ROUND15-VERIFICATION.json` records 665 passed and 3 skipped out of 668, zero failures. It predates the candidate and is not candidate full-suite evidence. No inspected receipt proves README's draft claim of 698 passing.
- Archived-HEAD recon, credential-limited subprocess isolation, budgets, JUnit parsing, drift checks, and refusal of the incomplete fix API are useful local prototype behavior. They do not implement FIX → REFRESH → NOTE.

## Required gates still open

1. Fix and regression-pin F13-D01 through F13-D05.
2. Implement authenticated atomic fixes, ownership/fork/base/HEAD rails, post-fix full-suite proof, and a fresh post-fix context.
3. Exercise the complete default-off workflow and per-repository runner isolation.
4. Obtain quorum approval and dogfood three clean rounds at one shipped SHA. Current certification counter remains **0/3**.

## IMPROVEMENTS

1. **Model persisted state as a state machine.** Why: plausible fields combine into forged success. Fix: centralize cross-field invariants and property-test corrupt states.
2. **Separate private evidence from the public DTO.** Why: recursive scrubbing leaked paths and exposes future fields by default. Fix: use an allow-listed schema with privacy and ownership pins.
3. **Make publication transactional.** Why: outage advanced counters and changed retry bodies. Fix: persist exact pending writes and replay before advancing state.

## Parent containment after review

The isolated draft full suite independently completed with 698 passed and 3
live-model skips; FEATURE13-DRAFT-VERIFICATION.json records that receipt.
After this review, the parent disabled forge publication at both the run
boundary and the publication function. Two focused tests prove requests and
retries make no forge calls or state progress; lint passes. This quarantines
external writes and does not resolve the five findings or approve shipment.
The candidate remains local-only on feature/exhaustive-loop-draft, excluded
from main and production. The main release remains independently approved.
