# Recovery comorbidity check

The confirmed failures share a gap between the claimed boundary and the
boundary actually enforced. Recovery repairs six concrete manifestations;
the remaining predictions below are inferences, not additional confirmed bugs.

## Confirmed cluster

- Round-14's pathname fix changed separator selection but retained whitespace
  truncation. Its original example still failed.
- Listing completeness checked a counter that dictionary-rejection branches
  never incremented. Both adapters could report partial results as complete.
- Public schema strictness rejected boolean numerics but accepted numeric
  strings; URL validation inspected netloc but not hostname/port.
- Lifecycle collision prevention serialized credentials reversibly, bypassing
  the separate redaction boundary.
- Scheduler validation checked for the letter T while canonical state
  validation parsed timestamps. Identical data had different trust outcomes.
- The live cycle's aggregate success coexists with an adoption alert and a
  model-unavailable result. Existing pilot rules already disqualify this cycle
  from the stronger health claim; the aggregate is not itself proof of health.

Reproduction and fixes are in tests/test_pm_recovery.py. The prior independent
review is INDEPENDENT-REVIEW.md. Local verification is VERIFICATION.json.

## Shared mechanism and competing explanation

Fixes were made at one visible branch while the surrounding contract remained
broader. The same pattern crossed parsing, state, configuration and reporting.
The missing round-14 ledger entry and absent new test cases made that gap hard
for a successor to see.

An alternative explanation is expected historical contract evolution: older
tests deliberately allowed filtered lists. That explains the round-7 test
conflict, but does not explain why the round-14 source example still failed
or why the new completeness counter was never incremented. Those are direct
implementation defects.

## Predicted comorbidities (inferences)

| Likelihood | Mechanism and predicted symptom | Falsifiable probe | Blast radius |
|---|---|---|---|
| High | Other parse/translation branches may discard malformed records before an incompleteness guard observes them, allowing premature completion. | For each remaining round-14 enumeration surface, insert a malformed row before and after a valid sibling; assert no cursor/prune/completion changes. Reject the hypothesis for each surface whose guards preserve the invariant. | Individual repo's review state and missed reviews. |
| High | Historical status pages may inherit the last announced round rather than the runner's deployed SHA, overstating verified closure. | Compare source SHA, CI SHA, round disposition and posted update; this recovery already found round 14 deployed while tracker/ledger stopped at 13. | PM handoff and release decisions. |
| Medium | Old encoded finding identities may be re-rendered differently during migration, producing a one-cycle new/resolved mismatch. | Replay sanitized old-format and new-format comments through a complete re-review; compare semantic identities and output redaction. Current same-format round-trip checks pass, which limits this prediction to migration. | Comments containing specially escaped or credential-shaped filenames. |

## Blind spots

The focused review does not cover every original round-14 finding behaviorally.
Live-model recall, real fix completion, old-comment migration, and production
execution of the successor repairs are not established. The 35 model events
without an explicit success flag preclude a simple 27/75 success-rate claim.

## Probe order and stop condition

First run exact source reproductions and malformed-input pairs locally, then
replay old comments, then check deployed SHA plus runner evidence after an
authorized landing. The shared mechanism is no longer useful for a surface
when all adjacent branches enforce the same invariant and the second-site
probe passes. Exhaustive project closure still requires three independent
full green rounds; this check does not replace them.
