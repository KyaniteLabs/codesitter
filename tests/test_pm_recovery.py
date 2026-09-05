"""Behavioral recovery checks for the interrupted round-14 desk."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from fl4write import analyzer, capabilities, config, renderer, scrub, state, tiers
from fl4write.forges import ForgeError, GitHubAdapter, ForgejoAdapter
from fl4write.models import Finding, PullRequest


def raw_config():
    return {
        "repo": "owner/project",
        "forges": {"github": {"role": "primary", "api_base": "https://api.github.com",
                               "token_env": "TEST_FORGE_KEY"}},
        "model": {"endpoint": "http://model.invalid/v1", "model": "test", "key_env": "TEST_MODEL_KEY"},
        "review": {"general": "Review code", "security-threat": "Review security"},
        "severity_vocab": ["Critical", "Major", "Minor", "Nit"],
    }


def test_space_path_grounding_uses_the_entire_new_path():
    assert analyzer._git_diff_path("diff --git a/my file.py b/my file.py") == "my file.py"
    assert analyzer._git_diff_path("diff --git a/dir/a b/c.py b/dir/a b/c.py") == "dir/a b/c.py"


def test_truncated_diff_cannot_ground_a_file_outside_the_model_input(monkeypatch):
    first = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    last = "diff --git a/y.py b/y.py\n--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-old\n+new\n"
    diff = first + " " * analyzer.MAX_DIFF_CHARS + last
    item = {"rule_id": "general", "severity": "Major", "path": "y.py", "line": 1,
            "message": "The changed branch corrupts the result."}
    monkeypatch.setattr(analyzer, "_call_model", lambda *a, **kw: json.dumps({"findings": [item]}))
    pr = PullRequest(forge="github", number=1, repo="owner/project", head_sha="a" * 40)
    doc = analyzer.analyze(pr, {"x.py", "y.py"}, diff, config.RepoConfig.model_validate(raw_config()))
    assert doc.findings == []


def test_angle_protocol_relative_image_is_removed():
    payload = "![x](<//example.invalid/pixel>)"
    cleaned = scrub.scrub(payload)
    assert "example.invalid" not in cleaned
    scrub.assert_clean(cleaned)


@pytest.mark.parametrize("path", ["a\\b.py", "a\nb.py", "src/AKIA" "IOSFODNN7EXAMPLE.py"])
def test_finding_identity_roundtrip_is_stable(path):
    cfg = config.RepoConfig.model_validate(raw_config())
    pr = PullRequest(forge="github", number=1, repo="owner/project", head_sha="a" * 40)
    finding = Finding(rule_id="general", severity="Major", path=path, line=1, message="A real defect.")
    body = renderer.render_review(pr, [finding], cfg, review_hash="abc")
    previous = [Finding(severity=sev, path=p, line=line, rule_id=rule, message="previous")
                for sev, p, line, rule in renderer.parse_finding_lines(body)]
    updated = renderer.render_review(pr, [finding], cfg, review_hash="abc", previous_findings=previous)
    assert "🆕" not in updated
    assert "Resolved since last review" not in updated


def test_redacted_identity_does_not_serialize_a_reversible_secret():
    path = "src/AKIA" "IOSFODNN7EXAMPLE.py"
    key = renderer.path_key(path)
    assert key != renderer.path_key("src/[redacted].py")
    assert path not in key
    if key.startswith("\\u"):
        assert key.encode().decode("unicode_escape") != path


def test_escaped_envelope_after_closed_think_is_accepted():
    assert analyzer.extract_json('<think>draft</think> {"\\u0066indings": []}',
                                 envelope_key="findings") == {"findings": []}


@pytest.mark.parametrize("key", ["GH_TOKEN", "CODESITTER_GITHUB_TOKEN"])
@pytest.mark.parametrize("route", ["model", "fallback_model"])
def test_implicit_forge_alias_cannot_be_a_model_key(key, route):
    raw = raw_config()
    raw[route] = dict(raw["model"], key_env=key)
    with pytest.raises(ValidationError):
        config.RepoConfig.model_validate(raw)


@pytest.mark.parametrize("update", [{"shadow": "false"}, {"fix": {"enabled": "yes"}},
                                    {"model": {"seed": True}}])
def test_public_config_validation_preserves_boolean_boundaries(update):
    raw = raw_config()
    for key, value in deepcopy(update).items():
        if key == "model":
            raw[key].update(value)
        else:
            raw[key] = value
    with pytest.raises(ValidationError):
        config.RepoConfig.model_validate(raw)


def test_security_privacy_missing_evidence_caps_readiness():
    checked = set(capabilities.SCORING_CATEGORIES) - {"Security & Privacy"}
    assert capabilities.readiness_score({}, checked) <= capabilities.CAP_MISSING_CRITICAL


@pytest.mark.parametrize("stamp", ["2026-09-01", "2026-09-01T12:00:00", "nonsenseTnonsense"])
def test_incomplete_watermark_is_rejected(stamp):
    assert not state._valid_iso(stamp)


@pytest.mark.parametrize("bad", [{"open_ids": "bad"}, {"merged_since": "not-a-time"},
                                {"merged_since": "nonsenseTnonsense"}])
def test_scheduler_corrupt_aux_state_is_unknown(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(tiers, "STATE_DIR", tmp_path)
    data = {"version": state.STATE_VERSION, "prs": {}, **bad}
    (tmp_path / "owner__project.state.json").write_text(json.dumps(data))
    assert tiers._read_state("owner/project") is None


@pytest.mark.parametrize("adapter_cls", [GitHubAdapter, ForgejoAdapter])
def test_uncertain_own_marker_is_not_absence(adapter_cls, monkeypatch):
    forge = adapter_cls(config.ForgeBinding(role="primary", api_base="https://forge.invalid",
                                            token_env="TEST_FORGE_KEY"))
    forge.bot_login = "fl4write[bot]"
    monkeypatch.setattr(forge, "_paginated", lambda *a, **kw: iter([
        {"id": None, "body": "<!-- fl4write:v1:abc -->", "user": {"login": forge.bot_login}}]))
    with pytest.raises(ForgeError):
        forge.get_persistent_comment("owner/project", 1)


@pytest.mark.parametrize("value", [1, True, [], {}])
def test_file_content_wrong_type_returns_unavailable(value, monkeypatch):
    forge = GitHubAdapter(config.ForgeBinding(role="primary", api_base="https://forge.invalid",
                                            token_env="TEST_FORGE_KEY"))
    monkeypatch.setattr(forge, "_call", lambda *a, **kw: {"encoding": "base64", "content": value})
    assert forge.get_file("owner/project", "x.py", "a" * 40) is None


@pytest.mark.parametrize("mode", ["malformed", "full_cap"])
def test_issue_fallback_never_processes_partial_listing(mode):
    from fl4write.issues import collect_new_issues

    class PartialForge:
        def _paginated(self, *a, **kw):
            raise ForgeError("unavailable")

        def _call(self, *a, **kw):
            if mode == "malformed":
                return {"message": "unavailable"}
            return [{"number": n} for n in range(1, 101)]

    assert collect_new_issues(PartialForge(), "owner/project", 0) == []


@pytest.mark.parametrize("adapter_cls", [GitHubAdapter, ForgejoAdapter])
@pytest.mark.parametrize("row", [None, {"number": 1}])
@pytest.mark.parametrize("lane", ["open", "merged"])
def test_malformed_pr_listing_never_certifies_completeness(adapter_cls, row, lane, monkeypatch):
    forge = adapter_cls(config.ForgeBinding(role="primary", api_base="https://forge.invalid",
                                            token_env="TEST_FORGE_KEY"))
    if lane == "merged" and isinstance(row, dict):
        row = dict(row, merged=True, merged_at="2026-09-04T12:00:00Z")
    monkeypatch.setattr(forge, "_paginated", lambda *a, **kw: iter([row]))
    with pytest.raises(ForgeError):
        if lane == "open":
            forge.list_open_prs("owner/project")
        else:
            forge.list_merged_prs("owner/project", "2026-09-01T00:00:00Z")


@pytest.mark.parametrize("field,value", [("max_tokens", "4000"), ("temperature", "0.2"),
                                       ("seed", "1"), ("test_timeout", "240")])
def test_numeric_strings_are_not_public_schema_numbers(field, value):
    raw = raw_config()
    if field == "test_timeout":
        raw[field] = value
    else:
        raw["model"][field] = value
    with pytest.raises(ValidationError):
        config.RepoConfig.model_validate(raw)


@pytest.mark.parametrize("base", ["https://api.github.com:notaport", "https://api.github.com:99999",
                                 "https://:443"])
def test_invalid_forge_url_fails_at_configuration_boundary(base):
    raw = raw_config()
    raw["forges"]["github"]["api_base"] = base
    with pytest.raises(ValidationError):
        config.RepoConfig.model_validate(raw)
