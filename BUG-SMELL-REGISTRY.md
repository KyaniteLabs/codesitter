# BUG-SMELL-REGISTRY — fl4write

Raw feed per empower-orchestrator law: one line per bug/smell at notice-time,
no triage. Curated outcomes live in LEARNINGS.md.

- 2026-09-01 issues-lane — same triage comment posted 3-4× (email storm); state lost-update + identity mismatch → LEARNINGS #17
- 2026-09-01 rename-sweep — line-filtered sweep rewrote a URL string; surveillance probed the same file twice (spurious alerts) → LEARNINGS #18
- 2026-09-01 identity — app rename changed the slug/bot login; checks pinned the old login → LEARNINGS #20
- 2026-09-01 rulesets — contents-PUT 409 "must be made through a pull request" on 8 repos; branch=main 404s on master-default repos → LEARNINGS #21
- 2026-09-01 nucbox env — cron never saw .bashrc model key; quoted value 401'd auth → LEARNINGS #22
- 2026-09-01 assumptions — "app not installed on user account" was false; observable via /app/installations → LEARNINGS #23
- 2026-08-31 racing branches — five silent adoption losses to date (Innerscape, Elixis ×2, devarch, tastecheck, content-production-system); surveillance every cycle is the mitigation
- 2026-08-31 runner-log — per-repo ALERT lines invisible inside ok-status output; now logged explicitly
- 2026-09-01 six-lane audit batch — ~60 findings, 13 Critical: vacuous diff fallback, dead+dangerous fix lane clone, lethal-trifecta env, symlink write-through, gatekeeper false-clean, format drift (renderer/engine/metrics), dead config knobs, silent-state corruption handling, runner timeout arithmetic, pid-reuse lock wedges, README status lies → LEARNINGS #25; fixes in 1f20586
- 2026-09-01 meta — the hardened run-cycle.sh died on its own first deploy (set -u unbound var): new hardening needs the same verification bar as the code it guards
- 2026-09-01 completeness-recheck batch — 8 residual findings caught by re-verifying the "everything fixed" claim against the lane reports (LEARNINGS #26); fixed in the residuals commit; 4 open items = documented decisions (container isolation, human-approval merges, fallback provider, seeds)
- 2026-09-01 merge-scan — engine called check_and_merge_own_prs(config) without the REQUIRED bot_identity arg; TypeError swallowed by the broad except as "merge scan failed" every cycle since the audit fix — the scan had never once run (inert today only because merge_own_prs=false everywhere; landmine for the day it's enabled). Fixed with the post-merge build + regression test.
- 2026-09-01 prune-ordering (self-caught in build) — prune_closed ran before the post-merge sweep could see this cycle's merged records; on any watermark rewind the head-SHA guard was already gone → fresh model call + re-review. Fixed: sweep before prune, records kept one cycle.
- 2026-09-01 ci/lint — PM-1's final commit red on CI, green locally (ruff 0.15.8 vs CI's 0.16.5 default-rule widening); 'ruff clean' was a version-local claim → LEARNINGS #27; fix = explicit rule selection in pyproject
- 2026-09-01 deploy-order — the 18:00 cron exec'd the OLD run-cycle.sh body (bash buffered pre-pull) while post-pull python -m invocations ran the NEW engine: sweep fired, telemetry grep didn't. Self-corrects the next cycle; noted so a half-applied deploy is never misread as a bug.
- 2026-09-01 forgejo-WAF — Cloudflare-fronted forge: API GETs pass, POST/PATCH from non-browser UAs get WAF 1010 — every engine write silently fails while reads work (silent-asymmetry class, live-caught via the liminal audit issue updates). Fix: tailnet-direct api_base (VPS+nucbox share the tailnet); CF stays for humans.
- 2026-09-01 forgejo-identity — the bot user was creatable via the VPS container CLI all along (docker exec -u git forgejo forgejo admin user create/generate-access-token): "no admin token" ≠ "no admin path" — enumerate the ssh config's FULL host list + CLI surfaces before declaring a click blocked. Transient-owner-token usage is viable with mint→use→DB-delete hygiene (disclosed).
- 2026-09-01 gitea-contents-PUT — repos defaulting to master reject implicit-branch writes ("user cannot commit") AND explicit-branch when a push-lock rule covers master; the PR route (new_branch + pull + merge, no merge-whitelist) self-completes adoption with plain write perms — LEARNINGS #21's Forgejo twin.
