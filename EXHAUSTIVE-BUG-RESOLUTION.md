# EXHAUSTIVE BUG-RESOLUTION LOOP — requested FL4WRITE behavior

**Status: feature request (CEO word 2026-09-04, PM-3 intake) — behavior spec, not yet
implemented. Implementation = feature tranche; per standing authority #2 it ships only after a
delegate quorum audit, and per org habit every defect found while building it lands a regression
pin + LEARNINGS entry.**

- Origin: CEO chat, 2026-09-04 (FL4WRITE PM-3 session), before the MECE gauntlet resumed.
- The same pattern lives in org rules: workspace `AGENTS.md` § EXHAUSTIVE BUG-RESOLUTION LOOP
  PATTERN (org-wide rule surface); law-pack changelog entry pending via COO.
- Tracker: KyaniteLabs/fl4write issue #13.
- This loop is the identical contract the 2026-09 MECE gauntlet runs on FL4WRITE itself
  (3 consecutive zero-new full rounds) — the product behavior must be dogfooded on its own repo
  before it is trusted on others.

## What the CEO asked (verbatim, lightly cleaned)

> This is a pattern — an exhaustive bug resolution pattern. Loop one: reconnaissance (detect
> bugs), then fix, then refresh everything, take note of what you did, REFRESH CONTEXT WINDOW,
> then go again — try to find as many bugs as possible, then fix, then refresh everything, take
> note of what you did, then new context window again, etc. The loop continues until at least
> 3 100% green loops with zero regressions. The loop will fully exhaustively flush out and fix
> all bugs from a "finished" or closed-to-finished project. — It is a type of behavior expected
> out of FL4WRITE when deemed necessary or requested.

## The loop contract (canonical)

**ROUND = recon → fix → refresh → note → fresh context.**

1. **RECON (detect bugs)** — fresh-eyes, exhaustive adversarial pass over the WHOLE project at
   current HEAD. Find as many real bugs as possible. Every finding must carry evidence
   (file:line or verbatim quote of the reviewed bytes); uncited findings are discarded.
   Recon runs in a NEW context window every round — no long-context session loops on itself.
2. **FIX** — every valid finding is fixed with a regression pin; the full verification suite must
   be 100% green afterwards; zero regressions vs the previous round.
3. **REFRESH EVERYTHING** — subjects, packs, fixtures, state and artifacts are re-generated from
   the post-fix HEAD. Auditing a stale tree re-opens already-fixed items and hides new ones.
4. **NOTE** — what this round did (findings, fixes, pins, verdicts) is appended to the persistent
   round ledger. The ledger is the only thing that crosses rounds.
5. **FRESH CONTEXT** — next round starts from the ledger, not from this round's context.

**EXIT CONTRACT — three consecutive green loops.** A round is GREEN iff:

- recon produced ZERO new valid defects (desk-verified; dup/invalid verdicts recorded), AND
- the full suite runs 100% green at the round's HEAD (evidence stored — junit/run logs — not
  prose), AND
- zero regressions against the previous round's green baseline (every test that passed before
  still passes).

Any round that finds new valid defects, or regresses the suite, resets the consecutive-green
counter to 0 (after its fixes land). The loop ends only when the counter reaches 3 — then the
project may be certified **exhaustively flushed @ `<sha>`**, with the ledger as evidence.
Never declare exhaustion early; exhaustion is a certification, not a feeling.

**Why:** round-N reviewers are structurally blind to round-N bugs; every fix round can introduce
new bugs; only fresh-eyes re-entry plus a hard 3-clean-rounds bar reliably exhausts a codebase.

## When FL4WRITE engages it ("deemed necessary or requested")

Requested (explicit): a human asks for an exhaustive flush on a repo — via per-repo central
config, issue, or command (surface decided at implementation). Default OFF.

Deemed necessary (automatic): to be defined at implementation, candidates only —
repo reaches a finished/closed-to-finished marker (release gate, PILOT-style graduation, a
"done" claim on a tracked deliverable, gauntlet-final-layer verdict needing a flush), or an
omnisweep/retro closeout finds the repo eligible. Automatic triggers stay conservative and are
never guessed from prose alone.

## Product shape of one round (mapping onto existing machinery)

| Pattern step | Existing machinery | Notes |
|---|---|---|
| RECON (whole tree, fresh context) | omnisweep-semantics full-tree scan at HEAD + analyzer + gatekeeper + scrub/render containment | each round = new engine invocation / fresh model session; round notes are the only carry-over; freshness gate applies (no zombie findings on moved code) |
| FIX | fix lane (own PRs only; fork rail comment-only) | per-finding stable-id PRs or contained patches, as omnisweep fix phase does; Critical/Major floor configurable |
| Green evidence | verify-tests with junit aggregation (`test_cmd`, aggregated testsuites) | full-suite run, not diff-only: this is an exhaustion loop, its gate is the whole suite |
| REFRESH | re-generate round packs from post-fix HEAD; reload state | stale-subject discipline, like the gauntlet's refresh-packs |
| NOTE | round ledger appended to the per-repo audit issue (edited in place) + state + telemetry | ledger survives, context does not |
| Counters | per-repo state: round number, consecutive-green, green-baseline SHA + junit evidence refs | int-normalized persistence (retro_seen lesson) |
| Certification | final audit-issue edit: "exhaustively flushed @ sha" + ledger + evidence refs; telemetry event | human-visible artifact on the repo |

## Defensive constraints (must survive this repo's own gauntlet before shipping)

- **Evidence, not prose**: a green round requires stored run evidence (aggregated junit / logs).
  No evidence ⇒ round is NOT green.
- **Outage ≠ green**: forge/model/runner failure defers the round; a truncated or failed round
  never counts as recon-complete and never counts green. Counter untouched on deferral.
- **Shape containment** at every adapter boundary (forge rows, junit XML, ledger state) — a
  malformed artifact degrades the round, never crashes the loop or fakes a verdict.
- **Bounded loop**: hard per-repo round cap + spend bounds per round (model budget like
  omnisweep's max_*); cap exceeded ⇒ escalate to an issue with the ledger attached, never
  silently stop. Loop must not become a permanent cost drain on a repo that will not flush.
- **Per-repo isolation**: one repo's loop (or its failure) never affects other repos' cycles.
- **Fresh context is structural**: rounds MUST be new contexts over the ledger; a config that
  lets one long session "loop" is a violation of the pattern, not an implementation of it.
- **Exit discipline**: certification only at 3 consecutive green; any new-valid-defect or
  regression round resets to 0. The 3-green bar is the whole point.

## Acceptance criteria (definition of done for the tranche)

1. A repo can be put into exhaustive-loop mode by request (config/command/issue), default off,
   and the trigger is documented.
2. Each round runs recon→fix→refresh→note on a fresh context with the ledger crossing rounds;
   round packs come from the post-fix HEAD.
3. Full-suite evidence gates each round; deferral on outage; truncated rounds never count.
4. Consecutive-green counter persists, resets on any non-green round, survives crashes/restarts,
   and certification fires exactly at 3 with a ledger + evidence artifact on the repo.
5. Bounds, escalation, per-repo isolation and containment all have regression pins.
6. Quorum delegate audit (fresh-context reviewer, standing authority #2) passes before any
   fleet enablement; the tranche itself survived the exhaustive loop on fl4write's own repo.

## Open questions at intake (decide at implementation, record rulings on the issue)

- Trigger surface: config flag vs issue command vs both; who may request.
- Automatic "deemed necessary" markers — which, if any, ship in v1.
- Round/loop caps, spend bounds, severity floor for the fix phase.
- Certification surface (audit issue state, comment, telemetry event schema).
- Interaction with tier scheduling on the runner (exhaustive loops are bursty by nature).
