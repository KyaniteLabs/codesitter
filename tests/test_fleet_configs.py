"""Fleet config invariants (PM-3, 2026-09-03 — LEARNINGS #33).

Every *.fl4write.yaml in the repo root is repo law as data (fl4write/config.py).
The loader dedupes configs by repo key and can cycle ONE config per repo — a
second central config naming the same repo is shadowed (it ALERTs every cycle
and never runs). The fleet therefore keeps repo keys unique across ALL central
configs; this test is the CI-visible tripwire for the class that cost ~18
cycles of dedupe ALERTs on six dual-homed org repos (kinocut, Epoch,
Innerscape, checkyourself, devarch-framework, Elixis).
"""

from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIGS = sorted(
    p for p in ROOT.glob("*.fl4write.yaml") if not p.name.startswith(".")
)  # hidden .fl4write.yaml = a repo's in-repo law file, not a fleet config


def _repo_key(path: pathlib.Path) -> str:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path.name} is not a mapping"
    repo = data.get("repo")
    assert isinstance(repo, str) and "/" in repo, f"{path.name}: repo key missing/malformed"
    return repo


def test_fleet_configs_present() -> None:
    assert len(CONFIGS) > 100, "fleet checkout expected (central configs live in the repo root)"


def test_every_fleet_config_parses_with_repo_key() -> None:
    for path in CONFIGS:
        _repo_key(path)


def test_repo_keys_are_unique_across_the_fleet() -> None:
    seen: dict[str, pathlib.Path] = {}
    duplicates: list[str] = []
    for path in CONFIGS:
        key = _repo_key(path)
        if key in seen:
            duplicates.append(f"{seen[key].name} and {path.name} both name {key}")
        seen[key] = path
    assert not duplicates, (
        "duplicate repo keys — the loader cycles one config only, the rest ALERT every "
        "cycle and never run: " + "; ".join(duplicates)
    )
