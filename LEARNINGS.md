
> **Rename 2026-09-01:** `codesitter` → **Fl4wRite** (`fl4write`). Historical entries below keep the old name; the old marker `codesitter:v1:` is still RECOGNIZED by lookups so pre-rename comments are never duplicated.

# codesitter learnings (each paid for on 2026-08-31, build day)

1. **Marker-substring identity is hijackable.** Any commenter can write your marker; persistent-comment lookup must verify author == bot identity. (Review gate, runtime-verified.)
2. **Shadow state poisons cutover.** Shadow outcomes must never count as reviewed, or the live flip no-ops forever. Distinct outcome keys; the predicate treats them as unreviewed.
3. **Vacuous grounding celebrates over Criticals.** A missing diff fetcher defaulting to `set()` drops every finding and posts 🎉 while reporting success. Required parameters beat defaults for correctness-critical inputs.
4. **Mirrors are optimizations, never dependencies.** An unreachable mirror must degrade (log+skip), not abort the primary cycle. Caught by the first live smoke run.
5. **Model prose is not JSON.** "I cannot comply" crashes json.loads outside the ModelUnavailable path — contain parse failures per-PR, never lose the whole cycle's state.
6. **Delta keys must use the real rule id.** Reconstructing prior findings with a hardcoded rule mints 🆕 on every cycle for every configured-rule finding.
7. **reasoning_effort: max burns completion budget on hidden reasoning** (DeepSeek-V4-Flash-0731): ≥8000 max_tokens or accept medium. (Landscape lane A.)
8. **Harness automations pause on prompt edit** — a safety gate with no API bypass; deployment plans must budget the one enable-click.
9. **Edit-in-place never re-notifies** (Codecov law, corpus-confirmed) — the persistent-comment law exists because notifications, not content, are the spam surface.
10. **Tone is delivery, not detection** (Kilo roast mode evidence) — renderer-only presets keep the analyzer honest and forks safe.
11. **A merged adoption can be silently lost to a racing branch.** Innerscape #304 merged clean — then a branch based on older main landed on top and main reverted to .coderabbit.yaml-only. Lesson: verify the artifact ON MAIN after every adoption merge (contents API), not just the merge event; re-adopt on current main if lost (#305).
12. **App removal is NOT cosmetic.** CodeRabbit still posts default walkthroughs after .coderabbit.yaml removal — the app must be uninstalled (settings UI) or it keeps reviewing alongside codesitter (seen live on the kinocut inaugural).
13. **PR-head propagation lags seconds after a push** — a cycle run immediately post-push sees the old SHA and correctly skips; the head-SHA predicate self-heals on the next cycle (designed behavior, verified live).
14. **bot_login must equal the posting account.** The hijack-defense author check with a mismatched default rejects OUR OWN persistent comment → double-post. Configurable now, wired to adapters.
15. **Inaugural proof (live, kinocut #503):** all three paths verified in production — 🎉 celebration (clean diff), grounded Critical finding (planted token → rule `secrets` + proposal), edit-in-place on re-review (one comment, updated with 🆕).
16. **Active repos eat adoptions twice.** Elixis (#149) lost its config to a racing branch exactly like Innerscape (#304) — verify-once is insufficient while branches are in flight. Countermeasure: the runner now verifies in-repo config presence on main EVERY cycle and alerts on loss.

## 17. One state owner per cycle (the email storm, 2026-09-01)
The engine loads state at cycle start; the issues lane did its OWN load+save
mid-cycle; the engine's end-of-cycle save then overwrote the file from its
stale in-memory copy — wiping `last_triaged_number` EVERY cycle. Combined
with a bot_login identity mismatch (posting as kyanitelabs[bot], checking for
simongonzalezdc), every run re-triaged every open issue as a NEW comment:
maintainers got the same triage email 3–4× (237 duplicate comments deleted
across 15 repos). Fix: lanes mutate the engine-owned dict; ONE save. Plus a
marker-under-any-identity guard: never post a second copy, skip + log.
**Law: any module that persists state must receive the shared state dict, never
its own load/save pair.**

## 18. Renames need diff review, not grep-and-pray
The line-filtered codesitter→fl4write sweep protected the marker literals but
silently rewrote a URL string — the surveillance fallback probe ended up
checking `.fl4write.yaml` twice, printing a spurious "adoption lost" alert for
every repo. Grep for the old name AFTER a sweep and eyeball every remaining
hit; a "protected literals" list protects literals, not identifiers-in-strings.

## 19. Identity follows the token, or edit-in-place dies
bot_login must match the identity the token posts AS. With per-repo app
installations the poster is kyanitelabs[bot]; a hardcoded personal login makes
every "find my comment" lookup miss → new comment instead of edit → email.
bot_login is now derived from the auth route (app=bot, PAT fallback=user).

## 20. Renaming a GitHub App changes the bot login (2026-09-01)
CEO renamed the app kyanitelabs → "Fl4wRite"; the SLUG followed, so the
posting identity changed kyanitelabs[bot] → fl4write[bot] — while every
identity check in the codebase still expected the old login. That is the
email-storm failure mode reborn, caught only because "verify the CEO's
clicks via GET /app" was run instead of taking the confirmation at face
value. Fix: bot_login defaults follow the current slug; comments authored
under legacy slugs are recognized as ours (is_own_identity).
**Law: after ANY app-settings change, re-fetch /app and diff name, slug, and
avatar — the slug is identity.**

## 21. Ruleset repos reject direct contents-PUT with 409 (2026-09-01)
8 of 31 repos return "Repository rule violations found — Changes must be
made through a pull request" on contents PUT (409, not 403). Branch+PR+merge
is the route; research-scout additionally allows ONLY squash merges (merge
PUT 405s with "Merge commits are not allowed"). Also: never pin branch=main
on contents calls — several repos default to master (404).

## 22. .bashrc is invisible to cron and SSH (and its values may be quoted)
Non-interactive shells never reach ~/.bashrc exports (Ubuntu early-return),
so cron-run processes see no model key — and the .bashrc value can be
wrapped in literal double quotes, which survive `cut -d= -f2-` and 401 the
Authorization header. Extract with quote-stripping inside the runner script
itself (run-cycle.sh carries this, host-guarded).

## 23. Before asking the CEO to click, query what is observable (2026-09-01)
"Install the app on your user account" turned out to be already-installed
since May — the real bug was a hardcoded org installation ID. GitHub App
state is fully observable via GET /app/installations with the app JWT.
**Law: a click request is a last resort; every checkable claim gets checked
first.**

## 24. The hourly poller structurally misses fast-merged PRs (2026-09-01)
Evidence from the first real PR flow (the CEO's Wave-2/2b docs sweep): PRs open
and merge in ~60 seconds (tastecheck #19: created 00:24, merged 00:25); some
wave merges never appear as GitHub PRs at all (Forgel-side/agent merges pushed
to main). An hourly poll that only sees OPEN PRs reviews none of them. In this
org, agent-driven fast-merge IS the normal PR flow — so the v1 polling trigger
reviews almost nothing real. Mitigations: (a) post-merge review mode (review
PRs merged since the last watermark; findings land as post-merge comments,
fixes ride follow-up PRs); (b) the chartered v2 event trigger (webhook via the
app — permissions already granted). Also: 8 repos lost configs to the same
sweep (stale-based merges landing on main — LEARNINGS class #16/#18): sweep
tooling MUST rebase onto fresh main before landing.

## 25. The six-lane audit: error paths downgrade to success-shaped data (2026-09-01)
CEO-ordered MECE adversarial audit (state/security/API/LLM/config/ops lanes,
~60 findings, 13 Critical). The dominant systemic pattern: FAILURE PATHS
SILENTLY PRODUCE THE SAME SHAPE AS SUCCESS — a failed diff fetch returned
the empty set (posted a celebration over real findings, marked reviewed
forever); a >1MB file fetched as "" let the model fabricate a whole file;
an empty gatekeeper keep-list dropped every finding and posted "clean";
git clone -b HEAD failed so the fix lane had never once worked (and had it
worked, would have silently reverted main — default-branch tree + PR-head
content). Second pattern: THREE MODULES DISAGREED ABOUT THE COMMENT FORMAT
(renderer emitted one shape, engine and metrics parsed a legacy one) — which
alone killed delta markers, resolution tracking, AND the acceptance metric.
Third: the fail-open/containment contracts were honored only in the analyzer
— the gatekeeper's narrow except tuple crashed whole cycles on routine 429s.
Laws: (a) every error path must return a shape that CANNOT be mistaken for
success (None, an exception, a sentinel the caller must handle); (b) one
source of truth for any serialized format, with a round-trip test; (c)
"fail-open" means except Exception or it isn't; (d) a knob wired to nothing
is worse than no knob (extra=forbid + dead-knob wiring). Also: set -u
demands ${VAR:-} — the hardened runner was itself killed by an unbound
variable on its first deploy. 102 tests (was 50), one per critical class.


## 26. "Did you fix EVERYTHING?" is itself a test (2026-09-01)
After the six-lane audit's fix pass (102 tests green, deployed), the CEO asked
whether every single finding was fixed. Re-auditing the claim against the six
lane reports found EIGHT more fixable residuals (merge-gate rejecting legacy
identities, metrics reactions calling a method that didn't exist, the README
still saying "Formerly Fl4wRite", dead params, missing module tests...). The
fix pass had closed the criticals so cleanly that the long tail felt done.
**Law: a completeness claim is only as good as a line-by-line recheck against
the source list — 'all tests green' verifies the fixes you MADE, not the
findings you MISSED. Remaining opens must be an explicit, documented decision
list, never silence.**

## 27. Lint/tool contracts must be explicit — defaults drift with versions (2026-09-01)
PM-1's final commit passed "ruff clean" locally (0.15.8) and FAILED CI
(0.16.5): ruff widened its default rule set between minor versions, so the
same code was clean under one implicit contract and 38-errors dirty under
another. The failure sat red on main because local runs could not see it.
Same class as the dead-knob law: an implicit contract is a contract nobody
signed. **Law: any tool whose config selects nothing has selected
"whatever this version defaults to" — pin the rule set (or equivalent
contract) explicitly, and verify with the EXACT version CI runs (a venv
install; `pip install` on macOS refuses via PEP 668 and silently leaves the
old binary in place, which once made a 'verified under CI's version' check a
no-op).** Corollary: "green locally" is a claim about YOUR versions; CI is
the only authority on CI's versions.

## 28. Stale implicit contracts strike on every new forge surface (2026-09-01)
Three same-day repeats of old laws on Forgejo: the CF-fronted forge showed
GET-passes/POST-fails (error-shapes-must-differ, #25's class), master-default
repos rejected implicit-branch contents writes (#21's twin), and the "no
admin token" conclusion dissolved once the ssh config's full host list was
read — the origin was the VPS, with a container CLI that creates users
without any API token. **Law: porting a working system to a new surface
re-runs its whole incident history — before building, enumerate the new
surface's own versions of every law already learned; before declaring an
action blocked, enumerate every host AND CLI you can already reach.**

## 29. The author is structurally blind — delegate audits are load-bearing (2026-09-02)
Two fresh reviewers (GLM-5.3-max subagent; gpt-5.6-sol via codex) found 2
Critical + 7 Major in a batch its author had already passed five times —
including a token file sitting INSIDE the test sandbox and a counter that
had never counted since deploy. Then the CEO's completeness check ("did you
fix EVERY finding?") exposed SIX unfixed items behind the author's own
"all fixed" — LEARNINGS #26 repeating on the author himself. **Law: every
feature tranche ships with one fresh-context delegate audit BEFORE deploy
(third-reviewer class; quorum: MiniMax-M3 + Sol + mimo-v2.5-pro); a
completeness claim by the author is a hypothesis, checked line-by-line
against the source list, never a report.**
## 30. Prompts do not catch self-failing diffs — RUN them (2026-09-02)
Both MiniMax-M3 and deepseek gave a planted, test-failing diff a clean
review — TWICE EACH — including once with an explicit tests-are-the-spec
prompt contract. The fix was structural, not rhetorical: verify_diff_tests
executes the diff's own tests in the sandboxed worktree; a failing diff is
a deterministic Critical that the gatekeeper cannot drop and the fix lane
cannot auto-patch (it anchors at the TEST — test-weakening is one lane
away). The planted-bug corpus (tests/test_planted_diffs.py) is the standing
Q1 instrument: deterministic layer 100% by construction, model recall
measured live. **Law: when a deterministic check is possible, prompt
harder second — and the eval corpus grows from every production miss.**

## 31. Capability rules must be DEPLOYED, not just defined (2026-09-02)
The CheckYourself integration defined 19 capability rules in capabilities.py
but shipped without wiring them into config loading. The grounding gate
(analyzer rule_id must exist in config.review) would have dropped every
capability-citing finding. Both non-GLM auditors (Sol + M3) caught it
independently — the author had written the rules, tested the scoring, and
assumed deployment. **Law: a new rule/schema/feature must be verified LIVE
against the production grounding/config path before the commit message says
'ships' — definition without deployment is a dead knob (LEARNINGS #25d
reborn).**
## 32. The fix-pass needs the same verification bar as the bug it fixes (2026-09-02)
An indentation error in the list-response guard broke 28 tests. The guard
was correct logic at wrong indentation — Python's syntax caught it, but
only because the test suite imports executor.py at collection time.
Without the suite, the fix would have shipped broken and taken down the
ci_watch lane on the next cycle. **Corollary to LEARNINGS #25: a fix's
test run IS the verification — but only if the test suite exercises the
fixed path. The ultraqa gauntlet caught this because baseline
verification (step 2) runs the suite FIRST.**

## 33. Desks transfer by retirement, never by parallel operation (2026-09-02)
The ZCode→DSH migration's failure mode was never the new desk — it was
two desks alive at once: duplicate tracker posts, conflicting reviews,
racing commits on shared state. Same failure class as a two-host runner:
the automation layer is platform-agnostic; the judgment layer is
single-occupant. The transfer instrument was one self-contained prompt
(PM3-HANDOFF.md) carrying verified state numbers, standing authorities,
traps, prioritized open loops, and the access map — deliberately
sufficient WITHOUT the old desk's session memory. The old desk's last act
was proving it holds nothing open: no crons, no background workers,
clean tree, everything pushed. **Law: moving an agent desk across
platforms = retire-then-spawn; the handoff prompt must be the only
dependency, and retirement is not complete until the old side's write
paths are provably closed.**

## 34. Config and adoption identity follows the forge of truth (2026-09-03)
PM-3's first session found two live defect classes in the fleet's config layer.
(a) Six dual-homed org repos (kinocut, Epoch, Innerscape, checkyourself,
devarch-framework, Elixis) carried TWO central configs naming the same repo
key (X + X.fj after the Sep-2 Forgejo sweep). The loader dedupes by repo key:
one config cycles (alphabetically first — the .fj), the other shadows forever
and ALERTs every cycle (18 cycles of noise, ~6 lines each). With the CEO's
all-FJ order the Forgejo side IS the live review surface (open FJ PR queues
on kinocut/Epoch/Innerscape, reviewed by the .fj configs; ZERO GitHub PR
merges on any of the six since Sep 2) — the GitHub configs were wave-1 era
shadow configs and were retired. (b) Adoption losses: tastecheck + complyos
lost their in-repo .fl4write.yaml to force-land sweeps landing on main
(racing-branch law, mirror form — the sweep carries a stale tree), and
resonant-constable + resonant-context-kit were armed 09-03 with no in-repo
adoption at all. Both classes ALERTed every cycle. Also caught: 671eb01
removed the wrong-target resonant-gifts CENTRAL config, but the same
wrong-target content (repo: resonant-tastecheck, floor route) still lived
INSIDE simongonzalezdc/resonant-gifts — and it contaminated my first
adoption template before self-correction (every adoption must mirror the
target repo's own central config). **Law: config + adoption identity follows
the forge of truth — one central config per repo, on the forge where its PRs
merge; an adoption survives only while every lander (PR, push, or force-land)
carries it — sweep force-lands cut from stale bases eat it (racing-branch
law; mirror-synced copies track the forge of truth and survive, verified on
the six org repos); every adoption carries the repo's OWN central config
content and is verified contents-on-branch after landing.** Fleet: 152→146 central configs; repo-key
uniqueness pinned by tests/test_fleet_configs.py (the loader cannot cycle
two configs for one repo — duplicate keys are shadowed, never run).

## 35. macOS case-insensitivity hides fixture-path drift from CI (2026-09-03)
CI on main was RED from 2026-09-02 17:12 UTC for ~10 hours - every push failed
test_forgejo_warm_floor while local runs stayed green, so the 'CI green'
handoff claim (measured on the laptop, not the runner) was stale by the time
PM-3 sat down. Root cause: the test wrote its fixture as
simon__cncl.state.json while _state_path('simon/CNCL') builds
simon__CNCL.state.json - on macOS's case-insensitive APFS the read
succeeds and the test passes; on Linux CI the file does not exist and the
classifier took the bootstrap path (hot != warm). The tiers tranche added the
failing test; every commit since (the ultraqa fixes, LEARNINGS #31/32 docs,
the PM-3 handoff, PM-2's close-out) sat red unseen. The own-repo ci_watch
WORKED (ci_red=1 every cycle since 23:00, escalation issues #9-#11 on
KyaniteLabs/fl4write, fix attempts failed Linux verification) - the missing
piece was a human reading gh run list. **Law: a test that writes files must
build their paths with the SAME code the production path uses (hand-typed
fixture filenames are a contract nobody signed - LEARNINGS #27's class on a
new surface: filesystem case semantics); 'CI green' is a claim about the CI
runner - read gh run list, never local pytest.** Fix: fixture written via
tiers._state_path, pinned by construction.

## 36. CI run-level annotations are meta, not code findings (2026-09-03)
ci_watch minted Major findings from EVERY check annotation - and GitHub Actions
emits run-level auto-annotations anchored at the WORKFLOW DIRECTORY (path
'.github', lines = workflow YAML lines: 'Node.js 20 is deprecated', 'Process
completed with exit code 1.'). The fix lane then correctly refused to fetch a
directory (executor._get_file_content returns None for list responses - the
f1088e3 guard), so every red head burned a fix attempt on '.github' and
escalated. Root cause: ci_watch assumed annotation.path == source file; GH
violates that for run-level annotations. **Law: any CI-annotation surface must
mint findings only for paths that are FILES at the relevant ref - an HTTP 200
from the contents API is not a file (directories answer with a list); the
forge adapter's path_is_file() is the one truth, fail-open on None.** Fixed:
adapter path_is_file(repo, path, ref) + mint-time filter in _ci_watch_step + 3
regression tests.


## 37. A wedged agent session is recoverable — and expensive to abandon (2026-09-03)
The PM-3 DSH session wedged three ways in one day: a deepseek-lane 502 queue-full
(07:46Z-cycle end), a model request that never returned (~5h20m, 08:29-13:51), and
then ~70 minutes of tool-call emission failures (`unknown tool ""` — empty tool
names on larger calls, small calls fine) that blocked landing the UltraQA
adversarial test pass (turns 9-11, aborted by the CEO at 14:01 and 15:00). The
in-flight work survived ONLY because the harness records every streamed tool-call
argument in the session transcript (`~/.dsh/sessions/<ws>/session-<id>/session.jsonl.zstd`,
10.6k events, 8MB) — the full intended test suite was reconstructed byte-for-byte
from the recorded attempts and landed green in a fresh session. **Law: significant
multi-step changes land in the repo at each green step, never as one pending
giant append; when a lane misbehaves (queue-full, wedged request, empty tool
names), stop burning turns — switch the route and keep tool calls small, then
recover the in-flight payloads from the session JSONL.** Rescue path proven
2026-09-03: decompress the zstd transcript, extract `tool/call` + `assistant/message`
tool-call arguments, diff the successive attempts, land the latest complete draft.

## 38. Posted severity is not finding quality — adjudication is the instrument (2026-09-03)
The Q1 proxy (posted Critical+Major share as "finding quality") was wrong: a severity label is
the MODEL's claim, not a verdict. First desk adjudication round (CTO + CS consults,
council-consult-2026-09-03-fl4write-quality, code at the reviewed SHAs): of 23 posted findings
on liminal post-merge reviews, **8 FALSE incl. 7 of 10 Criticals** — bodies said "tests pass /
no issue / assertion is correct" then posted Critical, or cited test content that does not
exist in the file (HTML-escaped markup fabricated from an unread test file). Honest quality
~9-30% vs the 55-85% proxy: **3-6x overstated**. Mechanisms: L1-B1 counted any message
containing "test" as verified (has_test = "test" in low); the self-contradiction guard scanned
only message[:120] for 3 phrases; and testing-quality Criticals never met the rubric's own bar
(verifiable failing diff test). **Law: severity-integrity gates are deterministic, not
prompts; Q1 = adjudicated REAL share from desk rounds; every posted C/M passes the
contradiction gate and the testing-quality ceiling.** Fixed: L1-B4 full-message
self-contradiction gate + L1-B5 testing-quality Critical ceiling (test_cmd-gated) + 12
regression tests pinning the sample escapes. The adjudication ALSO found the bot under-posts:
PR #1119's tempo shim rides addInitScript, which never runs for setContent pages — the crash
it claims to fix persists (missed-defect evidence, filed on the PR). Phase 2: citation
grounding — findings must quote the reviewed SHA's actual bytes (fabricated-premise class).

## 39. Speculative-security Criticals need code reading, not phrase gates (2026-09-03)
Sample residue after the L1-B4/L1-B5 tranche: two security-threat Criticals (items 13, 19 —
XSS-on-static-prepend, "prototype pollution" on a hardcoded shim list) survive every text
gate because their hedged conditionals ("could be exploited if the content is malicious /
if an attacker can influence…") are indistinguishable by text from the sample's REAL
security findings (items 17, 18 — same hedges, but the content IS user-uploaded playables
under --no-sandbox). The discriminator was domain knowledge of the trust boundary, which
deterministic message filters cannot encode. **Law: severity-integrity gates are necessary
but not sufficient — speculative-security Criticals require either citation grounding
(findings quote the reviewed bytes) or a Critical-only verification pass; until then their
survival is a tracked residue, not a closed class.** Sample effect: of the 10 posted
Criticals, 4 dropped + 4 floored to Major by the tranche; 2 (13, 19) remain as documented
residue for phase 2.

## 40. Text gates are whack-a-mole; grounding is the cure (2026-09-03, UltraQA round 1)
The readiness gauntlet (CEO: "FL4WRITE is NOT ready for use") ran the full adversarial
battery over the calibration tranche and the pipeline. New escapes found and fixed: (a) five
more self-refuting terminal phrases ("this is fine", "the diff is clean and safe to merge",
"tests all pass", "nothing wrong", "everything checks out") — every phrase list grows a
round behind the generator; (b) "the tests FAIL TO COVER the branch" bypassed the
failure-claim gate (coverage wording, not a failure); (c) a valid-JSON state file of the
wrong shape (list/str/int) crashed the whole cycle instead of bounded-reconciling;
(d) scrubbed finding text could still mint fake finding headings in the posted comment
(markdown structure is not a scrub class); (e) newline-bearing messages could break bullets
in escalation/issue bodies (engine, executor, fixlane — now single-lined via scrub.inline).
**Law: deterministic text filters are necessary but not sufficient — severity claims need
GROUNDING (cite the reviewed-SHA bytes; run the diff's tests when claiming they fail), and
every untrusted-text render site must be single-line/inert by construction.** Residue,
documented: speculative-security Criticals (hedged "could be exploited if…" on static code)
are text-indistinguishable from the real hedged findings — phase-2 citation grounding or a
Critical-only verification pass closes them (LEARNINGS #39). 357 tests green after the round.

## 41. Forge adapters are an untrusted input surface like everything else (2026-09-03, UltraQA round 2)
Round 2 of the readiness gauntlet: every adapter boundary must contain SHAPE errors, not
just ForgeError (HTTP): list_open_prs/merged rows missing fields, garbage rows, malformed
persistent-comment tuples, non-numeric annotation lines — any of them crashed the whole
cycle before the fix. Same law as round 1 in new clothes (assumed contract shape, LEARNINGS
#40): valid-JSON-wrong-shape state, forge rows of the wrong shape, CI annotation text
bypassing the analyzer scrub — all external surfaces need containment + scrubbing at THEIR
boundary, not downstream. Fixes: envelope ambiguity (a second DISTINCT {"fixed_content"} in
one model response refuses to parse — identical duplicates parse), adapter row guards +
shape-error tuples at open/merged listing, acceptance, comment-signals and retro sites,
ci_watch annotation scrub + line hardening, structural raw-HTML scrub (h1-h6/tables/divs),
fix-PR proposal heading-escape, testing-quality "fail to adequately cover" wording. Sol
audit round 2: GO-WITH-CHANGES, all 5 items closed with regression pins. 374 tests green.

## 42. Test gates need execution evidence, not exit codes (2026-09-03, UltraQA round 3)
Comorbidity #9's top predictions all CONFIRMED by probes: (P1) adapter shape errors crashed
cycles at post-merge listing, omnisweep tree shape/rows, issues-lane rows, ci_watch check-run
fields (numeric name, dict conclusion = unhashable against the benign set, numeric summary);
(P4) the fix-lane test gate was gameable — a hostile "fix" calling os._exit(0) at import time
kills pytest with rc 0 before any test runs, a false green that would push a process-killing
patch as a fix PR (sys.exit is caught by pytest; os._exit is not). Fix: _test_run_evidence —
green requires execution evidence: non-empty output (os._exit skips all flushing) and a
pytest summary line for pytest cmds; the verifier turns no-evidence rc-0 into a Critical
"UNVERIFIED" finding instead of a clean verdict. **Law: exit codes are a promise, output is
evidence — any auto-landing gate on a code-executing step (fix lane, verifier, CI-mimic) must
require both.** Sol audit round 3 (GO-WITH-CHANGES) hardened further: output TEXT is forgeable
too (flush a fake summary then os._exit(0)) — pytest gates now require a host-controlled
--junitxml artifact as COMPLETION evidence (tests>0, failures=0, errors=0). Honest
boundary (MECE round-1 F1-002/round-2 F2-005): the path is argv-visible to the same-user
test process, so a DETERMINED in-process adversary can forge it — the artifact defeats
accidental-kill and flush-then-exit classes; OS privilege separation is the real cure, and NON-pytest runners FAIL CLOSED on the fix gate until a per-runner evidence
mapping lands (fix lane: GitHub-only v1, zero landed fixes — blocking is free; the organic-PR
verifier keeps rc-based verdicts for non-pytest, silent-exit labeled unproven). 384 tests green.

## 43. The exhaustive loop is the instrument (2026-09-04, MECE round 1)
CEO protocol correction: a gauntlet is not exhaustive until FRESH-EYES members of a diverse
MECE team, re-auditing each round with a findings ledger, produce ZERO new valid findings on
THREE CONSECUTIVE full rounds. Round 1 (terra/luna/M3/sol/glm over 5 MECE domains) proved the
single-observer rounds 1-4 of the readiness pass were NOT exhaustive: it found 33 findings
incl. a CRITICAL the earlier pass shipped (executed test code could read ~/.sinter/config.json
= every org key via the sandbox HOME) and majors that invalidated shipped claims (junit
"host-controlled" evidence was argv-visible to the same-user process; Forgejo pagination used
per_page which the server ignores, silently capping every FJ list; the readiness
missing-evidence cap was inert code; check-runs merge gate unpaginated; issues triage failures
skipped forever). 28/33 fixed or ruled-by-design in round 1 across 7 commits; 5 open minors
queued. Law: product gates (fix lane, merge, posting) need fresh-eyes MECE re-audit rounds to
claim readiness; the earlier "battery complete" wording was withdrawn on the record.

## 44. Regression pins are host-independent or they are not pins (2026-09-04, MECE round 4)
Two round-3 regression pins opened the reviewed source via a HARDCODED MAC-LOCAL absolute path
(/Users/simongonzalezdecruz/workspaces/fl4write/...). Green on this laptop; CI red on EVERY
push from ~01:52Z (FileNotFoundError on the Ubuntu runner) until the bot's own ci_watch lane
filed fl4write #12 — a red stretch during which the README still claimed "CI on every push":
the honest-status rule means re-checking the CI badge, not the local suite, before quoting it.
Law: tests resolve repo paths from the test file (Path(__file__).resolve().parent.parent) —
author/machine-specific absolutes are host-contaminated claims; a pin that only proves something
about THIS laptop is not a pin. Fixed in f068269 (REPO_ROOT), #12 closed with evidence.

## 45. Shadow is a dry run, not a preview (2026-09-04, MECE round 5)
Sol DOM-C reopened the shadow lifecycle with probes: shadow runs advanced LIVE discovery/action
belts — the post-merge watermark, retro_seen/cursor/completion, omnisweep completion, and
(historically) ci_acted — so the live cutover no-opped over what shadow had only LOOKED at, and
omnisweep completion without publication meant "retrying next cycle" was a lie (the complete
fast path returned before the upsert). Also in the same desk pass: a kill between the retro
checkpoint and its deferred-classification save permanently skipped a PR; a truncated tree
rendered COMPLETE; an abort rendered terminal; parked retro PRs promised re-arm "on the next
repo commit" that could never come. Laws: shadow belts are separate (pm_shadow_seen /
retro_shadow_seen) and live runs ignore them; state checkpoints happen only AFTER outcome
classification; completion is a whole-tree, published claim (omni_published retry contract);
aborts and truncations are never COMPLETE; parked state carries an expiry and re-arms
automatically. Regression pins: 9 red-pre-fix across engine/state/tiers.

