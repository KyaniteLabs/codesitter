# Recovered historical audit ledger

## Feature draft review — September 5

FEATURE13-DRAFT-REVIEW.md reproduces five new safety findings in the isolated
unmerged candidate. Publication was subsequently quarantined, with two focused
boundary tests passing. The findings remain open; containment is not repair.
Candidate full suite before quarantine:698 pass3 skip. No candidate shipment,
fresh whole-project green round, or certification follows. Clean counter0/3.

## Successor round 16 — September 5

FRESH-ROUND-16.md independently approved the readiness and live-evaluation
repairs, now deployed as cae36ee. Isolated full release:672 passed, zero skips;
RELEASE-VERIFICATION.json binds the reviewed source. Real audit issue7 now
contains readiness77/100, verified after version2 refresh without rescanning.

Whole-project verdict remains NOT GREEN. Feature13 was rejected for shipment:
R16-001 malformed baseline state reproduced; parent fixed it with five
run-boundary cases (candidate20 tests pass). Authenticated fix/refresh and
forge publication remain under implementation in a separate candidate.
No feature deployment or exhaustive certification is claimed; clean count0/3.

## Successor round 15 — 2026-09-05

Fresh recon: FRESH-ROUND-15.md. R15-001, R15-003 and R15-004 accepted,
reproduced, repaired and pinned in tests/test_round15.py. R15-002 rejected:
the existing severity-membership guard prevents the claimed crash; the
counterevidence is executable. Independent repair/config approval:
ROUND15-REPAIR-REVIEW.md. Full suite: 665 passed, 3 live-model skips;
ROUND15-VERIFICATION.json binds source and JUnit hashes. Round NOT GREEN
because it found valid defects. Consecutive clean rounds remain 0/3.

## Initial recovery record

Successor repair result: six classes fixed locally, 45 new cases, full suite
650 passed / 3 live-model skips. Scoped independent re-review APPROVED.
See RECOVERY-REPORT.md and REVIEW-FOLLOWUP.md. This does not close round 14
or change the 0/3 consecutive-green counter.

Recovered 2026-09-04 from the interrupted PM's local audit artifacts. Historical verdicts below are that PM's record, not successor re-verification. Round 14 was not closed. Clean-round counter remains 0/3.

# FINDINGS LEDGER — FL4WRITE MECE team-audit loop (2026-09-04)
Schema: F<round>-<seq> | round | domain | member | severity | claim | evidence | what is wrong | fix/probe. Verdict: new/dup/invalid/fixed.
Green light = THREE CONSECUTIVE full rounds with ZERO new valid findings.
DOMAINS: A review pipeline | B action lanes | C cycle engine | D forge/config/CLI | E claims/test contract.

## ROUND 1 (members: terra-A, luna-B, M3-C, sol-D (sub for mimo/qwen), glm-E)
F1-001 luna DOM-B | critical | sandbox HOME exposes ~/.sinter keys to executed code | probe: test code read real HOME config | FIXED 16b9e7b (throwaway HOME + env scrub; absolute-path residual → privilege-separation tranche)
F1-002 luna DOM-B | major | junit evidence path handed to untrusted process (same-user forgery) | argv-visible junit | FIXED 16b9e7b (boundary stated honestly; OS isolation = real cure)
F1-003 luna DOM-B | major | askpass token helpers leak on exception paths | finally audit | FIXED 352218d
F1-004 luna DOM-B | major | binascii.Error uncaught in file fetch | code read | FIXED 352218d
F1-005 luna DOM-B | major | issues-lane remote ops escape to cycle crash | code read | FIXED 352218d
F1-006 luna DOM-B | major | merge-gate check-runs not paginated (>~100 runs hid failures) | code read | FIXED 5fe8e99
F1-007 luna DOM-B | major | failed issue triage skipped forever (watermark jump) | code read | FIXED 5fe8e99 (retry set)
F1-008 luna DOM-B | minor | issue collection silently caps at 500 (10 pages x 50) | _paginated max_pages | CLOSED 19aa5e7 (truncation alert logged)
F1-009 luna DOM-B | major | triage output fields model-controlled w/o type validation | code read | CLOSED (typed coercion landed r3 c0b514c incl. bool/urgency/labels; see F2-109/F3-004)
F1-010 luna DOM-B | minor | telemetry usage ints not safe-int'd at an emit site | code read | CLOSED (F2-108 14c38b0 + _safe_int)
F1-011 luna DOM-B | major | fix-depth rail not enforced for ci_watch direct attempts | code read | RULED invalid-by-design (per-head synthetic PRs; SHA-keyed acting + cap alert)
F1-012 luna DOM-B | major | patch scope rail prompt-only | code read | RULED partial-resolved (single-file enforced; content-level = documented residual)
F1-013 terra DOM-A | critical | model-quoted secrets not redacted before posting | analyzer/render read | CLOSED e26fe69 (redaction at finding CONSTRUCTION; render redaction belt retained)
F1-014 terra DOM-A | major | findings:null posted as clean review (no fallback) | probe | FIXED 62a120d
F1-015 terra DOM-A | major | anchors beyond diff (line 999999) posted | probe | FIXED 62a120d (diff-span grounding)
F1-016 terra DOM-A | major | L1-B1 substring "test" = evidence (attestation) | probe | FIXED 62a120d
F1-017 terra DOM-A | major | L1-B3 whole-diff credential anchors unrelated findings | code read | FIXED 62a120d (per-path chunks)
F1-018 terra DOM-A | major | unclosed <!-- swallows comment tail | code read | FIXED 62a120d
F1-019 terra DOM-A | major | backtick filenames break heading structure | probe | FIXED 62a120d (strip in headings)
F1-020 terra DOM-A | minor | colon-path parse/emit asymmetry | probe | FIXED 62a120d (right-anchored parse)
F1-021 terra DOM-A | minor | gatekeeper applied-set keyed (path,line) not rule | code read | CLOSED 1c71709 (keep-set rule-keyed; demote side was fixed r1)
F1-022 terra DOM-A | major | readiness missing-evidence cap INERT (no caller passed categories) | code read | FIXED 62a120d
F1-023 sol DOM-D | major | Forgejo pagination param per_page (server ignores; lists capped) | code read | FIXED d06797e
F1-024 sol DOM-D | major | lenient base64 in file fetch | code read | FIXED d06797e
F1-025 sol DOM-D | minor | zero-byte file misclassified as directory | code read | FIXED d06797e
F1-026 sol DOM-D | minor | empty token_env accepted (silent unauthenticated) | code read | FIXED d06797e
F1-027 sol DOM-D | minor | unknown CLI flags silently ignored (typo runs wrong mode) | code read | FIXED d06797e
F1-028 glm DOM-E | major | runner lock in world-writable /tmp | code read | FIXED 5fe8e99
F1-029 glm DOM-E | minor | FL4WRITE_POOL=0 → xargs unlimited | code read | FIXED 5fe8e99
F1-030 glm DOM-E | minor | check-dirty blind to staged/renamed/deleted | code read | FIXED 5fe8e99
F1-031 glm DOM-E | minor | malformed-plan edge | code read | FIXED 5fe8e99 (JSON guard)
F1-032 glm DOM-E | minor | README claims contradict current state | code read | FIXED 5fe8e99
F1-033 M3 DOM-C | mixed | 50-item walkthrough — watermark/cap/race items verified OK-by-design; per-finding FJ escalation comments | code read | FIXED (escalate-once)
F1-034 M3 DOM-C | minor | model-failure cap terminal at SHA | code read | RULED by-design (alert exists)

Round-1 close: 28/33 unique findings FIXED or RULED; 5 open minors queued (F1-008/009/010/013/021).
DOM-D substitutions recorded (mimo 2x reasoning-budget fail; qwen connection fail).

## ROUND 2 (rotation: luna-A, M3-B, terra-C, glm-D, sol-E) — in progress
F2-001 sol DOM-E | major | my round-1 JSON guard clobbered scheduler exit status (case overwrote $?) | run-cycle.sh | FIXED 720f6b9
F2-002 sol DOM-E | minor | empty due-list feeds xargs a NUL record (phantom worker error) | FIXED 720f6b9
F2-003 sol DOM-E | minor | check-dirty regex missed MM/AM/UU states | FIXED 720f6b9 (any porcelain line)
F2-004 sol DOM-E | major | README claims every finding cites a capability; code allows bounded 'general' fallback | FIXED 720f6b9 (doc truth)
F2-005 sol DOM-E | major | LEARNINGS #42 overclaimed junit evidence vs honest boundary | FIXED 720f6b9
F2-006 sol DOM-E | minor | README fleet count 129 vs claimed 130 | DUP/INVALID (recomputed: 129 files)
F2-007 sol DOM-E | minor | PILOT green-cycle definition stale (31 ok constant) | FIXED 720f6b9
F2-101 glm DOM-D | major | reopened F1-023 Forgejo pagination | DUP (fixed d06797e; pack was stale — process bug fixed: refresh-packs.sh)
F2-102 glm DOM-D | minor | reopened F1-026 empty token_env | DUP (fixed d06797e)
F2-103 glm DOM-D | minor | reopened F1-027 unknown CLI flags | DUP (fixed d06797e)
F2-104 glm DOM-D | minor | reopened F1-024 lenient base64 | DUP (fixed d06797e)
F2-105 glm DOM-D | major | GH App auth minted on Forgejo-primary repos (fail+PAT every cycle) | FIXED 7ef2604
F2-106 glm DOM-D | minor | dead trailing return in format_cycle_line | FIXED 7ef2604
F2-107 glm DOM-D | minor | config path taken from argv[1] even when it is a flag | FIXED 7ef2604
F2-108 M3 DOM-B | major | calibration snapshot crashes on string usage fields (closes F1-010) | FIXED 14c38b0
F2-109 M3 DOM-B | minor | triage urgency vocab drift (orphan 'critical' marker) | FIXED 14c38b0
F2-110 M3 DOM-B | rest | walkthrough dups of round-1 items | DUP (verified against fixed code)
Round-2 so far: 17 findings ruled (13 fixed incl 3 new majors, 4 dup/invalid). PENDING: luna DOM-A + terra DOM-C reports.
F2-201 terra DOM-C | major | omni cap double-counts tree per cycle (aborts legal sweeps) | FIXED ff2e580
F2-202 terra DOM-C | major | retro ties lost forever (strict < cursor) — PLUS the seen-set belt was dead since inception (int keys vs str after JSON) | FIXED ff2e580 (inclusive cursor + int normalization)
F2-203 terra DOM-C | major | state nested PR records: null record / non-numeric key crash | FIXED ff2e580
F2-204 terra DOM-C | major | ci_acted set before escalation; failed issue-open never retries | FIXED ff2e580
F2-205 terra DOM-C | major | non-ForgeError shape rows at CI/metrics boundaries | RULED covered (round-1/2 containment + metrics widening in place; forges reaction rows degrade via metrics try)
F2-206 terra DOM-C | minor | acceptance counts any reaction (eyes counts as addressed) | FIXED ff2e580 (+1/hooray only)
F2-207 terra DOM-C | major | readiness helper had NO caller + read wrong field ('rule_id' vs persisted 'rule') | FIXED ff2e580 (wired at completion + both fields)

ROUND 2 CLOSE: 27 findings ruled — all FIXED except ledgered dups/ruled-by-design. New clean-round count: 0 (rounds 1-2 both found real defects).
F1-008 | CLOSED 19aa5e7 (paginated cap truncation now logs)

## ROUND 3 (rotation: M3-A, sol-B, glm-C, terra-D, luna-E) — in progress
F3-001 sol DOM-B | critical | merge-gate pending overwritten by last page (my pagination edit left a stale line) | FIXED cfa6ed8
F3-002 sol DOM-B | critical | verify_diff_tests kept the token helper alive during test execution | FIXED c0b514c
F3-003 sol DOM-B | major | sandbox stripped git identity -> every automated commit failed (explains 0 landed) | FIXED cfa6ed8
F3-004 sol DOM-B | major | triage bool coercion: string "false" -> True | FIXED c0b514c
F3-005 sol DOM-B | major | triage comment fields unescaped (heading injection) | FIXED c0b514c
F3-006 sol DOM-B | critical | triage public path lacked credential redaction | FIXED c0b514c
F3-007 sol DOM-B | minor | own-PR merge scan single-page | FIXED c0b514c
F3-101 glm DOM-C | major | retro sweep lacks per-PR forge containment | FIXED 583653a
F3-102 glm DOM-C | minor | vocab-drifted persisted severity crashes omni fix phase | FIXED 583653a
F3-103 glm DOM-C | minor | verify-budget comment claimed a gate that never existed; analyze ran past budget | FIXED 583653a
F3-104 glm DOM-C | minor | cursor skip paths no per-skip save | RULED fail-safe (crash loses <=10 positions -> retry)
F3-201 terra DOM-D | major | head_check_runs unpaginated (red HEAD beyond page 1 read as clean) | FIXED cb0bdfc
F3-202 terra DOM-D | major | adapter _call decode errors leak JSONDecodeError past boundaries | FIXED cb0bdfc
F3-203 terra DOM-D | critical | app token set under one env name, adapters read the binding name | FIXED cfa6ed8
F3-204 terra DOM-D | major | whitelisted --shadow flag was a fake-safety trap (runs live) | FIXED cfa6ed8
F3-301 luna DOM-E | critical | run-cycle plan guard CLEARED valid JSON plans since 720f6b9 -> hourly halt on next self-pull | FIXED cb0bdfc (zero fleet impact: runner had not pulled past 26c9958)
F3-302 luna DOM-E | major | scheduler plan file in predictable /tmp | FIXED cb0bdfc (~/.fl4write)
F3-303 luna DOM-E | minor | FL4WRITE_POOL=08 octal abort | FIXED cb0bdfc (base-10)
F3-304 luna DOM-E | major | README issues-lane claim vs per-repo opt-in | FIXED cb0bdfc-doc
F3-305 luna DOM-E | minor | check-dirty count wording duplicated | FIXED cb0bdfc
F3-4xx M3 DOM-A | unstructured | markdown chars in path display (adopted) | FIXED (path_display extended); remainder musings without citations

## ROUND 4 (rotation: sol-A, glm-B, luna-C, M3-D, terra-E) — desk close in progress
F4-001 sol DOM-A | critical | malformed model findings logged verbatim (secrets into logs) | FIXED 1dc96d2
F4-002 sol DOM-A | major | git octal-escaped quoted paths not decoded for anchoring | FIXED 1dc96d2
F4-003 sol DOM-A | major | bare secret prefix counts as credential | FIXED 1dc96d2
F4-004 sol DOM-A | minor | new-marker identity vs display-path keys mismatch | FIXED 1dc96d2
F4-005 sol DOM-A | major | path_display missing scrub (bidi filenames) | FIXED 1dc96d2
F4-006 sol DOM-A | minor | gatekeeper prompt omits rule_id while impl keyed by it | FIXED 1dc96d2
F4-1 glm DOM-B | major | junit evidence reads only first testsuite | FIXED 5e2131f
F4-2 glm DOM-B | major | verify non-pytest empty-output rule | RULED present/intended
F4-3 glm DOM-B | minor | fix-depth rail (dup of F1-011 ruling) | DUP (by-design)
F4-4 glm DOM-B | minor | telemetry docstring vs body | FIXED 5e2131f
F4-5 glm DOM-B | minor | dead symlink re-check | FIXED 5e2131f
F4-6 glm DOM-B | minor | issues-lane render raise containment | RULED contained (render inside try)
F4-7 glm DOM-B | minor | dead argv assignment | FIXED 5e2131f
F4-8 glm DOM-B | minor | sandbox-home process leak | FIXED 5e2131f
F4-401 terra DOM-E | major | plan guard accepts '{not-json' (silent no-op) | FIXED 0d29bc7
F4-402 terra DOM-E | minor | README test count drift | FIXED 0d29bc7
F4-C001 luna DOM-C | major | stale CycleLock unlink race (both cycles run) | FIXED 34796bf + pin (red pre-fix verified)
F4-C002 luna DOM-C | major | list-outage/deadline prunes PR records | FIXED 34796bf + 2 pins
F4-C003 luna DOM-C | major | retro_seen:null state crashes retro | FIXED 34796bf + pin
F4-C004 luna DOM-C | major | retro retries malformed-envelope PR forever | FIXED 34796bf + pin (park at 3 deferrals, alert)
F4-C005 luna DOM-C | major | annotation list null element escapes containment | FIXED 34796bf + pin
F4-C006 luna DOM-C | minor | per-PR comment claims cycle-wide gatekeeper counts | FIXED a563781 + pin
F4-Dxx M3 DOM-D | unstructured | 75KB stream; desk mining pending | OPEN-desk
Round 4: 20 fixed/ruled (luna 6/6 done via desk, CI verified green); remaining: M3 DOM-D stream mining. Side-find: CI was RED on every push since round-3 pins (host-contaminated /Users paths) — bot-flagged fl4write #12, fixed f068269 + LEARNINGS #44, closed with evidence.

## ROUND 5 (rotation: glm-A, terra-B, sol-C, luna-D, M3-E) — in progress
F5-001 terra DOM-B | major | issues-lane post failure skipped forever once a later success advances the watermark (F1-07 class reopened w/ recomputation) | probe: two-issue ordering | FIXED fbdcdaf (retry.add in the except branch) + pin
F5-002 terra DOM-B | major | fixlane escalate + executor PR body + ci_watch escalation render RAW f.path — forged headings / credential-shaped filenames in posted bodies | probe rendered "## forged heading" + AKIA-shaped path | FIXED fbdcdaf (renderer.path_display at all posted-body sites) + pin
F5-101 luna DOM-D | major | check_annotations adapter translation crashes on null/non-object rows (AttributeError past adapter; engine F4-005 belt unreachable — crash is adapter-side) | code read forges.py | FIXED 47ea58c (row guard) + pin
F5-102 luna DOM-D | major | tree walkers (GH recursive + Forgejo per-subtree) crash on malformed entries — escapes omnisweep tree scan | code read | FIXED 47ea58c (isinstance guard) + pin
F5-103 luna DOM-D | major | ModelRoute accepts temperature NaN/Inf and max_tokens<=0 — NaN serializes as invalid JSON; <=0 unusable requests | probe | FIXED 47ea58c (temperature [0,2], max_tokens [1,2^20]) + pin
F5-104 luna DOM-D | minor | FL4WRITE_CYCLE_BUDGET_S non-int -> raw ValueError traceback; negative -> silently expired deadline | code read cli.py | FIXED 47ea58c (_cycle_budget_s fails loud exit 2) + pin
F5-201 sol DOM-C | major | shadow runs advance LIVE belts: pm watermark, retro seen/cursor/complete, omni complete (cutover no-ops; omni completes w/o publishing) | probe CI_SHADOW_STATE | FIXED eb6c5e8 (separate shadow belts pm_shadow_seen/retro_shadow_seen; live ignores; completion publish-gated) + pin
F5-202 sol DOM-C | major | omnisweep completion persisted BEFORE issue create/update; complete fast-path returns before upsert — "retrying next cycle" was a lie | recomputation: completed findings -> zero open_issue calls | FIXED eb6c5e8 (omni_published retry contract) + pin
F5-203 sol DOM-C | major | retro PR checkpointed seen before deferred outcome removed it in-memory only — kill between saves skips PR forever | recomputation persisted retro_seen={7:True} vs corrected {} | FIXED eb6c5e8 (save only after classification) + pin (no checkpoint may carry pre-deferral seen-set)
F5-204 sol DOM-C | major | load_state: UnicodeDecodeError uncaught; wrong-typed aux fields crash later int()/comparison ops | code read | FIXED eb6c5e8 (decode reconcile + _normalize_aux) + pin
F5-205 sol DOM-C | major | tiers _read_state accepts ANY version (999 classified cold, not UNKNOWN->warm) | recomputation | FIXED eb6c5e8 (STATE_VERSION required) + pin
F5-206 sol DOM-C | major | any nonempty merged_since upgrades cold->warm — ancient watermark makes cold unreachable | recomputation 2000 watermark -> warm | FIXED eb6c5e8 (watermark RECENCY within 7d) + pin
F5-207 sol DOM-C | major | known-truncated tree alerts then records/publishes COMPLETE | recomputation (files=[], truncated=True) -> omni_complete | FIXED eb6c5e8 (truncation blocks completion; over-cap abort not terminal) + pin
F5-208 sol DOM-C | major | ci annotation message sliced w/o type normalization — numeric message TypeError escapes cycle | probe int message | FIXED eb6c5e8 (coercion belt) + pin (adapter level)
F5-209 sol DOM-C | major | retro parking alert promises re-arm on next repo commit — impossible for merged PRs; parked permanently | code read | FIXED eb6c5e8 (24h expiry auto re-arm; pin covers expiry re-listing + re-park)
F5-210 sol DOM-C | minor | top-level belts never GC'd (model_failures for closed PRs, ci_acted markers, retro parks) | code read | FIXED eb6c5e8 (prune_closed extends) + pin
F5-211 sol DOM-C | minor | CycleReport omni math zero on fast paths despite persisted findings | code read | FIXED eb6c5e8 (populate every return path) + pin
F5-3xx M3 DOM-E | unstructured | stream self-ruled runner scripts clean; 2 minor doc items adopted (README Day-1 HISTORICAL label, check-dirty wording) | desk-verified | FIXED 392b05d; no new valid code defects from the stream
Round 5 close: 21 findings ruled — all FIXED with red-pre-fix pins (19 code + 2 doc) across 6 commits (fbdcdaf, 47ea58c, eb6c5e8, 392b05d, 1c71709 + f068269 CI side-find). Full round: terra-B 2, glm-A 2, luna-D 4, sol-C 11, M3-E 2-doc (stream self-ruled code clean). glm seat notes: z.ai 429 quota wall x4 then empty replies — thinking must be EXPLICITLY disabled (http_member_glm.py) or glm burns budget in <think> and returns zero text. New clean-round count: 0 — round 5 produced 21 valid findings. Suite 450+3sk; CI green.

## ROUND 6 (rotation: terra-A, luna-B, M3-C, glm-D, sol-E — least-recent domains) — in flight
F6-001 terra DOM-A | critical | duplicate envelope keys in ONE object bypass the distinct-envelope refusal (json last-wins) | recomputation {"fixed_content":"SAFE","fixed_content":"CHANGED"} -> CHANGED | FIXED e26fe69 (object_pairs_hook rejection at every decode boundary) + pin
F6-002 terra DOM-A | critical | reopened F1-013: render-time redaction only — model-quoted credentials sent verbatim to the gatekeeper prompt | code read | FIXED e26fe69 (redaction at finding construction) + pin
F6-003 terra DOM-A | minor | reopened F4-001: drop-log slices BEFORE redacting — truncated credential prefixes leak | recomputation byte-72 token -> 'xxxxghp_AAAA' | FIXED e26fe69 (redact-then-slice) + pin
F6-101 luna DOM-B | major | reopened F1-024: executor._get_file_content lenient base64 — '!!!!' decodes to '' (empty premise -> fabricated fixes) | probe returned '' | FIXED e26fe69 (validate=True + empty rejected) + pin
F6-102 luna DOM-B | minor | telemetry calibration_snapshot UnicodeDecodeError on corrupt stream crashes CLI post-cycle | probe | FIXED e26fe69 (errors=replace) + pin
F6-201 M3 DOM-C | minor | (stream candidate, desk-verified) omni fix phase marks fix_attempted pre-call — transient 'error' never retried | code read engine.py | FIXED fffa2fc (un-mark on error; terminal outcomes stay) + pin
Round 6 so far: 6 fixed (all pinned red-pre-fix; commits e26fe69, fffa2fc). PENDING: sol DOM-E (codex run in flight, deep); glm DOM-D seat REPLACED by LUNA-MAX codex seat; M3 DOM-C seat REPLACED by LUNA-MAX-2 codex seat — CEO provider-switch 2026-09-04: China-peak windows degrade MiniMax/GLM (z.ai 429 walls x6, M3 6x think-only streams = the evidence); gauntlet seats route to OpenAI codex, many Lunas at max reasoning as needed; minimax/glm may return off-peak per rotation.
F6-E01 sol DOM-E | major | reopened F5-201: retro shadow still writes live retro_seen (loop-top) + can set retro_complete; omni shadow persists live cursor/findings | code read LEARNINGS.md:410-414; engine.py | FIXED 06a59bc (retro belt-only + complete guard; omni shadow = full dry run, zero state/spend) + pin
F6-E02 sol DOM-E | major | reopened A3: explicit pytest test_cmd discards diff's own test files -> whole-suite run attributes unrelated red to the changed file (false deterministic Critical) | probe argv | FIXED 06a59bc (diff files always targeted behind '--') + pin
F6-E03 sol DOM-E | major | verify filenames joined-then-split() corrupt spaces/option-like paths; junit flag appended after '--' | probe 'tests/test_changed name.py' -> two argv entries | FIXED 06a59bc (list elems + separator insert) + pins
F6-E04 sol DOM-E | major | reopened F4-401: runner validates JSON syntax but not shape — {"due":null} = silent empty cycle | probe exit 0 | FIXED 06a59bc (shape validation: due/alerts list[str], summary str) + pin
F6-E05 sol DOM-E | major | unguarded cd in run-cycle.sh + check-dirty.sh — missing checkout certified clean | probe | FIXED 06a59bc (cd || error exit) + pin
F6-E06 sol DOM-E | major | PILOT intro still presents issues lane as fleet-enabled | PILOT.md:9-10 vs README F3-304 | FIXED 06a59bc (HISTORICAL label + opt-in truth)
F6-E07 sol DOM-E | major | PILOT Forgejo blocker section contradicts live 45-config fleet | recomputed 45 live .fj configs | FIXED 06a59bc (SUPERSEDED banner)
F6-E08 sol DOM-E | minor | README fleet count 129 vs 130 tracked | git ls-files count | FIXED 06a59bc (130 + consistency pin)
F6-E09 sol DOM-E | minor | adoption-loss counts: 'five' events that enumerate six | PILOT + registry | FIXED 06a59bc (six across five repos)
Round 6 so far: 15 fixed (all pinned red-pre-fix; commits e26fe69, fffa2fc, 06a59bc; suite 461+3sk). PENDING: luna-max DOM-C (bash-224) + luna-max DOM-D (bash-225) codex seats in flight (China-peak switch: all remaining seats OpenAI-codex per CEO).
F6-C0xx luna-max DOM-C (remaining) | mixed | C010 loader rows FIXED 286ae6b; C014 markers FIXED 0a8fec0; C015 retention cap FIXED 0a8fec0; C016/17 deadline FIXED f95ecf7; C018 clean-publish FIXED f95ecf7; C019 bool version FIXED f95ecf7 | see commits
F6-3xx luna-max-2 DOM-D | mixed | 301 CLI doc truth, 302 oversized-fallback honesty, 306 transport wraps, 307 RA bounds, 308/309/312 envelope+row guards, 310 root truncation, 311 walk budget, 313 uncertain writes, 314/315 probe contracts — FIXED across 0a8fec0/514b952; 303 deletion-diff deferral ruled documented-residual (both adapters conservative); 304/305 removed with the fallback | 10 pins
ROUND 6 CLOSE (2026-09-04): 50 findings ruled — all FIXED with red-pre-fix pins (commits e26fe69, fffa2fc, 06a59bc, 286ae6b, f95ecf7, 0a8fec0, 514b952; suite 480+3sk; CI green @ 514b952). Rotation: terra-A 3, luna-B 2, sol-E 9, luna-max C 19, luna-max-2 D 17 (China-peak switch: minimax/glm replaced by codex lunas at max effort per CEO). New clean-round count: 0 — rounds 1-6 ALL produced valid findings (6/6 productive). Round 7 queued.

## ROUND 7 (rotation: luna-A, luna-max-2-B, terra-C, sol-D, luna-max-E — codex pool) — in flight
F7-C001 terra DOM-C | major | CycleLock stale-break compare-then-unlink TOCTOU — contenders interleave, one unlinks the other's LIVE lock, both cycles run (3rd reopen of the lock class) | recomputation of interleaving | FIXED ef23e5a (kernel flock — no stale-breaking exists; law tests rewritten) + pins
F7-C002 terra DOM-C | major | omni aux fields not normalized at load — omni_cursor=1 TypeError's resume; truthy "false" completion flags falsely terminalize | recomputation omni_scanned_total="bad" | FIXED ef23e5a (cursor/head str, counters int, flags bool at load) + pin
F7-C003 terra DOM-C | major | ci_watch trusts head as hex — non-hex SHA + failing check crashes fixes-enabled cycle at int(head[:6],16) | code read | FIXED ef23e5a (full 40-hex validation, degrade + alert) + pin
F7-A01 luna DOM-A | major | FINDING_LINE_RE rule spans newlines — crafted previous comment injects headings via resolved interpolation; unsafe rule keys accepted at load | code read renderer.py:41-46 | FIXED a56dbd5 (single-line identity groups; key charset refused at load) + pin
F7-A02 luna DOM-A | minor | L1-B1 scenario markers substring-match negatives — "unexecuted branch ... unaffected" retains Critical | code read analyzer.py:570 | FIXED a56dbd5 (positive-only marker scan w/ un/non/no guards) + pin
F7-D001 sol DOM-D | major | tree walk recursion limit on acyclic deep chains; wide responses unbounded | recomputation 1100-dir chain RecursionError | FIXED 8efe32c (iterative worklist) + pin
F7-D002 sol DOM-D | major | global visited set mistakes shared content-addressed subtrees for cycles — files omitted, omni completion blocked | recomputation two roots -> one subtree only | FIXED 8efe32c (ancestry-only frames + per-sha cache replay) + pin
F7-D003 sol DOM-D | major | intermediate envelopes (repo/commit/root) and root blob rows unvalidated | recomputation null repo envelope AttributeError | FIXED 8efe32c + 3b6f7d8 (coerce-or-drop helper everywhere) + pins
F7-D004 sol DOM-D | major | one malformed PR row aborts whole-page translation on both adapters | recomputation [None, {number:1}] TypeError/AttributeError | FIXED 3b6f7d8 (per-row skip + log) + pin
F7-D005 sol DOM-D | major | comment rows need usable id/body/login before marker matching | recomputation missing-id/numeric-body rows escaped | FIXED 3b6f7d8 (identity fields required) + pin
F7-D006 sol DOM-D | major | key presence != usable identifier ({number:null}); uncertain issue POSTs retried into duplicate audit issues | recomputation | FIXED 3b6f7d8 (positive-int ids only; title-based reconciliation = documented residual) + pin
F7-D007 sol DOM-D | major | substring host match routes GH adapter + App token to api.github.com.evil.invalid | recomputation | FIXED 8efe32c (exact hostname equality) + pin
F7-D008 sol DOM-D | major | GH token mirrored into EVERY unset binding env incl Forgejo mirrors | code read cli.py | FIXED 8efe32c (GitHub-host bindings only) + pin
F7-D009 sol DOM-D | major | strict models coerce quoted booleans ('off'->False) — silent live-write/fix enablement | recomputation shadow:'off' -> False | FIXED 3b6f7d8 (raw pre-validation) + pin
F7-D010 sol DOM-D | minor | non-GH binding credential presence unverified at load | code read | FIXED 3b6f7d8 (load-time warning) 
Round 7 so far: 15 fixed (all red-pre-fix pinned; commits ef23e5a, a56dbd5, 8efe32c, 3b6f7d8; suite 493+3sk). PENDING: luna-max-2 DOM-B, luna-max DOM-E seats in flight.
F7-B001 luna-max2 DOM-B | major | own-PR merge scan reads pr_data['number'] OUTSIDE per-PR containment — one malformed row kills the whole scan | recomputation [{}] -> KeyError | FIXED 3221b67 (row guard incl. parse inside try, number=None init) + pin
F7-B002 luna-max2 DOM-B | major | issues watermark read/written raw — non-int last_triaged_number TypeError's both comparisons AND the max() write; F5-001 retry set broke across JSON (ints->str) | recomputation 'bad' watermark -> TypeError | FIXED 3221b67 (boundary normalization read+write, int retry set) + pin
F7-B003 luna-max2 DOM-B | minor | fix-gate configured-command argv via cmd.split() corrupts quoted paths | recomputation | FIXED 3221b67 (shlex; malformed quoting fails closed) + pin
F7-E001 luna-max DOM-E | minor | run-cycle due dispatch newline-delimited — newline-bearing path splits into 2 worker records | probe | FIXED 3221b67 (NUL-delimited mapfile -d '') + pin
ROUND 7 CLOSE (2026-09-04): 19 findings, all fixed with red-pre-fix pins (commits ef23e5a, a56dbd5, 8efe32c, 3b6f7d8, 3221b67; suite 497+3sk, CI green @ 3221b67). Rotation: terra-C 3, luna-A 2, sol-D 10, luna-max2-B 3, luna-max-E 1 (both max seats SIGTERM'd once mid-run; reruns at default effort landed). Clean-round counter: 0 — rounds 1-7 ALL productive.

## ROUND 8 (rotation: luna-max-2-A, sol-B, luna-max-C, terra-D, luna-E — codex pool) — in flight
F8-0xx sol DOM-B (round 8) | in progress | F8-001 wrapped-base64 FIXED 66eef41; F8-002 isolated test exec + integrity belt FIXED 66eef41; F8-003 stable branch identity FIXED 66eef41; REMAINING desk: merge sha-binding (F8-004), combined-status gate (F8-005), verify pytest option arity + non-py files (F8-006/007), infra-vs-test failure classification (F8-008), issues foreign-marker ownership (F8-009), triage label escaping (F8-010), telemetry calibration window (F8-011), telemetry no-block (F8-012)
ROUND 8 SO FAR: lm2-A 2, lm-C 2, luna-E 2, terra-D 5, sol-B 3 of 12 — 14 ruled FIXED (c2069a8, 66eef41). Round 8 close pending sol-B remainder + pins.
ROUND 8 CLOSE (2026-09-04): 23 findings, all fixed with red-pre-fix pins (commits c2069a8, 66eef41, 14919ef; suite 509+3sk; CI green @ 14919ef). Rotation: lm2-A 2, lm-C 2, luna-E 2, terra-D 5, sol-B 12. Clean-round counter: 0 — rounds 1-8 ALL productive.

## ROUND 9 (rotation: sol-A, luna-max-B, luna-C, luna-max-2-D, terra-E — codex pool) — in flight
F9-001 lm DOM-B | minor | model_call outcome events lack ok; calibration defaulted failures to healthy | probe | FIXED c49d788 (emit ok post-validation; count explicit outcomes only)
F9-C001 luna DOM-C | major | retro listing dict envelope silently became empty + falsely declared COMPLETE | recomputation | FIXED c49d788 (envelope guard + alert, never complete) + pin
F9-C002 luna DOM-C | major | open listing dict envelope iterated keys, listing_failed False -> prune deleted live state | recomputation | FIXED c49d788 (envelope = lane failure) + pin
F9-C003 luna DOM-C | major | omni fingerprint paths-only — content edits w/ unchanged paths continued the stale-HEAD audit | recomputation | FIXED c49d788 (paths+sizes+head) + pin
F9-D001/003/004 lm2 DOM-D | major | get_file envelope, create-comment/issue ids positive non-bool ints | recomputation | FIXED c49d788 + pins
F9-D005 lm2 DOM-D | major | missing gh binary raised raw FileNotFoundError | recomputation | FIXED c49d788 (RuntimeError wrap) + pin
F9-E001 terra DOM-E | minor | README test counts stale (426) | recomputed 509+3sk | FIXED c49d788 + pin
F9-A01 sol DOM-A | critical | parse diagnostics echo raw model bytes (creds to logs) | recomputation | FIXED 6e73fed (redact head) + pin
F9-A02 sol DOM-A | major | think-only response certified clean | probe | FIXED 6e73fed (refuse) + pin
F9-A03 sol DOM-A | major | nested draft envelope beats real top-level | recomputation | FIXED 6e73fed (outermost owner decode) + pin
F9-A04 sol DOM-A | major | file-mode impossible anchors accepted | recomputation line 999999 | FIXED 6e73fed (real line cap) + pin
F9-A06 sol DOM-A | major | secrets ceiling guards legacy rule only (canonical = secrets-config) | recomputation | FIXED 6e73fed (rule family) + pin
F9-A07 sol DOM-A | major | negated clauses count as positive evidence (contradiction + scenario) | probes | FIXED 6e73fed (clause-level strip) + pins
ROUND 9 SO FAR: 15 ruled FIXED (c49d788, 6e73fed; suite 518+3sk). DESK-OPEN (sol DOM-A remainder + terra DOM-E hermetic-runner critique): A05 whole-file secrets evidence source, A08 readiness monotonicity (partial: ceiling clamp + independent audit-cats tracking needed), A09 path identity collisions, plus any items past A09 in the report.
F9-A05 sol DOM-A | major | whole-file credential findings lose literal evidence (no hunk map; message pre-redacted) | recomputation Nit | FIXED 9f47cd8 (file source is the anchor) + pin
F9-A09 sol DOM-A | major | path_display deletes filename chars — 'a_b.py' vs 'ab.py' collapse onto one lifecycle identity | recomputation | FIXED 9f47cd8 (lossless code-span display) + pins updated
F9-A10 sol DOM-A | major | renderer scrub boundary — unclosed HTML comments survive via deterministic Finding paths; assert_clean omits comments/hidden | recomputation | FIXED 9f47cd8 (full scrub + validation incl. html structure) + pin
F9-A11 sol DOM-A | major | ATX headings with 0-3 leading spaces / blockquote prefixes still mint structure | recomputation | FIXED 9f47cd8 (breadth) + pin
F9-A12 sol DOM-A | minor | keep-schema omits rule_id though matcher requires it | schema evidence | FIXED 9f47cd8 (schema + prose) + pin
F9-A13 sol DOM-A | minor | route stats double-count one physical call on parse failure (reported 2/2 healthy) | recomputation | FIXED 9f47cd8 (single accounting; parse is a parse signal) 
F9-A08 sol DOM-A | major | readiness not monotonic (categories derived from findings) | recomputation 0f=80 < 1Nit=81 | RULED partial (equal-category monotonicity holds; independent audit-category tracking is the full cure — tracked, engine-side persistence next tranche)
ROUND 9 CLOSE (2026-09-04): 29 findings ruled (26 FIXED with red-pre-fix pins + A08 partial + hermetic-runner critique RULED process note), commits c49d788, 6e73fed, 9f47cd8; suite 522+3sk; CI green @ 9f47cd8. Rotation: lm-B 1, luna-C 3, luna-E 1, terra-E 2(+critique), lm2-D 5, sol-A 13+ (A01..A13; A08 partial-ruled). Clean-round counter: 0 — rounds 1-9 ALL productive.

## ROUND 10 (rotation: luna-A, luna-max-2-B, terra-C, luna-max-D, sol-E — codex pool; resumed after PM session interruption) — CLOSED
F10-A01 luna DOM-A | major | truthy non-string message.content crashed the JSON scan (uncaught TypeError, fallback skipped) | probe content=5 | FIXED 922acd0 (payload-assert raise -> route loop falls back) + pin
F10-A02 luna DOM-A | major | fused negations ("cannot crash", "doesn't fail") bypassed the clause refutation scan | probe | FIXED 922acd0 (contraction normalization before scan) + pin
F10-A03 luna DOM-A | major | boolean finding anchors coerced to line 1 and fabricated grounded findings | probe line=True | FIXED 922acd0 (raw bool/int validation before pydantic) + pin
F10-C001 terra DOM-C | major | malformed retro merged rows silently dropped then retro_complete=True = terminal clean audit | recomputation [None] | FIXED 922acd0 (rows_bad alert + completion blocked) + pin
F10-C002 terra DOM-C | major | completed omnisweep never re-probed HEAD — stale-HEAD findings published forever (reopened F9-C003) | recomputation | FIXED 922acd0 (completed fast path probes head, restart on change) + pin
F10-C003 terra DOM-C | major | malformed omni tree rows dropped then certified complete | recomputation ([None],False) | FIXED 922acd0 (rows_bad gates BOTH completion sites — same-cycle finalize leak caught by pin) + pin
F10-B001 luna-max2 DOM-B | major | pytest option arity: -q treated as value-taking swallowed the suite path (reopened F8-006) | probe argv | FIXED af9e8ea (_pytest_verify_argv explicit model) + pins
F10-B002 luna-max2 DOM-B | minor | fix_attempt outcome event missing on infra/model error returns — telemetry undercounted failures | probe | FIXED af9e8ea (single guarded _finish terminal recorder, every path once) + pin
F10-B003 luna-max2 DOM-B | major | foreign-marker quarantine claimed alert visibility but had no structured report state | code read | FIXED af9e8ea (summary quarantined count + engine cycle alert + bounded 200-entry list) + pins
F10-B004 luna-max2 DOM-B | minor | bool identifiers pass isinstance(int) — int(True)==1 targets real endpoints | code read | FIXED af9e8ea (non-bool positive-int rails at issues collect + own-PR merge scan) + pins
F10-D001 luna-max DOM-D | major | typed PR-row fields (numeric head.sha, non-string title/body/author) reached PullRequest and coerced/raised (reopened F7-D004) | recomputation | FIXED af9e8ea (shared _row_pr: typed scalars validated pre-construction, per-row degrade) + pin
F10-D002 luna-max DOM-D | major | bool PR numbers accepted as #1 at 4 listing sites | recomputation | FIXED af9e8ea (raw non-bool positive-int only) + pin
F10-D003 luna-max DOM-D | major | bool comment id passed isinstance(cid,int) → update targeted /comments/True | recomputation | FIXED af9e8ea (bool exclusion, matching create guards) + pin
F10-D004 luna-max DOM-D | major | truthy non-string default_branch reached urllib quote as raw TypeError at 3 sites | recomputation | FIXED af9e8ea (typed branch, non-string -> main) + pin
F10-D005 luna-max DOM-D | major | get_file list/scalar success payload raised AttributeError (reopened F9-D001) | recomputation | FIXED af9e8ea (dict envelope required) + pin
F10-D006 luna-max DOM-D | major | appauth installation/token responses unvalidated — empty token cached+exported as bot identity | code read | FIXED af9e8ea (envelope + positive non-bool id + non-empty string token) + pin
F10-D007 luna-max DOM-D | minor | extra CLI positionals silently ignored — typo'd invocations ran anyway | code read | FIXED af9e8ea (exactly-one positional contract, exit 2) + pin
F10-E001 sol DOM-E | major | fix integrity compared .strip() content — indentation fixes discarded as no-ops; unreadable/deleted targets proceeded to staging (reopened F8-002) | recomputation | FIXED af9e8ea (exact-byte compare, fail-closed reads, git add status) + pins
F10-E002 sol DOM-E | major | option parser omitted value-taking options (-k) (reopened F8-006; merged with B001) | recomputation | FIXED af9e8ea (explicit model incl attached/bundled forms) + pins
F10-E003 sol DOM-E | major | chained full-suite test_cmds ran for diff attribution — baseline red minted deterministic Criticals on the changed file (reopened F8-007) | DialectOS config | FIXED af9e8ea (chains/custom runners UNVERIFIED, never run) + pin
F10-E004 sol DOM-E | major | diff-test discovery missed spec.* / __tests__/ / tests?/ dir conventions — changed tests bypassed the verifier silently | recomputation | FIXED af9e8ea (widened discovery; untargetable -> UNVERIFIED degrade) + pins
F10-E005 sol DOM-E | minor | README test count stale (509) and the pin enforced the literal (reopened F9-E001) | collection 542 | FIXED af9e8ea/4c51bad (pin derives the count from a live nested suite run) + pin
F10-E006 sol DOM-E | minor | README pointed operators at untracked kinocut.fl4write.yaml | git ls-files | FIXED 4c51bad (tracked kinocut.fj.fl4write.yaml reference) + pin
F10-E007 sol DOM-E | minor | README fix-lane paragraph described the pre-deployment v0.1 plan (reopened F1-032) | code read | FIXED 4c51bad (rewritten as live behavior) + pin
ROUND 10 CLOSE (2026-09-04): 27 findings, all fixed with red-pre-fix pins (commits 922acd0, af9e8ea, 4c51bad; suite 542+3sk; CI green @ af9e8ea + 4c51bad). Rotation: luna-A 3, terra-C 3, luna-max2-B 4, luna-max-D 7, sol-E 7 (B001+E002 merged as one defect class; E005..E007 doc-truth). Round 10 was interrupted mid-desk (PM family emergency at ~00:53); resumed same-session: C002/C003 pins repaired (analyze stub + rows_bad same-cycle leak), remaining 21 findings desk-ruled after recon outputs B/D/E were read. Clean-round counter: 0 — rounds 1-10 ALL productive.

## ROUND 11 (rotation: luna-max-A, luna-B, sol-C, terra-D, luna-max-2-E; 40 findings) — CLOSED
F11-A01..A08 luna-max DOM-A | see rows | octal quoted git paths undecoded (reopened F4-002); think-only w/ trailing prose/unclosed forms certified clean (reopened F9-A02); malformed outer envelope fell through to nested drafts (reopened F9-A03); negation strip swallowed positive conjunctions (reopened F9-A07); backtick paths aliased with apostrophe paths (reopened F9-A09); reference/protocol-relative remote images bypassed scrub; clean omnisweep scored readiness 80 (reopened F9-A08); control-char log injection (reopened F4-001) | recomputations | ALL FIXED a42dfe5 (closed-think scoped refusal keeps the UltraQA unclosed-think law; backtick-run code-span fences are byte-lossless; clean complete sweeps score 100 full-coverage) + pins
F11-B001..B08 luna DOM-B | see rows | fetch crashes bypassed _finish; configured junit paths let executed code own evidence (reopened F1-002); malformed issue bodies crashed the lane; single-page fallback truncated issues intake (reopened F1-008); pytest infra failures minted Criticals (reopened F8-008); calibration line-slice erased qualifying events (reopened F8-011); string 'false' counted as ok; unbounded pagination loops | recomputations | ALL FIXED a42dfe5 (incl. harness fixes: planted/quality fakes modeled infra failures that USED to mint false Criticals) + pins
F11-C001..C016 sol DOM-C | see rows | pruning/open_ids on malformed listing rows (reopened F9-C002); shadow dependency-skip wrote live state (reopened F5-201); deterministic finding terminalized SHA (reopened F6-C007); truncated-snapshot cursor trust (reopened F5-207); unanchored fingerprint (reopened F9-C003/F10-C002); fetch-exception quarantine gap (reopened F6-C008); partial restart resets (reopened F7-C002 state reconcile; F5-204 numerics); tiers prs fail-safe; deadline lane containment (reopened F6-C016/17); retro alert truth (reopened F10-C001); ci escalation title limits; HEAD-probe containment; retention leaks (reopened F5-210) | recomputations | FIXED a42dfe5 + 534a627 (C013 acceptance reaction versioning RULED partial: dedupe per login exists; timestamp-vs-comment-version binding requires the adapter reaction-timestamp contract — tracked next tranche) + pins
F11-D001..D004 terra DOM-D | see rows | tree rows coerced into validity (reopened F10-C003); wrapped base64 refused (reopened F8-001); truthy/garbage merged rows entered post-merge lane; malformed reaction rows dropped valid ones (reopened F2-205) | recomputations | ALL FIXED a42dfe5 + pins
F11-E001..E004 luna-max-2 DOM-E | see rows | runner never invoked the C2 guard; pull failure continued on stale code; fleet-count counted the hidden in-repo law file (reopened F6-E08/F10-E005); CLI shadow doc contradicted schema (reopened F6-301); README volatile round marker | evidence | FIXED a42dfe5 + 3666a89 (guard runs every cycle; pull failure fatal; runner.log/logs gitignored; non-hidden enumeration 129) + pins
ROUND 11 CLOSE (2026-09-04): 40 findings (39 FIXED with red-pre-fix pins + C013 RULED partial tracked), commits a42dfe5/3666a89/534a627; suite 574+3sk; CI green @ 534a627. Rotation luna-max-A 8, luna-B 8, sol-C 16, terra-D 4, lm2-E 4. Reopened-fix ratio still ~2/3 of the round — rounds 1-11 ALL productive. Clean-round counter: 0.

## ROUND 12 (rotation: luna-A, sol-B, luna-max-C, luna-max-2-D, terra-E; 36 findings) — CLOSED
F12-A01..A08 luna DOM-A | see rows | pretty-printed final envelope refused after closed think; gatekeeper bool line anchors; rce/xss/ssrf substring false positives ('source'); angle-bracket + srcset remote images (reopened F11-A6); >3-backtick fences unparsable (reopened F11-A5); redaction aliases lifecycle identity (reopened F9-A09); curly-apostrophe negations bypass (reopened F10-A02); control-bearing paths hit gatekeeper raw | recomputations | FIXED 816717e + 8cfb673 (A6 RULED partial: display redaction kept; identity-vs-display separation tracked — window is credential-shaped filenames only) + pins
F12-B01..B12 sol DOM-B | see rows | CRITICAL: shared sandbox HOME let tests plant .gitconfig steering the privileged commit + post-test tree divergence; scrubbed patch premise destroyed file meaning (reopened F1-012); orphan fix branch after PR-creation failure (reopened F8-003); capped check-run evidence merged (reopened F1-006/F11-B008); --pyargs arity (reopened F8-006); default-command ignores known_env_failures; capped marker/issue scans advance watermarks (reopened F1-008); shadow mutates live retry belt (reopened F5-201); unbounded retry set (reopened F10-B003); untyped marker rows; OverflowError token counts (reopened F2-108); verify infra paths emit no telemetry | recomputations | ALL FIXED 816717e + 8cfb673 (per-run disposable test HOME, hardened privileged git GIT_CONFIG_* + write-tree/HEAD^{tree} belt, exact-bytes fence premise [bounded-diff deferral recorded], force-with-lease reconcile, incomplete pagination raises) + pins
F12-C001..C006 luna-max DOM-C | see rows | non-SHA anchors accepted (reopened F11-C015/F9-C003); persisted quarantine lists crash .append (state); truthy 'ci_acted:..' strings suppress red-head fixes; deadline not enforced inside issues/metrics (reopened F11-C011); bool check-run ids; dead omni_issue id never reconciled | recomputations | ALL FIXED 8cfb673 (40-hex anchors only + adapter fallback, list/bool normalization, deadline params, failure-count reconcile) + pins
F12-D001..D008 luna-max-2 DOM-D | see rows | FJ subtree rows without sha certify incomplete sweeps (reopened F11-D001..004); capped pagination returned as complete (prune hazard); bool check-run ids (dup C005); malformed file envelopes classify as files; CRITICAL forge token_env collides with model key_env (credential cross-send); bools coerce into int limits; repo ids accept URL delimiters; netloc-less api_base leaks raw ValueError | recomputations | ALL FIXED 8cfb673 (typed sha rows mark truncated, incomplete pagination raises ForgeError, strict content str, config validators: env-namespace isolation / bool-int rejection / repo charset / netloc + ValueError wrap as ForgeError) + pins
F12-E001..E002 terra DOM-E | see rows | flock setup failures misclassified as contention (silent fleet skip); README count attributed to the wrong round | evidence | FIXED 816717e + 8cfb673 (tool/exec error exits loud, contention-only rc1 quiet; provenance pinned) + pins
ROUND 12 CLOSE (2026-09-04): 36 findings (34 FIXED w/ pins + A6 + B2-bounded-diff RULED-partial tracked), commits 816717e/8cfb673; suite 590+3sk; CI green @ 8cfb673. Rotation luna-A 8, sol-B 12, lm-C 6, lm2-D 8, terra-E 2. Reopened ratio stayed high (~2/3) — rounds 1-12 ALL productive. Clean-round counter: 0.

## ROUND 13 (rotation: sol-A, luna-max-2-B, luna-C, terra-D, luna-max-E; 45 findings incl 3 Critical) — CLOSED
F13-A01..A15 sol DOM-A | see rows | CRITICAL credential-assignment values (low-entropy, e.g. password=aaaaaaaaaaaaaaaa) neither anchored nor redacted; escaped-key envelopes beat literal discovery; array/malformed-prefix drafts certified clean; whitespace-tolerant think closes ignored; zero-width chars dodge contradiction then normalize; 'never' negations unhandled + wide strip erased real claims; escaped-alt images; scrub/assert language mismatch (svg/display:none); tilde fences swallow output; zero-finding truncated review certified clean; quoted path token rstrip trimmed content quotes; lossy display aliases control/newline paths; raw demotion logs; readiness weights documented vs code (RULED partial: doc corrected, per-category scoring tracked); prompt reviewed destructively scrubbed source | recomputations | ALL FIXED 40a5c25 (JSON-aware envelope discovery keeps the UltraQA ambiguity law; narrow failure-claim scan for L1-B1/B5; injective control-escaping path identity; exact-source fenced premise) + pins
F13-B01..B09 lm2 DOM-B | see rows | CRITICAL verifier tests ran with the real HOME + later privileged push unhardened (reopened F12-B001); askpass helper deleted before force-with-lease retry; Unicode digits crash retry parse; bool/non-finite watermark; marker rows w/o usable ids; early verify paths emit no telemetry; merge response never validated; bool token counts; quarantine list state unnormalized | recomputations | FIXED 2999866/920452b + pins (E6/E7-style real git shim + hostile-hook integration pins)
F13-C01..C08 luna DOM-C | see rows | issues lane UnboundLocal after deadline deferral; merged-lane failures authorize pruning; fingerprint ignores excludes; omni_pub_fail "bad" crashes; malformed omni findings leave terminal flags; ci/retro/omni start past deadline; shadow dep marker suffix compare; unanchored sweeps certified complete | recomputations | ALL FIXED 920452b (prune barrier, per-lane gates, effective-scan fingerprint, atomic reset incl pub_fail, unanchored deferral) + pins
F13-D01..D06 terra DOM-D | see rows | CRITICAL duplicate token_env across GH-primary + FJ-mirror routes the App token to Forgejo (reopened F12-D005); non-dict FJ rows certify incomplete trees; GH check-run cap returns partial as complete (ci clears red); whitespace-only base64 reviewed as a file; CLI config errors print secret-bearing input values; float fields coerce bools | recomputations | ALL FIXED 2999866 + pins
F13-E01..E07 lm DOM-E | see rows | attached unknown pytest options bypass fail-closed; README ledger marker stale (rounds 1-11); PILOT soak clock claim stale; registry stops at round 9; NUL-dispatch + check-dirty pins source-only; privileged-git pin not behavioral | evidence | FIXED 2999866 (E5 tracked: full run-cycle dispatch integration deferred; E7 real temp-git hostile-hook pin added) + pins
ROUND 13 CLOSE (2026-09-04): 45 findings (43 FIXED w/ pins + A14 + E5 RULED-partial tracked), commits 920452b/2999866/40a5c25/a4241ca; suite 605+3sk. Rotation sol-A 15, lm2-B 9, luna-C 8, terra-D 6, lm-E 7. Largest round yet; Critical count rose to 3 (two credential-namespace/isolation, one severity-evasion). Rounds 1-13 ALL productive. Clean-round counter: 0.


## Round 14 — successor recovery, NOT CLOSED

39 reported findings; production fixes b4524e9 and cc1e486. Existing baseline: 605 passed, 3 live tests skipped. Original round had no new test cases. Successor regression work and independent review remain distinct from a complete fresh whole-project round.

### DOM-A/F14-A01

F14-A01 | round 14 | DOM-A | luna-max-2 | major | git diff path grounding for unquoted filenames containing spaces | fl4write/analyzer.py:79-81,113-127,419-423,653-672; quote: `diff --git a/my file.py b/my file.py` parsed as `my` | unquoted paths are truncated at whitespace, leaving the correct path without a span map while impossible line anchors remain accepted | use path-aware Git-header parsing and require nonempty spans for anchored findings; add an unquoted-space probe

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A02

F14-A02 | round 14 | DOM-A | luna-max-2 | major | grounding against a truncated PR diff | fl4write/analyzer.py:558-562,653-673; probe: truncated diff contained only `x.py`, model emitted `y.py:1`, result had `_diff_truncated: 1` and `_dropped_ungrounded: 0` | external file membership plus empty-span “not judged” accepts findings for files omitted from the supplied diff | require accepted paths and spans to exist in the supplied, non-truncated diff

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A03

F14-A03 | round 14 | DOM-A | luna-max-2 | major | scrub/inline protocol-relative remote images (reopened F11-A6/F12-A4) | fl4write/scrub.py:32-48,87-98,175-180; quote: `![x](<//evil.invalid/pixel>)` survived `scrub()` and `assert_clean()` | angle-bracket protocol-relative image destinations bypass both remote-image patterns and can remain in posted comments | add angle-aware protocol-relative matching to scrubbing and cleanliness assertions

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A04

F14-A04 | round 14 | DOM-A | luna-max-2 | major | finding lifecycle identity for escaped paths (reopened F13-A12) | fl4write/renderer.py:99-132,214-220; fl4write/engine.py:116-121; probe: backslash/newline paths round-tripped with `new=1,resolved=true` | escaped display paths are stored as previous identities and escaped again during comparison, causing unchanged findings to appear new and prior findings resolved | decode display paths before comparison or maintain a separate canonical raw identity

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A05

F14-A05 | round 14 | DOM-A | luna-max-2 | major | credential-shaped filename lifecycle identity (reopened F12-A6/F9-A09) | fl4write/renderer.py:124-132,214-220; fl4write/scrub.py:129-153; probe: `"src/AKIA" + "IOSFODNN7EXAMPLE.py"` (public documentation fixture) and `src/[redacted].py` both display as `src/[redacted].py`, with `new=0` | non-injective redaction is used as lifecycle identity, so distinct files alias and real findings can lose new/resolved state | compare using unredacted canonical paths and redact only for display

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A06

F14-A06 | round 14 | DOM-A | luna-max-2 | major | Critical severity ceiling for negated scenario clauses | fl4write/analyzer.py:475-484,784-830; probe: Critical messages `There is no possibility of arbitrary code execution.` and `There is no risk of data leakage.` remained Critical | negation handling omits “no possibility,” “no risk,” and similar constructions while scenario markers remain active | parse clause-level negative constructions comprehensively before scenario-marker detection

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A07

F14-A07 | round 14 | DOM-A | luna-max-2 | minor | JSON envelope parsing after closed think with an escaped key | fl4write/analyzer.py:274-289,308-323; probe: valid `<think>draft</think> {"\\u0066indings": []}` raised `ValueError` refusing the envelope | the early think-block check searches only for literal `"findings"` and rejects escaped keys that later parsing supports | perform JSON-aware envelope detection before closed-think refusal

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A08

F14-A08 | round 14 | DOM-A | luna-max-2 | minor | non-NUL control characters in finding rule IDs | fl4write/config.py:377-382; fl4write/models.py:25-31; fl4write/renderer.py:164-170,270-273; probe: `bad\x01rule` passed model validation, then rendering raised `ValueError: unscrubbed control char U+0001` | loader validation excludes only selected controls, allowing other control characters to reach rendering and crash the review | reject all unsafe control characters in rule IDs or safely escape them before rendering

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-A/F14-A09

F14-A09 | round 14 | DOM-A | luna-max-2 | major | readiness missing-evidence cap for Security & Privacy (reopened F13-A14/F1-022) | fl4write/capabilities.py:15-17,39-42,61-64,80-92,152-159; probe: omitting only `Security & Privacy` produced score `97`, labeled HIGH | Security & Privacy is weighted and contains security/privacy capabilities, but the hard-coded critical-category set omits it, allowing security-unchecked audits to receive a HIGH label | derive critical categories from the capability table and include Security & Privacy in the cap logic

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-B/F14-001

F14-001 | round 14 | DOM-B | codex gpt-5.6-terra | major | reopened — issue-intake fallback completeness | fl4write/issues.py:62-70 | The fallback breaks on a non-list page and also returns after ten full pages, then treats the partial list as complete; processing it can advance `last_triaged_number` past unseen issues permanently. | Return `[]` on non-list or exhausted-full-page fallback; pin both cases and assert the watermark holds.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-B/F14-002

F14-002 | round 14 | DOM-B | codex gpt-5.6-terra | minor | reopened — verify-test terminal telemetry | fl4write/executor.py:723-732 | Fetch and checkout failure branches `return None` before their adjacent `_v_unverified(...)` calls, so those terminal outcomes emit no `verify_tests` event despite the stated every-early-exit contract. | Move emissions before returns; pin fetch and checkout failures to exactly one `unverified` event each.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-B/F14-003

F14-003 | round 14 | DOM-B | codex gpt-5.6-terra | major | reopened — sha-bound squash-merge status | fl4write/executor.py:1042-1054 | The request correctly uses the PR-head SHA as a merge precondition, but successful squash merges produce a new merge-commit SHA; requiring response `sha == head.sha` marks real merges unproved and leaves `fix_prs_merged` at zero. | Keep request precondition; accept `merged: true` with a valid returned commit SHA. Pin a successful response whose SHA differs from the head.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-B/F14-004

F14-004 | round 14 | DOM-B | codex gpt-5.6-terra | major | reopened — foreign-marker quarantine cost containment | fl4write/issues.py:77-83,280,311-330 | An attacker-planted marker is detected only after the LLM triage call, then its issue is retained for every later cycle without watermark advancement. Public commenters can therefore force recurring model calls indefinitely. | Check/quarantine foreign markers before model triage; retain operator visibility without scheduling repeated model work; pin two cycles with one marker and zero triage calls.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-001

F14-001 | round 14 | DOM-C | luna-max | major | Shadow open-PR dependency skips suppress later live review (reopened F5-201) | fl4write/engine.py:1631-1637; fl4write/engine.py:276-285 | The dependency-skip branch unconditionally writes `dependency-skip` to live state, so a later live run sees the SHA as reviewed and does not invoke `_review_pr`. | In shadow mode record only shadow-belt state, or avoid mutating live PR state.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-002

F14-002 | round 14 | DOM-C | luna-max | major | Malformed omni finding reconciliation is not an atomic sweep reset (reopened F13-C005) | fl4write/state.py:230-246; fl4write/engine.py:868-879,930-935,993-1003 | Reconciliation removes terminal flags but retains old findings, `omni_head`, failure maps, and quarantine lists; the restarted scan can fetch at a stale HEAD and append/publish stale findings. | Apply the complete `_omni_reset_sweep` field set whenever omni findings are malformed.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-003

F14-003 | round 14 | DOM-C | luna-max | major | Truthy non-boolean omni fix flags permanently suppress eligible fixes | fl4write/state.py:230-237; fl4write/engine.py:620-627 | Optional `fix_attempted` and `fix_stale` values are not normalized; persisted `"false"` is truthy and silently skips the finding forever. | Require boolean optional flags or discard invalid values during state reconciliation.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-004

F14-004 | round 14 | DOM-C | luna-max | major | A fresh live omnisweep can complete without a trusted HEAD anchor (reopened F13-C008) | fl4write/engine.py:696-712,805-814,838-846,866-879,948-953 | The no-anchor guard applies only when a cursor or fingerprint already exists; a fresh scan fetches at `HEAD` and can persist `omni_complete` with no SHA, after which the fast path never probes HEAD. | Require a validated full SHA before scanning or persisting live completion; otherwise defer.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-005

F14-005 | round 14 | DOM-C | luna-max | major | Boolean tree sizes bypass the malformed-row guard and can falsely certify an empty tree (reopened F11-D001/F10-C003) | fl4write/engine.py:761-783,838-846 | `isinstance(False, int)` is true; recomputation with `("critical.py", False)` yields `rows_bad=False`, excludes the file as size zero, and sets `omni_complete=True` without an alert. | Reject boolean sizes explicitly with `not isinstance(size, bool)`.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-006

F14-006 | round 14 | DOM-C | luna-max | minor | Tier classification trusts malformed auxiliary state instead of failing warm (new) | fl4write/tiers.py:58-81,116-149,151-167 | `_read_state` bypasses canonical normalization; `open_ids="bad"` and `merged_since="garbage"` are accepted and can classify an old-pushed repository as cold instead of UNKNOWN/warm. | Reuse canonical state normalization or validate scheduler-consumed fields and return warm on corruption.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-007

F14-007 | round 14 | DOM-C | luna-max | major | Date-only retro cursors permanently skip merges occurring on that date (new) | fl4write/state.py:191-204; fl4write/engine.py:1170-1177,1250-1258 | `_valid_iso` accepts `2026-09-01`; lexical comparison makes `2026-09-01T12:00:00Z <= 2026-09-01` false, so same-day PRs are skipped and the retro window can be marked complete. | Require a full timezone-aware timestamp before accepting retro watermarks/cursors.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-C/F14-008

F14-008 | round 14 | DOM-C | luna-max | minor | Metrics loses the entire merged sample when the open listing contains one malformed row (reopened F2-205 with new ordering evidence) | fl4write/metrics.py:79-100 | Merged-row deduplication dereferences every existing open row before the later shape filter; one `None` or malformed row raises, the exception discards all merged rows, and the metric silently undercounts. | Filter/validate open rows before merged deduplication and preserve valid merged rows independently.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-001

F14-001 | round 14 | DOM-D | codex gpt-5.6-sol | critical | credential isolation (reopened F12-D005/F13-D001) | fl4write/config.py:229-253; fl4write/appauth.py:126-133; fl4write/analyzer.py:181-190 | Collision validation considers only configured forge `token_env` names, but app auth implicitly exports the forge credential as `GH_TOKEN` and `CODESITTER_GITHUB_TOKEN`; a config with `model.key_env: GH_TOKEN` and forge `token_env: GHT` validates, then sends the GitHub App token as Bearer credentials to the model endpoint; recomputation returned `config_accepted GH_TOKEN GHT` and `model_bearer_source 'APP_FORGE_TOKEN_SENTINEL'` | Reserve both implicit app-auth names against every model `key_env`, or eliminate global aliases and pass forge credentials through a scoped channel.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-002

F14-002 | round 14 | DOM-D | codex gpt-5.6-sol | major | sanitized CLI config errors (reopened F13-D005) | fl4write/cli.py:187-190,217-234 | The sanitized `config error` line is preceded by `log.error(..., exc)`, and `basicConfig` sends that full Pydantic exception to stderr; recomputation printed `input_value='TOPSECRET_SENTINEL_123456'`, so secret-bearing invalid fields still leak into logs | Never log the raw validation exception; log only sanitized locations/types after credential redaction.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-003

F14-003 | round 14 | DOM-D | codex gpt-5.6-sol | major | GitHub App credential binding and comment identity (reopened F3-D003) | fl4write/cli.py:268-287; fl4write/forges.py:77-82,514-543 | After minting an App token, the CLI copies it to a binding only when that environment variable is unset, but unconditionally sets `bot_login` to `fl4write[bot]`; an existing personal PAT therefore remains the adapter credential while comments are searched as the bot, causing unrecognized persistent comments and repeated posts; recomputation preserved `PERSONAL_PAT_SENTINEL` while expecting `fl4write[bot]` | Unconditionally bind the minted token to every GitHub-host binding, or resolve and set the identity corresponding to the credential actually retained.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-004

F14-004 | round 14 | DOM-D | codex gpt-5.6-sol | major | strict configuration booleans and numbers (reopened F7-D009/F13-D006) | fl4write/config.py:28-29,32-58,99,334-376; fl4write/__init__.py:7-18 | Strictness exists only in `load_config` preprocessing, while the publicly exported `RepoConfig.model_validate` remains coercive: recomputation converted `shadow: "false"` to live `False` and `fix.enabled: "yes"` to `True`; even the loader path misses optional integer `seed`, converting YAML `true` to integer `1` | Encode strict booleans and numeric types in the Pydantic models themselves, including optional numeric fields, rather than relying on loader-only name scanning.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-005

F14-005 | round 14 | DOM-D | codex gpt-5.6-sol | major | exact-host routing and URL validation (reopened F12-D008) | fl4write/config.py:67-75; fl4write/forges.py:919-925 | Config validation checks only that a netloc exists; `https://api.github.com:notaport` validates, then `_is_github_base` evaluates `parts.port` outside its `try` and raises raw `ValueError`, aborting CLI routing before the cycle | Validate hostname and port during config loading and keep all `urlsplit` property access inside the guarded router.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-006

F14-006 | round 14 | DOM-D | codex gpt-5.6-sol | major | forge transport exception boundary (reopened F6-306) | fl4write/forges.py:95-130,139-165 | Both transport wrappers omit `http.client.HTTPException` failures raised while reading responses; recomputation made `resp.read()` raise `IncompleteRead` and `_call` leaked raw `IncompleteRead` instead of retrying or raising `ForgeError` | Catch `http.client.HTTPException`/`IncompleteRead` in both wrappers, retry GET once, then wrap as `ForgeError`.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-007

F14-007 | round 14 | DOM-D | codex gpt-5.6-sol | major | PR enumeration row guards (reopened F7-D004/F11-C001) | fl4write/forges.py:464-512,640-684; fl4write/engine.py:423-518,1605-1711 | Built-in adapters discard malformed open and merged rows before returning, so the engine receives an apparently complete all-`PullRequest` list and cannot activate its prune barrier or merged-row watermark gap; recomputation of `[None, valid_row]` returned only the valid PR with no incompleteness signal | Return structured listing completeness, preserve a detectable malformed-row sentinel, or fail the enumeration with `ForgeError`; never prune or advance watermarks from a filtered partial list.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-008

F14-008 | round 14 | DOM-D | codex gpt-5.6-sol | major | persistent-comment at-most-once guard (reopened F7-D005) | fl4write/forges.py:514-543,686-711; fl4write/engine.py:267-283 | A comment containing the FL4WRITE marker and bot author but an unusable ID is logged and skipped; the adapter returns `None`, which the engine interprets as absence and follows with `create_comment`; recomputation returned `None` for an own marked comment with `id: None` | Distinguish absent from uncertain; raise `ForgeError` or return an explicit uncertain result whenever a potentially-owned marker row cannot be safely updated.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-009

F14-009 | round 14 | DOM-D | codex gpt-5.6-sol | major | complete tree enumeration (reopened F5-102/F11-D001/F13-D002) | fl4write/forges.py:355-370,805-821,834-870 | GitHub silently skips non-dict tree rows without setting `truncated`; Forgejo’s `entries_of` filters descendant non-dicts before the later guard can see them, making that guard unreachable; recomputation returned valid files with `truncated=False` for malformed rows on both adapters | Preserve every raw row through validation and mark the result truncated on non-dicts, unknown types, or invalid subtree paths; remove the premature Forgejo filtering.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-010

F14-010 | round 14 | DOM-D | codex gpt-5.6-sol | major | check-run row completeness | fl4write/forges.py:557-603; fl4write/engine.py:1390-1413 | `head_check_runs` validates only the list envelope and returns malformed rows as a complete result; the engine silently skips them and declares no failures, even clearing prior red state; recomputation with `[None]` produced `red_heads=0`, no alert, and removed `ci_red_sha` | Make any malformed check-run row render the page unqueryable/incomplete and return `None` rather than a partial list capable of certifying green.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-011

F14-011 | round 14 | DOM-D | codex gpt-5.6-sol | major | merged-PR timestamp guards (reopened F11-D003) | fl4write/forges.py:54-62,485-505,657-676 | `_parse_iso` accepts timezone-naive ISO timestamps, after which both adapters compare them with an aware watermark; recomputation raised `TypeError: can't compare offset-naive and offset-aware datetimes`, causing one malformed row to discard all valid siblings each cycle | Reject datetimes without timezone information or normalize them explicitly before comparison.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-012

F14-012 | round 14 | DOM-D | codex gpt-5.6-sol | major | changed-file extraction from forge diffs (reopened F4-002 at the DOM-D duplicate parser) | fl4write/cli.py:68-87; fl4write/forges.py:896-910; fl4write/analyzer.py:45-92 | CLI and Forgejo paths extract files only from unquoted `+++ b/...` lines, although Git quotes non-ASCII/control-bearing paths; recomputation found no files for `"b/caf\\303\\251.py"` while the canonical parser correctly returned `café.py`, so findings are rejected as outside the diff and the SHA can be marked reviewed clean | Use one shared Git-diff pathname parser based on `diff --git` headers for both diff getters.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-013

F14-013 | round 14 | DOM-D | codex gpt-5.6-sol | major | App installation-token response guard (reopened F10-D006) | fl4write/appauth.py:90-133 | Token validation accepts any nonempty string; recomputation accepted and cached `"   "`, then the installer would export it while selecting bot identity, producing persistent authentication failure for the cache lifetime | Reject whitespace-only, surrounding-whitespace, and control-bearing tokens before caching or export.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-014

F14-014 | round 14 | DOM-D | codex gpt-5.6-sol | major | secret-safe malformed-row logging | fl4write/forges.py:448-450,468-473,527-533,648-670,697-703 | Multiple malformed-row paths log `str(row)[:120]` without credential redaction; recomputation emitted a credential-shaped PR title verbatim in the warning | Log only row position and validation reason, or pass external row text through credential redaction before truncation.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-015

F14-015 | round 14 | DOM-D | codex gpt-5.6-sol | minor | diff-fetch error reporting (reopened F6-302) | fl4write/cli.py:32-45,74-85 | `make_get_diff` catches every `_gh` runtime failure—missing binary, timeout, authorization, and transport errors—but always reports `oversized (>20k lines)`; recomputation of `RuntimeError("gh unavailable")` produced that false diagnosis | Preserve a sanitized failure category or detect the specific oversized-diff response before using that message.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-016

F14-016 | round 14 | DOM-D | codex gpt-5.6-sol | minor | cycle-budget CLI validation (reopened F5-104) | fl4write/cli.py:170-184,290-300 | The parser enforces positivity but no upper bound; a 401-digit integer validates and then `time.monotonic() + budget_s` raises raw `OverflowError` | Bound the budget to an operational maximum and catch overflow while constructing the deadline.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-D/F14-017

F14-017 | round 14 | DOM-D | codex gpt-5.6-sol | minor | file-content envelope contract (reopened F10-D005) | fl4write/forges.py:374-408 | `get_file` validates the outer dictionary and encoding but calls `.split()` without requiring string content; integer, boolean, list, and dict contents all raised raw `AttributeError` instead of returning `None` as documented | Require `isinstance(data.get("content"), str)` before normalization and decoding.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.

### DOM-E/F14-001

F14-001 | round 14 | DOM-E | codex-gpt-5.6-luna | minor | README test-count/green-status regression pin | tests/test_gauntlet_fixes.py:3099,3104,3108; README.md:76 | The nested pytest subprocess return code and failure/error counts are ignored; a red run can satisfy the count assertion if README mirrors its partial counts, despite claiming “tests green.” | Require returncode 0 and assert zero failures/errors before accepting the count.

Recovery status: deployed change reported; requires behavioral verification and closure evidence. See RECOVERY-REPORT.md for successor results and reopened findings.
