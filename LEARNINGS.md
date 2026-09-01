
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
