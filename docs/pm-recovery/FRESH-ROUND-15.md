# Fresh round 15 whole-project recon

> Post-review adjudication: R15-002 is **rejected as reported**. The existing
> membership guard precedes the severity lookup; a restart-to-fix-phase test
> proves that the claimed crash is unreachable. R15-001, R15-003 and R15-004
> were reproduced and repaired. Independent scoped approval is recorded in
> ROUND15-REPAIR-REVIEW.md. Original reviewer text below is retained as evidence.

## Review identity

- Reviewed base HEAD: `cc1e48663986ab50af07fd44fbded7f7aa0bc92a`
- Reviewed pre-report working-tree diff SHA-256: `95712e59ec2231edfc2c33edc7339937b1710052f9caa4f2b3bf367285cde03b`
- Tree state: dirty successor-recovery tree; this report is the only round-15 write.
- Method: current CodeGraph index first (164 files, 1,587 nodes, 3,793 edges), then durable charter/ledger, source inspection, targeted tests, compile check, and standalone reproducing probes.

## Verdict

**RECON INCOMPLETE / NOT GREEN.** Four verified defects remain. One directly reopens round-14 finding F14-C003; the other three are new concrete defects in the same state/action boundary families. The three-clean-round counter remains **0/3**. This review cannot certify whole-project closure because the parent, not this worker, owns the full host pytest run, live forge/provider behavior was not exercised, and the requested exhaustive-loop product tranche in `EXHAUSTIVE-BUG-RESOLUTION.md` remains explicitly unimplemented.

## Verified defects

### R15-001 — persisted string fix flags still suppress omnisweep fixes

- Domain: engine/state (DOM-C); severity: major; verdict: **verified, reopened F14-C003**.
- Evidence: `fl4write/state.py:228-262` validates findings, but normalization of `fix_attempted`/`fix_stale` is inside `if bad:` at lines 242-262. A structurally valid finding therefore retains `fix_attempted: "false"`. `fl4write/engine.py:626` reads the field by truthiness and skips the fix.
- Reproducing probe:

  ```text
  load_state({valid omni finding, fix_attempted: "false"})
  => PROBE_FIX_FLAG 'false' True
  ```

- Impact: a corrupt or older state record permanently suppresses an eligible fix while appearing to say false.
- Required repair: normalize optional fix flags for every retained finding, independent of whether another finding is malformed; add a load-state-to-fix-phase regression pin.

### R15-002 — arbitrary persisted severity crashes omnisweep fix phase

- Domain: engine/state (DOM-C); severity: major; verdict: **verified, new** (same class as historical F3-C102, but current behavior is a fresh reopening).
- Evidence: `fl4write/state.py:234-241` requires only that `sev` is a string. `fl4write/engine.py:626` calls `config.severity_vocab.index(sev)` without containment.
- Reproducing probe:

  ```text
  load_state({valid omni finding, sev: "Severe"}) => retains 'Severe'
  ['Critical','Major','Minor','Nit'].index('Severe')
  => ValueError: list.index(x): x not in list
  ```

- Impact: one vocabulary-drifted state row can abort the omnisweep fix lane every cycle.
- Required repair: validate persisted severities against the supported vocabulary (drop/reset or quarantine invalid rows) and contain the fix-phase lookup; pin restart behavior.

### R15-003 — boolean line survives persisted-finding validation

- Domain: engine/state (DOM-C); severity: minor; verdict: **verified, new**.
- Evidence: `fl4write/state.py:239-241` excludes booleans for `id` but checks only `isinstance(line, int)` for `line`; in Python, `True` is an integer.
- Reproducing probe:

  ```text
  load_state({valid omni finding, line: true})
  => PROBE_BOOL_LINE True True
  ```

- Impact: malformed state can target/render line 1 as a seemingly valid anchor, weakening the persisted-evidence contract.
- Required repair: reject boolean lines explicitly and require the same positive-line bounds used at analyzer boundaries; add reconciliation pins for `true`, `false`, zero, and negative values.

### R15-004 — malformed owned triage marker causes a duplicate comment

- Domain: action lanes/forge boundary (DOM-B/D); severity: major; verdict: **verified, new** (parallel to F14-D008, but the issue-triage path remains unprotected).
- Evidence: `fl4write/issues.py:180-195` discards a marker row with an unusable ID. Both `find_existing_triage` (`198-210`) and `_foreign_triage_exists` (`213-227`) therefore report absence. `run_issues_cycle` then reaches `create_comment` at line 352.
- Reproducing probe: a fake forge returned `{'id': None, 'body': '<!-- fl4write-triage:v1 -->', 'user': {'login': 'fl4write[bot]'}}`; with deterministic triage output the lane printed `PROBE_DUPLICATE_CREATE 1` and returned `{'triaged': 1, 'errors': 0, 'quarantined': 0}`.
- Impact: an uncertain/malformed response can email-spam an issue with duplicate bot triage, violating the at-most-once law already enforced for review comments.
- Required repair: make marker detection tri-state (owned / foreign / uncertain) or raise `ForgeError` when any owned marker has an unusable ID; pin that no model call or comment creation occurs.

## Coverage and exclusions

- Review pipeline: analyzer parsing/grounding, gatekeeper, scrub, renderer lifecycle, capabilities/readiness; round-14 recovery pins inspected. No additional verified defect recorded in this domain.
- Action lanes/executor: issue collection/triage/comment identity, fix/test/merge surfaces, telemetry early exits; one verified defect.
- Engine/state: open/post-merge/CI/retro/omnisweep orchestration, deadlines, pruning, state reconciliation; three verified defects.
- Forge/config/CLI: adapters, pagination/completeness, diff routing, app-auth namespace, strict config/CLI handling; the triage-marker defect crosses this boundary, but no second standalone defect was verified.
- Tests/docs/runner: charter, round ledger, recovery artifacts, test inventory, runner and dirty-check scripts inspected.
- Targeted evidence: `tests/test_pm_recovery.py` passed **45/45**. The gauntlet target reached 171 passes before its nested whole-suite assertion failed solely on the inherited GPG sandbox fixture (`test_check_dirty_clean_checkout_passes`: signing `Input/output error`; nested result 649 passed, 3 skipped, 1 failed). Per brief, this is **not counted as a product bug**. `python3 -m compileall -q fl4write` completed without output/error in the combined probe.
- Explicit exclusions: no full pytest initiated as a primary round-15 action; the gauntlet's own nested doc-truth check invoked it. No live GitHub/Forgejo, model, runner host, deployment, credential, network, or fleet probe. YAML fleet semantics were sampled through tests/source rather than independently exercising all configs. No mutation, commit, communication, or delegation.

## Duplicate and hypothesis handling

- R15-001 is explicitly a round-14 reopen; it is counted once.
- R15-002 is treated as a current reopening of the historical severity-drift class, not a second independent count.
- R15-004 is not a duplicate of F14-D008: that repair protects review-comment adapters, while this reproduction uses the separate issue-triage scanners.
- Runner exit-status semantics and PAT fallback identity remain hypotheses; neither is counted without a governing contract plus behavioral reproduction.

## IMPROVEMENTS

1. **Move state schema rules into one canonical validator.** Why: three defects came from asymmetric ad hoc checks in `_normalize_aux`. Fix: validate every `omni_findings` row through a typed model and atomically reset/quarantine on any invalid field.
2. **Share one tri-state persistent-marker scanner across review and triage lanes.** Why: the at-most-once repair covered review comments but missed the parallel triage implementation. Fix: return `absent`, `owned(id)`, or `uncertain/foreign`, with uncertain always fail-closed.
3. **Split the README live-count assertion from ordinary targeted tests.** Why: selecting one gauntlet test unexpectedly spawned the full suite and hit the known GPG fixture. Fix: mark the nested full-suite doc-truth test as a host-only/integration check and provide a collection-only unit pin for targeted runs.
