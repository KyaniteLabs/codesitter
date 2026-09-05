# Round-14 independent review

## Verdict

**REJECT — round 14 is not closed.** Commits `b4524e9` and `cc1e486` contain a nominal code change for each of the 39 source findings, but at least five original findings remain defective. Four are direct reproductions of the source finding, including the requested public-validation check. The fifth introduces a public-output disclosure while attempting to fix lifecycle identity.

The canonical ledger is also not a round-14 closeout record: `/tmp/fl4gauntlet/ledger/FINDINGS-LEDGER.md` ends at the round-13 close and contains no round-14 disposition. Therefore neither the implementation nor the ledger supports “39 fixed.”

## Confirmed findings

### 1. Major — F14-D007 still treats malformed PR listings as complete

The adapters initialize `_pr_rows_dropped`, but do not increment it when a dictionary fails `_row_pr`; GitHub open-PR enumeration also skips non-dictionary rows without incrementing it. The final guard therefore returns an empty, apparently complete list (`fl4write/forges.py:488-510`, `fl4write/forges.py:695-716`). This preserves the original prune/watermark hazard.

Reproduction:

```bash
python3 - <<'PY'
from fl4write.config import ForgeBinding
from fl4write.forges import GitHubAdapter, ForgejoAdapter
for cls, base in [(GitHubAdapter, 'https://api.github.com'),
                  (ForgejoAdapter, 'https://forge.invalid')]:
    a = cls(ForgeBinding(role='primary', api_base=base, token_env='TOK'))
    a._paginated = lambda *a, **k: [{'number': 1}]
    print(cls.__name__, a.list_open_prs('o/r'))
PY
```

Observed: both adapters return `[]`; neither raises `ForgeError`.

### 2. Major — F14-A01's stated unquoted-space probe still fails

The new parser uses `rfind(" b/")`, then still truncates the selected token with `split()[0]` (`fl4write/analyzer.py:54-81`). It does not recover the new pathname in the source report's exact example and also misparses a pathname containing an internal ` b/` segment.

Reproduction:

```bash
python3 - <<'PY'
from fl4write.analyzer import _git_diff_path
print(_git_diff_path('diff --git a/my file.py b/my file.py'))
print(_git_diff_path('diff --git a/dir/a b/c.py b/dir/a b/c.py'))
PY
```

Observed: `my` and `c.py`, not `my file.py` and `dir/a b/c.py`.

### 3. Major — F14-D004 public model validation still coerces malformed numeric strings

The new `_StrictModel` validator rejects non-boolean values for boolean fields and booleans for numeric fields, but it does not reject strings for numeric fields (`fl4write/config.py:31-63`). Pydantic subsequently coerces those strings. This contradicts the source finding's model-level strictness requirement; strictness remains partial rather than encoded in the public schema.

Reproduction:

```bash
python3 - <<'PY'
from fl4write.config import RepoConfig
x = {'repo':'o/r', 'forges':{'p':{'role':'primary',
     'api_base':'https://api.github.com','token_env':'TOK'}},
     'model':{'endpoint':'https://model.invalid','model':'m',
              'max_tokens':'4000','temperature':'0.2','seed':'1'},
     'test_timeout':'240'}
c = RepoConfig.model_validate(x)
print(c.model.max_tokens, c.model.temperature, c.model.seed, c.test_timeout)
PY
```

Observed: validation succeeds and returns `4000 0.2 1 240` as numeric values.

### 4. Major — F14-D005 public URL validation still accepts an invalid port

`ForgeBinding._api_base_queryable` checks only `urlsplit(...).netloc` (`fl4write/config.py:100-110`). `_is_github_base` now contains the runtime exception, but `RepoConfig.model_validate` still accepts `https://api.github.com:notaport`, contrary to the source finding's explicit load-time validation requirement. The malformed GitHub binding is then misrouted as non-GitHub rather than rejected.

Reproduction:

```bash
python3 - <<'PY'
from fl4write.config import RepoConfig
x = {'repo':'o/r', 'forges':{'p':{'role':'primary',
     'api_base':'https://api.github.com:notaport','token_env':'TOK'}},
     'model':{'endpoint':'https://model.invalid','model':'m'}}
print(RepoConfig.model_validate(x).forges['p'].api_base)
PY
```

Observed: the invalid-port URL is accepted.

### 5. Major — F14-A05's lifecycle key exposes a reversible credential-shaped filename

`path_key` avoids redaction collisions by Unicode-escaping every character of the raw path, then places that value in the public finding heading (`fl4write/renderer.py:135-145`, `fl4write/renderer.py:171-184`). This is reversible encoding, not sanitization. A credential-shaped filename hidden by `path_display` is recoverable byte-for-byte from the posted comment, while the scrub assertion no longer recognizes it.

Reproduction:

```bash
python3 - <<'PY'
from fl4write.renderer import path_display, path_key
p = 'src/AKIA' + 'IOSFODNN7EXAMPLE.py'  # public documentation fixture
print(path_display(p))
print(path_key(p))
PY
```

Observed: display output is `src/[redacted].py`, but the lifecycle key contains the complete path as reversible `\uNNNN` sequences. Canonical identity must not be embedded in the public display channel.

## Coverage and verification

- Source findings reviewed: 39 total (DOM-A 9, DOM-B 4, DOM-C 8, DOM-D 17, DOM-E 1).
- Nominal implementation coverage: 39/39 have labeled changes across the two commits.
- Confirmed fixed: not asserted item-by-item in this bounded review.
- Confirmed remaining defects: 5, listed above.
- Unverified: all other source findings beyond source/diff inspection and the existing focused regression suite.
- `python3 -m pytest -q tests/test_pm_recovery.py`: **30 passed**.
- A repository-wide `pytest -q` invocation was not a valid verification signal because the standalone `pytest` executable could not import the local package; a later `python3 -m pytest -q` run exceeded the review command window before completion. No full-suite pass is claimed.

## IMPROVEMENTS

1. **Make each source finding's exact probe a required red-before/green-after test.** The A01 fix fails the report's own example, and D007's guard is unreachable for common malformed rows. Add one parametrized round-14 test table keyed by all 39 IDs.
2. **Put strictness in field types, not an annotation-inspection validator.** The validator's partial type logic still permits numeric-string coercion. Use Pydantic strict numeric types/config and validate parsed URL hostname/port during model construction.
3. **Separate private lifecycle identity from public rendering.** The attempted collision fix serialized reversible raw identity into a comment. Persist a keyed digest or private canonical identity in state/marker metadata while keeping the visible path irreversibly redacted.
