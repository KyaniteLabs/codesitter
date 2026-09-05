# Round 15 repair review

## Verdict

**APPROVE — scoped repairs and authority configuration.** The current uncommitted repairs correctly address R15-001, R15-003, and R15-004 without a regression found in the reviewed paths. The parent is also correct to **REJECT R15-002 as reported**: `_omni_fix_phase` checks `sev not in config.severity_vocab` and continues before calling `.index(sev)`, and the executable regression proves an unknown persisted severity neither crashes nor attempts a fix.

This is an independent scoped approval, not an exhaustive green round. It does not change the fresh report's whole-project status or the three-clean-round counter.

## Repair assessment

- **R15-001 — APPROVE.** `_normalize_aux` now removes malformed optional `fix_attempted` and `fix_stale` values from every retained finding, not only while reconciling a malformed required field. The restart-to-fix-phase tests cover both flags with the previously suppressive string `"false"` and integer `0`; all four cases attempt the eligible fix.
- **R15-002 — REJECT finding.** The claimed `list.index` crash is unreachable for an unknown finding severity because the membership guard at `fl4write/engine.py:624` precedes the lookup at line 626. `test_unknown_severity_already_skips_fix_without_crashing` supplies `"Severe"`, forbids executor invocation, and completes with zero fix attempts.
- **R15-003 — APPROVE.** Persisted finding lines now reject booleans and require a positive integer. Restart tests cover `True`, `False`, zero, and negative one and verify both the findings and stale completion/head state are reconciled away.
- **R15-004 — APPROVE.** A marker-bearing comment with uncertain ID, body, or author identity now raises `ForgeError`; the live issue lane catches that uncertainty before model use or publication, records an error, and retains the issue for retry. Six malformed identity shapes verify no model call, no duplicate comment, no watermark advance, and a preserved retry entry.

## Authority configuration assessment

**APPROVE.** `.fl4write.yaml`, `fl4write.fl4write.yaml`, and `tastecheck.fl4write.yaml` all validate through `load_config` with Forgejo as the sole primary, GitHub as the mirror, and `bot_login: fl4write`. The configuration uses existing primary/mirror and identity fields. Unsupported v1 action surfaces are fail-closed: the two fl4write configs disable both `fix` and GitHub-only `ci_watch`; tastecheck disables `fix` and does not enable `ci_watch` (its schema default is false). No new fleet capability is enabled by these changes.

The repository migration, Forgejo-first landing of `a5d56df`, runner placement, and tastecheck PR 40 are accepted as parent-supplied operational evidence; this no-network review did not independently reverify remote state.

## Verification

- `python3 -m pytest -q tests/test_round15.py tests/test_pm_recovery.py` — **60 passed**.
- `python3 -m ruff check fl4write/issues.py fl4write/state.py tests/test_round15.py` — **all checks passed**.
- All three changed YAML configs loaded successfully and resolved to Forgejo primary, GitHub mirror, `bot_login=fl4write`, `fix.enabled=false`, and `ci_watch.enabled=false`.
- `git diff --check` — passed.
- The parent-reported host result remains **665 passed / 3 live-model skips**; it was not rerun here, per scope.

## Remaining limits

No network, deployment, remote Forgejo/GitHub, runner, credential, live-model, commit, or exhaustive-suite verification was performed. The fresh round remains explicitly non-green beyond this repair/config scope.

## IMPROVEMENTS

1. **Pin the project test interpreter.** Why: the standalone `pytest` executable points at Python 3.11 and failed collection with `ModuleNotFoundError`, while `python3 -m pytest` passed all 60 tests under the active environment. Fix: document or wrap the canonical test command and add an environment preflight that confirms the package import before pytest collection.
2. **Add direct config authority regression tests.** Why: this review had to inspect three YAML files and schema defaults separately to prove that Forgejo authority did not accidentally enable unsupported actions. Fix: parameterize the three shipped configs and assert primary, mirror, bot identity, fix, and CI-watch values in one test.
3. **Correct superseded findings in the fresh report.** Why: `FRESH-ROUND-15.md` still labels R15-002 verified even though current executable evidence disproves its crash path. Fix: append an adjudication note linking this review and mark R15-002 rejected without rewriting the original audit record.
