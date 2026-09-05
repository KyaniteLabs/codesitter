# Fresh whole-project round 16 and pending-repair review

## BLUF

**Whole-project verdict: NOT GREEN. Parent pending repairs: APPROVE (scoped). Feature13 candidate: REJECT for shipment / MIXED as a local-evidence prototype.** Confidence: 9/10 on the parent repair, 9/10 on the reproduced Feature13 defect, and 10/10 that Feature13 has not met its own shipping gates.

## Identity and method

- Reviewed working tree at `HEAD c75392ff0dff8ff9bd4da5758c6f074c0264ff45` on branch `main`; no branch switch, network, paid model call, deployment, commit, message, or delegation.
- The pre-review tracked diff SHA-256 was `66bf2d68e73e01868d2036266c9ed660227521d677fc13a527d3981d9293b3de`. Feature13 was untracked: `fl4write/exhaustive.py` SHA-256 `b771e288773def6c24c517633e66808d47c0d05af902c01741a4ceb2cd415be2`; `tests/test_exhaustive.py` SHA-256 `f3eb57ce8b8f1a0633fe11224f415b7654d31a71ba5c52de9be380f0aedb3a01`.
- Recon covered review pipeline, action lanes, engine/state, forge/config/CLI, and tests/docs/runner through the repository codegraph, current diff, round ledger, focused source reads, executable probes, and the three authorized test files. No full suite was run.

## Pre-registered gates

The parent repair would be approved only if the configured live route replaced the unit fixture, fleet-config credentials were test-local, zero-skip summaries parsed, complete audit bodies carried readiness, old published audits refreshed once without rescanning, and failed refreshes prevented fixes. It would be rejected by contradictory control flow or a focused failure.

Feature13 would be approvable only if the fixed subprocess, full coverage and budgets, persisted reset/freshness rules, malformed-state containment, fix/refresh/note loop, authenticated owned-PR integration, forge publication, quorum audit, and dogfood gates all survived counter-check. Any crashable persisted boundary or missing contract stage rejects shipment.

## New reproduced finding

### R16-001 — Major — malformed green baseline escapes containment

`_load_state` checks only that `green_baseline` is a list (`fl4write/exhaustive.py:119-120`). The regression path later computes and sorts its set difference (`fl4write/exhaustive.py:465`). A state with `green_baseline=["ok", 1]`, `round=1`, and a one-row ledger was accepted by `_load_state`; the exact follow-on expression raised `TypeError: '<' not supported between instances of 'str' and 'int'`. This is a reproduced crash, not inference. It contradicts the candidate's “corrupt state fails closed” claim (`docs/EXHAUSTIVE-USAGE.md:38-40`) and the canonical shape-containment requirement (`EXHAUSTIVE-BUG-RESOLUTION.md:87-88`).

Fix: validate `green_baseline` as a duplicate-free list of non-empty string test IDs during `_load_state` (and validate relevant ledger/pending row shapes), then pin mixed types and duplicates through `run()`, not only the loader.

No additional concrete defect was reproduced in the parent repair or the other reviewed domains. That statement is scoped to this pass; it is not a whole-project certification.

## Parent pending repairs — APPROVE (scoped)

- Live evaluation now loads `FL4WRITE_EVAL_CONFIG` or the repository's real config and passes that route to `analyze` (`tests/test_planted_diffs.py:142-162`), rather than `_config()`'s fake endpoint.
- Fleet-config dummy credentials use `monkeypatch.setenv` only when absent (`tests/test_fl4write.py:727-736`), so pytest restores them and does not poison later live tests.
- The nested summary accepts an omitted skip clause and normalizes it to zero (`tests/test_gauntlet_fixes.py:3117-3126`).
- Complete omnisweep bodies calculate and render readiness plus the non-certification warning (`fl4write/engine.py:592-597`). Completed published audits lacking report version 2 enter the upsert path; successful publication stamps version 2, while a failed update returns before `_omni_fix_phase` (`fl4write/engine.py:713-731`, `fl4write/engine.py:1058-1093`). `tests/test_round15.py:65-107` pins complete/incomplete rendering, one-time no-rescan refresh, and fix deferral on update failure.
- Focused verification: `python3 -m pytest -q tests/test_round15.py tests/test_exhaustive.py tests/test_pm_recovery.py` passed **79/79** in 10.97s. Pytest emitted cleanup warnings for read-only archive trees; assertions remained green.

This approval covers only the named repairs. The reported live full-suite 668/668 is parent evidence in `docs/pm-recovery/LIVE-EVAL-VERIFICATION.json`, not a certification and not rerun here. The current README's later 669/672 counts were not full-suite-verified under this brief.

## Feature13 candidate — REJECT for shipment

The revised design materially fixes the rejected caller-attestation concept: `_recon` launches a fixed module subprocess with a temporary HOME and only the selected credential (`fl4write/exhaustive.py:255-299`); each text chunk reserves the configured maximum output tokens before a call and records hashed coverage (`fl4write/exhaustive.py:230-250`); HEAD drift, findings, failed tests, lost test IDs, and moved certifications reset or invalidate state (`fl4write/exhaustive.py:401-508`). The focused evidence for those paths passes.

The strongest counter-case is therefore real: this is a useful, default-off, SHA-bound local-evidence prototype. It is still not the requested exhaustive bug-resolution feature. R16-001 breaks malformed-state containment. More fundamentally, findings stop with “authenticated owned-PR fix adapter is not implemented” (`fl4write/exhaustive.py:450-456`), so recon never performs FIX → REFRESH → NOTE. The command writes only local evidence; it does not publish the round ledger or certification (`docs/EXHAUSTIVE-USAGE.md:1-4`, `:28-43`).

Exact missing gates before Feature13 approval:

1. Repair and regression-pin R16-001 at the full `run()` boundary.
2. Implement authenticated owned-PR fixes with ownership/fork rails, regression pins, post-fix full-suite verification, and a fresh post-fix archive/context.
3. Publish the per-round ledger and final certification through the forge with retry/idempotency and failure containment.
4. Integrate a documented default-off trigger into the product/CLI/config lifecycle and prove per-repo runner isolation.
5. Obtain the required fresh-context quorum audit and run the tranche's own three consecutive zero-new-defect dogfood rounds at one shipped SHA (`EXHAUSTIVE-BUG-RESOLUTION.md:98-109`). Current counter remains 0/3.

## Coverage and exclusions

Reproduced: R16-001 and 79 focused passing tests. Source-confirmed: the named parent control flow and Feature13's explicit missing stages. Inferred/unverified: remote publication state, live provider reliability, CI/runner behavior, migration receipts, current fleet configuration population, README test totals, and all interactions outside the focused selection. No primary full suite, live model, network, forge, deployment, signing, or paid probe ran. Parent-reported 668/668 is evidence of one prior suite execution, not proof of zero defects.

## Counter-case, justice, and calibration

Approving the parent repair separately is fair because its narrow behavior has direct source and test evidence and does not depend on Feature13. Shipping Feature13 would transfer the cost of a false “exhaustive” claim to repository owners while fix, publication, quorum, dogfood, and malformed-state gates remain open. Rejecting the prototype's useful local-evidence behavior would also be unfair; the MIXED verdict preserves that demonstrated value without promoting it to certification.

Calibration log, 2026-09-04: parent pending repairs `CONFIRM/APPROVE`, 9/10; Feature13 full shipping claim `REFUTE/REJECT`, 10/10; revised local-evidence design `MIXED`, 8/10; whole-project green claim `REFUTE`, 10/10.

## IMPROVEMENTS

1. **Validate persisted collections deeply.** Why: `green_baseline` passed a shallow list check and crashed the next stage. Fix: centralize typed state decoding and exercise every accepted state through one complete round.
2. **Make focused archive fixtures cleanup-safe.** Why: the authorized green run emitted repeated `Directory not empty` warnings from mode-locked trees. Fix: restore writable modes in fixture teardown or keep artifacts outside pytest's automatic removal tree.
3. **Bind test-count claims to one generated artifact.** Why: verification JSON says 668 while README currently says 669 default / 672 live, and this brief forbade the resolving full run. Fix: generate README counts from a single hashed JUnit receipt and fail docs checks on stale hashes.
