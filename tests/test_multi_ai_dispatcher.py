"""Tests for the Multi-AI Dispatcher system."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.multi_ai.config import DispatcherConfig, load_dispatcher_config
from core.multi_ai.detection import (
    _verify_cli,
    detect_available_providers,
    get_cli_path,
    invalidate_cache,
    is_cli_available,
)
from core.multi_ai.dispatcher import (
    MultiAIDispatcher,
    _aggregate_results,
    _deduplicate_findings,
    _majority_verdict,
    dispatch_to_multiple_ais,
)
from core.multi_ai.output_parser import (
    extract_verdict,
    parse_provider_output,
)
from core.multi_ai.types import (
    AggregatedResult,
    DispatchStatus,
    Finding,
    ProviderName,
    ProviderResult,
)


# ============================================================
# types.py tests
# ============================================================

class TestProviderName:
    def test_values(self):
        assert ProviderName.CLAUDE.value == "claude"
        assert ProviderName.GEMINI.value == "gemini"
        assert ProviderName.CODEX.value == "codex"


class TestDispatchStatus:
    def test_values(self):
        assert DispatchStatus.SUCCESS.value == "success"
        assert DispatchStatus.TIMEOUT.value == "timeout"
        assert DispatchStatus.NOT_AVAILABLE.value == "not_available"
        assert DispatchStatus.ERROR.value == "error"


class TestFinding:
    def test_creation(self):
        f = Finding(
            provider="claude",
            severity="critical",
            category="bug",
            file="test.py",
            line=42,
            title="Bug found",
            suggestion="Fix it",
        )
        assert f.provider == "claude"
        assert f.severity == "critical"
        assert f.confidence == 0.0


class TestProviderResult:
    def test_default_values(self):
        r = ProviderResult(provider=ProviderName.CLAUDE, status=DispatchStatus.SUCCESS)
        assert r.raw_output == ""
        assert r.findings == []
        assert r.verdict == ""
        assert r.duration_seconds == 0.0


class TestAggregatedResult:
    def test_has_results_empty(self):
        r = AggregatedResult()
        assert r.has_results is False

    def test_has_results_with_success(self):
        r = AggregatedResult(providers_succeeded=["claude"])
        assert r.has_results is True


# ============================================================
# detection.py tests
# ============================================================

class TestCLIDetection:
    def setup_method(self):
        invalidate_cache()

    @patch("core.multi_ai.detection.shutil.which", return_value=None)
    def test_cli_not_available(self, mock_which):
        assert is_cli_available("nonexistent") is False

    @patch("core.multi_ai.detection._verify_cli", return_value=True)
    @patch("core.multi_ai.detection.shutil.which", return_value="/usr/bin/gemini")
    def test_cli_available(self, mock_which, mock_verify):
        assert is_cli_available("gemini") is True
        assert get_cli_path("gemini") == "/usr/bin/gemini"

    def test_invalidate_cache(self):
        invalidate_cache()
        # Should not raise

    @patch("core.multi_ai.detection.is_cli_available")
    def test_detect_available_providers_claude_only(self, mock_available):
        mock_available.return_value = False
        providers = detect_available_providers()
        assert ProviderName.CLAUDE in providers

    @patch("core.multi_ai.detection.subprocess.run")
    def test_verify_cli_timeout(self, mock_run):
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("gemini", 10)
        assert _verify_cli("/usr/bin/gemini") is False

    @patch("core.multi_ai.detection.subprocess.run")
    def test_verify_cli_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert _verify_cli("/usr/bin/gemini") is True

    @patch("core.multi_ai.detection.subprocess.run")
    def test_verify_cli_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert _verify_cli("/usr/bin/gemini") is False

    @patch("os.path.isfile", return_value=True)
    @patch("core.multi_ai.detection._verify_cli", return_value=True)
    @patch("core.multi_ai.detection.shutil.which", return_value="/usr/bin/gemini")
    def test_cache_reuse(self, mock_which, mock_verify, mock_isfile):
        invalidate_cache()
        path1 = get_cli_path("gemini")
        path2 = get_cli_path("gemini")
        assert path1 == path2
        # shutil.which should only be called once due to caching
        assert mock_which.call_count == 1

    @patch.dict("os.environ", {"GEMINI_CLI_PATH": "/custom/gemini"})
    @patch("core.multi_ai.detection._verify_cli", return_value=True)
    @patch("os.path.isfile", return_value=True)
    def test_env_var_override(self, mock_isfile, mock_verify):
        invalidate_cache()
        path = get_cli_path("gemini")
        assert path == "/custom/gemini"


# ============================================================
# config.py tests
# ============================================================

class TestDispatcherConfig:
    def test_default_config(self):
        config = DispatcherConfig()
        assert config.enabled is False
        assert config.providers == [ProviderName.CLAUDE]
        assert config.is_multi_ai is False

    def test_multi_ai_config(self):
        config = DispatcherConfig(
            providers=[ProviderName.CLAUDE, ProviderName.GEMINI]
        )
        assert config.is_multi_ai is True


class TestLoadDispatcherConfig:
    def test_default_no_spec_dir(self):
        config = load_dispatcher_config()
        assert config.enabled is False

    @patch.dict("os.environ", {"MULTI_AI_ENABLED": "true", "MULTI_AI_PROVIDERS": "claude,gemini"})
    def test_env_var_override(self):
        config = load_dispatcher_config()
        assert config.enabled is True
        assert ProviderName.GEMINI in config.providers

    def test_task_metadata_config(self, tmp_path):
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        metadata = {
            "multiAiConfig": {
                "enabled": True,
                "providers": ["claude", "codex"],
                "timeout": 600,
            }
        }
        (spec_dir / "task_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        with patch.dict("os.environ", {}, clear=False):
            # Remove env overrides if present
            import os
            os.environ.pop("MULTI_AI_ENABLED", None)
            os.environ.pop("MULTI_AI_PROVIDERS", None)
            config = load_dispatcher_config(spec_dir)

        assert config.enabled is True
        assert ProviderName.CODEX in config.providers
        assert config.timeout_seconds == 600

    @patch.dict("os.environ", {"MULTI_AI_ENABLED": "false"})
    def test_env_overrides_file(self, tmp_path):
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        metadata = {"multiAiConfig": {"enabled": True}}
        (spec_dir / "task_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        config = load_dispatcher_config(spec_dir)
        assert config.enabled is False  # env var takes precedence

    def test_claude_always_present(self):
        config = load_dispatcher_config()
        assert ProviderName.CLAUDE in config.providers


# ============================================================
# output_parser.py tests
# ============================================================

class TestOutputParser:
    def test_parse_json_array(self):
        output = '[{"severity": "critical", "file": "test.py", "line": 1, "title": "Bug", "suggestion": "Fix"}]'
        findings = parse_provider_output(output, "claude")
        assert len(findings) == 1
        assert findings[0].severity == "critical"
        assert findings[0].provider == "claude"

    def test_parse_markdown_wrapped(self):
        output = "Here are findings:\n```json\n[{\"severity\": \"major\", \"file\": \"a.py\", \"line\": 5, \"title\": \"Issue\", \"suggestion\": \"Fix\"}]\n```"
        findings = parse_provider_output(output, "gemini")
        assert len(findings) == 1
        assert findings[0].severity == "major"

    def test_parse_empty_array(self):
        findings = parse_provider_output("[]", "claude")
        assert findings == []

    def test_parse_empty_string(self):
        findings = parse_provider_output("", "claude")
        assert findings == []

    def test_parse_invalid_json(self):
        findings = parse_provider_output("not json at all", "claude")
        assert findings == []

    def test_parse_with_surrounding_text(self):
        output = "I found some issues:\n[\n{\"severity\": \"minor\", \"file\": \"b.py\", \"line\": 10, \"title\": \"Style\", \"suggestion\": \"Improve\"}\n]\nThat's all."
        findings = parse_provider_output(output, "codex")
        assert len(findings) == 1

    def test_parse_multiple_findings(self):
        output = json.dumps([
            {"severity": "critical", "file": "a.py", "line": 1, "title": "Bug1", "suggestion": "Fix1"},
            {"severity": "minor", "file": "b.py", "line": 2, "title": "Bug2", "suggestion": "Fix2"},
        ])
        findings = parse_provider_output(output, "claude")
        assert len(findings) == 2


class TestExtractVerdict:
    def test_approve(self):
        assert extract_verdict("The code looks good. APPROVED.") == "APPROVE"

    def test_reject(self):
        assert extract_verdict("REJECTED due to security issues") == "REJECT"

    def test_request_changes(self):
        assert extract_verdict("REQUEST CHANGES for the following...") == "REJECT"

    def test_pass(self):
        assert extract_verdict("All tests passed") == "APPROVE"

    def test_fail(self):
        assert extract_verdict("Build failed") == "REJECT"

    def test_empty(self):
        assert extract_verdict("") == ""

    def test_ambiguous(self):
        assert extract_verdict("Some observations about the code") == "COMMENT"


# ============================================================
# dispatcher.py tests
# ============================================================

class TestDeduplicate:
    def test_no_findings(self):
        deduped, high_conf = _deduplicate_findings([])
        assert deduped == []
        assert high_conf == []

    def test_single_finding(self):
        findings = [
            Finding("claude", "major", "bug", "a.py", 10, "Bug", "Fix"),
        ]
        deduped, high_conf = _deduplicate_findings(findings)
        assert len(deduped) == 1
        assert len(high_conf) == 0

    def test_two_providers_same_location(self):
        findings = [
            Finding("claude", "major", "bug", "a.py", 10, "Bug", "Fix"),
            Finding("gemini", "minor", "bug", "a.py", 11, "Bug2", "Fix2"),
        ]
        deduped, high_conf = _deduplicate_findings(findings)
        assert len(deduped) == 1  # Same bucket
        assert len(high_conf) == 1  # 2 providers = high confidence
        assert deduped[0].severity == "major"  # Highest severity

    def test_three_providers_escalation(self):
        # All lines in same bucket: 10//4=2, 11//4=2, 10//4=2
        findings = [
            Finding("claude", "minor", "bug", "a.py", 10, "Bug", "Fix"),
            Finding("gemini", "minor", "bug", "a.py", 11, "Bug2", "Fix2"),
            Finding("codex", "minor", "bug", "a.py", 10, "Bug3", "Fix3"),
        ]
        deduped, high_conf = _deduplicate_findings(findings)
        assert len(deduped) == 1
        assert deduped[0].severity == "critical"  # Escalated

    def test_different_files(self):
        findings = [
            Finding("claude", "major", "bug", "a.py", 10, "Bug", "Fix"),
            Finding("claude", "minor", "bug", "b.py", 10, "Bug2", "Fix2"),
        ]
        deduped, _ = _deduplicate_findings(findings)
        assert len(deduped) == 2  # Different files


class TestMajorityVerdict:
    def test_empty(self):
        assert _majority_verdict([]) == ""

    def test_single(self):
        assert _majority_verdict(["APPROVE"]) == "APPROVE"

    def test_majority(self):
        assert _majority_verdict(["APPROVE", "APPROVE", "REJECT"]) == "APPROVE"

    def test_tie_picks_first_max(self):
        result = _majority_verdict(["APPROVE", "REJECT"])
        assert result in ("APPROVE", "REJECT")


class TestAggregateResults:
    def test_all_success(self):
        results = [
            ProviderResult(
                provider=ProviderName.CLAUDE,
                status=DispatchStatus.SUCCESS,
                verdict="APPROVE",
            ),
            ProviderResult(
                provider=ProviderName.GEMINI,
                status=DispatchStatus.SUCCESS,
                verdict="APPROVE",
            ),
        ]
        agg = _aggregate_results(results)
        assert len(agg.providers_succeeded) == 2
        assert agg.consensus_verdict == "APPROVE"

    def test_mixed_results(self):
        results = [
            ProviderResult(
                provider=ProviderName.CLAUDE,
                status=DispatchStatus.SUCCESS,
                verdict="APPROVE",
            ),
            ProviderResult(
                provider=ProviderName.GEMINI,
                status=DispatchStatus.ERROR,
                error_message="Failed",
            ),
        ]
        agg = _aggregate_results(results)
        assert "claude" in agg.providers_succeeded
        assert "gemini" in agg.providers_failed


# ============================================================
# ultra_builder.py override tests
# ============================================================

class TestUltraBuilderOverrides:
    def test_new_override_keys_exist(self):
        from core.ultra_builder import _DEFAULT_OVERRIDES
        assert "multi_ai_dispatch" in _DEFAULT_OVERRIDES
        assert "init_quality_gate" in _DEFAULT_OVERRIDES
        assert "research_cross_validation" in _DEFAULT_OVERRIDES
        assert "plan_adversarial_review" in _DEFAULT_OVERRIDES
        assert "dev_subtask_review" in _DEFAULT_OVERRIDES
        assert "deliver_checkpoint" in _DEFAULT_OVERRIDES

    def test_all_defaults_true(self):
        from core.ultra_builder import _DEFAULT_OVERRIDES
        for key in ["multi_ai_dispatch", "init_quality_gate", "research_cross_validation",
                     "plan_adversarial_review", "dev_subtask_review", "deliver_checkpoint"]:
            assert _DEFAULT_OVERRIDES[key] is True
