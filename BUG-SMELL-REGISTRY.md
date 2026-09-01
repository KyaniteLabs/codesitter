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
