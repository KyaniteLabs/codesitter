# FL4WRITE PM recovery — 2026-09-04

## Current successor disposition — September 5

This section supersedes operational status in the historical recovery record below.

The original first-week checklist is reconciled: charter/history read, seat
posted, duplicate configs verified absent, self-review cycle verified live,
capability-grounded fix attempts inspected, comorbidity checked, and quality
report posted. Those seven obligations are complete. The eighth, an hourly
green cycle, remains blocked by the live alerts described below; process exit
success alone does not close it. A completed organic fix is a separate pilot
milestone, not a substitute for the original attempt-observation checkbox.
Forgejo is canonical, GitHub mirrors main automatically, and the sole NUCBox
runner has deployed releases a5d56df and c75392f. Tastecheck adoption was restored
through its merged PR 40 and verified with a live cycle. Historical CI issue 14
is closed on both hosts. Seat registration, quality and comorbidity updates were
posted; org registration was delivered in org-bus commit 95e77db.

The deployed independently approved release cae36ee passes **672 tests with zero
skips**, including real configured model calls. Source hashes and scope are in
[RELEASE-VERIFICATION.json](RELEASE-VERIFICATION.json); approval is in
[FRESH-ROUND-16.md](FRESH-ROUND-16.md). It repairs publication of readiness on
completed audit issues and the live evaluation harness. Candidate feature 13
is excluded from this release.

A real four-file audit completed on resonant-gifts at f2cd1ac, producing two
findings and a computed readiness of 77/100. Its existing issue 7 now publishes
that score, verified directly after the deployed reportversion2 refresh.
Forgejo, its automatic GitHub mirror and the runner agree on cae36ee;
CI33944631441 succeeded. The refresh rescanned zero files and raised no model
or gatekeeper failures. The original findings still need quality adjudication.
No organic fix PR has completed: nine attempts remain five nofix, one testfail,
three error. A private 20-finding sample awaits the CEO's adjudication.

The exhaustive-resolution candidate is a local evidence prototype. Independent
round 16 rejected shipment: malformed baseline state can crash, and the
authenticated fix/refresh and forge publication workflows remain absent.
The consecutive clean-round counter remains **0/3**. Round-14 source findings
are preserved in the ledger, without inventing per-finding closure.

Fleet health is not alert-free: the last hourly receipt was 29 ok / 0 errors,
but included unavailable PR diffs and model outages in two repositories.
Tastecheck's then-current access failure was subsequently repaired and retested.
Issue-lane scale proof, pilot fitness and public expansion remain unearned;
GraphQL remains explicitly deferred. Original comment history is preserved by
the source links and hashes in MIGRATION-HISTORY.json; migration copied issue
bodies but did not copy every historical comment.

Delivered tracker receipts: [seat map](https://github.com/KyaniteLabs/.github/issues/63#issuecomment-5549177546),
[quality](https://git.kyanitelabs.tech/KyaniteLabs/fl4write/issues/5#issuecomment-17758),
[handoff](https://git.kyanitelabs.tech/KyaniteLabs/fl4write/issues/3#issuecomment-17760),
[comorbidity](https://git.kyanitelabs.tech/KyaniteLabs/fl4write/issues/3#issuecomment-17763).

## Continuation — 2026-09-05

The CEO directed execution of the prepared delivery steps. Forgejo now has
the original code history at `cc1e486`; local `origin` points to Forgejo and
`github` retains the mirror. Issue bodies migrated with their original
numbers; comment-history completeness is still being checked. The migration
HTTP request timed out, so its return status is not used as completion proof.
The six repairs passed another full run: 650 passed, 3 live-model skips.
Fresh whole-project round-15 recon is running independently. The earlier
authority blocker below is historical; deployment and remaining gates are
in progress. No exhaustive certification is claimed.

## Initial recovery record

The original task list is recovered. Six defect classes are repaired locally
with 45 new regression cases; the full suite passes 650 tests with 3 live
model tests skipped. The prior PM's round 14 is **not closed**, the clean-round
counter remains **0/3**, and these successor repairs are **not deployed**.

## What was recovered and completed

The recovery reconciled the original [PM charter, issue #3](https://github.com/KyaniteLabs/fl4write/issues/3),
PM3-HANDOFF.md, PILOT.md, LEARNINGS.md, BUG-SMELL-REGISTRY.md,
[quality charter #5](https://github.com/KyaniteLabs/fl4write/issues/5),
[scale charter #6](https://github.com/KyaniteLabs/fl4write/issues/6),
[feature request #13](https://github.com/KyaniteLabs/fl4write/issues/13),
and [product map #63](https://github.com/KyaniteLabs/.github/issues/63).

The departed PM had deployed commits b4524e9 and cc1e486 for 39 round-14
findings. The ledger and public updates still ended at round 13. The
[recovered ledger](ROUND-LEDGER.md) preserves that history and all 39 source
findings without inventing a closeout. PM3-HANDOFF.md now points successors
here. A local PM heartbeat, board section and td-0febfb preserve ownership
and the remaining work.

An [independent Sol review](INDEPENDENT-REVIEW.md) rejected the original
round-14 changes. Its five findings, plus a locally reproduced scheduler
defect, produced these repairs:

| Defect | Local repair and behavioral evidence |
|---|---|
| Git diff filenames with spaces were truncated; an internal ` b/` also selected the wrong path | Preserve the complete unquoted path and recognize equal old/new pathname halves; exact source examples pass. |
| Credential-shaped filenames were published as reversible Unicode escapes | Use a one-way digest for their lifecycle key; distinct redacted filenames remain distinct and unchanged findings round-trip without false new/resolved labels. |
| Scheduler accepted a malformed timestamp merely containing `T` | Reuse the state's timezone-aware timestamp validator; malformed auxiliary state returns unknown. |
| Both forge adapters returned filtered malformed PR listings as complete | Count rejected rows on all affected open/merged paths and raise ForgeError; clean-list retry still returns valid siblings. |
| Public config models coerced numeric strings | Enable strict Pydantic validation; numeric strings fail and all 129 current fleet configs still load. |
| Invalid forge URL ports or absent hostnames passed config load | Validate parsed hostname and port at construction, including the model endpoint boundary. |

The source findings' exact probes were reproduced before fixes. The new
regression file also verifies reserved credential namespaces, boolean
boundaries, uncertain comment identity, malformed file-content envelopes,
partial issue pagination, image scrubbing and security-readiness caps.
The old round-7 test that required successful partial enumeration was
updated to the later round-14 fail-closed contract, with clean retry tested.

## Verification and its limits

- Baseline at cc1e486: 605 passed, 3 skipped; lint passed.
- Final local full suite: **650 passed, 3 skipped, zero failures**; 45 added cases.
- All 129 central configs pass the stricter schema; 129 unique repo keys.
- Stored evidence and source hashes: [VERIFICATION.json](VERIFICATION.json).
- The three skipped cases require an explicitly enabled live-model evaluation.
  Offline test success does not establish current model recall or finding quality.
- [Independent repair re-review](REVIEW-FOLLOWUP.md): **APPROVE** for all six
  repair classes. The reviewer ran 44 focused cases and all six exact probes;
  the parent then added its suggested top-level test_timeout regression case.
- CodeGraph was absent and was initialized during recovery. Context-mode tools
  were unavailable; codegraph plus bounded local reads were used. The jcode
  lookup confirmed no pre-existing index for this checkout.

This is a scoped recovery and repair pass. It is not a full fresh-context
audit round, and no claim of 39/39 behavioral closure or exhaustive
certification follows from the passing suite.

## Original task list: verified disposition

| Original obligation | Current result / remaining gate |
|---|---|
| Read original charter, history and map | Completed during recovery. |
| Observe an hourly green cycle | Runner is alive at cc1e486. The 23:02:24Z cycle finished 32 ok / 0 errors, but had a tastecheck adoption alert and one model-unavailable result. This does not satisfy the zero-alert health gate. |
| First completed real fix | No completed organic fix proven. Nine recorded attempts: five nofix, one testfail, three error. Epoch PR #199 is a planted proof PR, closed without merge, not a completed organic fix. |
| First readiness score on a real audit issue | Still unproven. None of 147 current runner state files had omni state or an audit issue reference. Absence of state is not proof that no historical audit ever existed. |
| Weekly 20-finding CEO adjudication | CEO verdict remains required. Historical desk adjudication cannot stand in for that verdict; current quality targets remain unproven. |
| Phase 3 GraphQL | Explicitly deferred by the prior scale decision; not silently promoted into this recovery's scope. Phases 1 and 2 are reported shipped in issue #6. |
| Pilot / fitness gate | The old 14-day clock is labeled superseded in PILOT.md. Fitness is still blocked by finding-quality evidence and the unfinished exhaustive audit, not automatically earned by elapsed time. |
| Issues lane at scale | Contract exists, but none of the 129 central configs enables the lane. Volume behavior has not been demonstrated; do not call it deployed at scale. |
| Tracker hygiene: #1, #2, #7 and #6 | Already completed by the prior PM: #1/#2/#7 are closed; #6 has the phase update. Issue #14 flags a historical failing SHA; current production CI is green, so a closure update is prepared but not posted. |
| Duplicate gifts/tastecheck configs | Already resolved. Current central repo keys are unique; gifts and tastecheck target different repositories. Hidden self-adoption config is not part of the runner's central glob. |
| Self-review cycle | Current runner scanned FL4WRITE without error; existing list-response regression tests pass. A new live review-and-fix result has not been manufactured or claimed. |
| Comorbidity record | [COMORBIDITY.md](COMORBIDITY.md) records mechanisms, predictions, probes and counterevidence. |
| PM seat-taking and quality updates on #63/#5/#3 | Reviewable text is prepared in TRACKER-UPDATES.md. No external messages were sent. |
| Round-14 closeout, then three fresh full green rounds | Original findings recovered; six repair classes verified locally. Complete per-finding closure and three full fresh-context rounds remain outstanding. Counter 0/3. |
| Implement exhaustive-loop product behavior, issue #13 | Still a specification, not implemented. It remains a separate feature tranche requiring its own acceptance tests, quorum review, dogfood proof and rollout gate. |
| Open-source/public expansion | Not approved by this recovery; fitness, secret review and authority-host landing gates remain. |

## Production and authority blockers

1. **Authority-host landing is unresolved.** This checkout and runner use the
   GitHub remote. The Forgejo API and git lookup for KyaniteLabs/fl4write
   return not found; an accessible Forgejo search returned no match. This
   could mean absent repository or insufficient access. The rule requiring
   Forgejo-first landing cannot be satisfied by assuming GitHub is canonical.
   No remote was changed and no repository was created.
2. **tastecheck adoption is missing on both queried hosts.** Its Forgejo
   repository exists, but the adoption-file query fails; GitHub returns 404
   for the adoption file. Its current central config still points to GitHub.
   Re-adoption needs a deliberate canonical-host choice and contents-on-main
   verification; repeating the previous GitHub-only restoration would not
   resolve the authority mismatch.
3. **Current model results are degraded.** The latest recorded failures include
   timeouts and truncated responses. Today's model-call stream has 75 records:
   27 explicit successes, 13 explicit failures, and 35 records without `ok`.
   These are records, not a deduplicated call-success denominator. Model
   routing and credentials were not changed.

The next delivery action is to resolve FL4WRITE's authority host, then land
the reviewed local repairs there and verify the single runner pulls that
exact change. The remaining engineering and CEO gates above must retain
their owners and evidence; none is closed by this report.
