# Round-14 repair follow-up review

## Verdict

**APPROVE — the local repair diff closes the five defects rejected in `INDEPENDENT-REVIEW.md` and the scheduler timestamp-validation hole within this scoped re-review.** No concrete regression was found in the focused changes or their directly exercised boundaries.

This approval is limited to the uncommitted repair diff and `tests/test_pm_recovery.py`. It is not an exhaustive round-14 certification. The status of the other round-14 findings remains unchanged and unverified here. The parent owns the full-suite run; no signing-dependent result is claimed by this review.

## Finding-to-evidence map

1. **F14-D007 — PASS.** Both adapters now count non-dictionary rows and dictionary rows rejected by `_row_pr`, then raise `ForgeError` instead of certifying a partial open or merged listing (`fl4write/forges.py:488-508`, `fl4write/forges.py:511-555`, `fl4write/forges.py:698-718`, `fl4write/forges.py:721-755`). The original malformed-row reproduction now raises for GitHub and Forgejo. The focused matrix also covers both adapters, open and merged lanes, and non-dictionary and malformed-dictionary rows (`tests/test_pm_recovery.py:152-165`).

2. **F14-A01 — PASS.** `_git_diff_path` identifies the separator by equal old/new path halves for the ambiguous same-path form and no longer truncates the selected new path at whitespace (`fl4write/analyzer.py:54-63`, `fl4write/analyzer.py:88-103`). Both exact original probes now return `my file.py` and `dir/a b/c.py`; both are pinned at `tests/test_pm_recovery.py:25-27`.

3. **F14-D004 — PASS.** Strict Pydantic model configuration now applies at the public `RepoConfig.model_validate` boundary (`fl4write/config.py:28-63`). The exact reproduction, including numeric strings for `max_tokens`, `temperature`, `seed`, and `test_timeout`, now fails validation. Focused tests pin the three model-route fields (`tests/test_pm_recovery.py:168-173`), while the isolated original probe additionally verified `test_timeout`.

4. **F14-D005 — PASS.** Forge and model URL validators now require a hostname and access the parsed port, which rejects nonnumeric and out-of-range ports during model construction (`fl4write/config.py:103-113`, `fl4write/config.py:123-130`). The exact invalid-port reproduction now fails validation; focused tests also cover an out-of-range port and missing hostname (`tests/test_pm_recovery.py:176-182`).

5. **F14-A05 — PASS.** Credential-bearing lifecycle paths now use a SHA-256 identity rather than reversible Unicode escaping (`fl4write/renderer.py:135-145`). The exact reproduction produces a redacted display and a digest that does not contain the source path. Distinct redacted and literal paths remain distinct, and render/parse/re-render stability is pinned for credential, backslash, and newline cases (`tests/test_pm_recovery.py:49-68`).

6. **Scheduler `merged_since` validation — PASS.** The scheduler now delegates non-null timestamps to the canonical timezone-aware `_valid_iso` validator (`fl4write/tiers.py:89-94`). Date-only, naive, and syntactically bogus `T` values are rejected, and corrupt scheduler state resolves to unknown rather than cold (`tests/test_pm_recovery.py:102-114`). The isolated bogus-timestamp probe returned `None`.

## Verification

- `python3 -m pytest tests/test_pm_recovery.py -q`: **44 passed in 0.20s**.
- Exact original reproductions: **6/6 passed** (five rejected defects plus scheduler validation).
- Focused source review found no new structural regression, file-size boundary crossing, scattered special-case growth, or public disclosure in the repair diff.
- Full suite: **not run by this reviewer**, per scope.

## Remaining uncertainty

The prior report did not confirm the other round-14 findings item by item, and this follow-up does not promote them to confirmed. Ledger closeout, signing-dependent fixtures, nested-suite behavior, and repository-wide interactions remain outside this scoped approval unless separately verified by the parent.

## IMPROVEMENTS

1. **Pin the complete D004 reproduction.** The focused test covers model-route numeric fields but not `test_timeout`; add `test_timeout` to the public-schema numeric-string matrix because the original failure spanned both nested and top-level fields.
2. **Give repair tests finding IDs in their names or parametrization IDs.** Mapping behavior back to five reopened findings required manual cross-reference; explicit IDs would make future red/green review mechanical.
3. **Move the inline `hashlib` import to module scope.** The current function-local import is harmless but adds avoidable noise in a core rendering helper; a module import keeps the identity path direct and easier to scan.
