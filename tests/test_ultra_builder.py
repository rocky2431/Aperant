#!/usr/bin/env python3
"""
Tests for Ultra Builder Integration Module
=============================================

Tests core/ultra_builder.py pure functions:
- is_ultra_builder_enabled: reads task_metadata.json
- load_ultra_builder_overrides: reads .ultra-builder-overrides.json
- is_rule_enabled: combines global toggle with per-rule overrides

All functions are file-reading pure logic. Uses tmp_path for file system.
No mocks needed.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "backend"))

from core.ultra_builder import (
    is_ultra_builder_enabled,
    load_ultra_builder_overrides,
    is_rule_enabled,
    _DEFAULT_OVERRIDES,
)


# =============================================================================
# HELPERS
# =============================================================================


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# =============================================================================
# TESTS: is_ultra_builder_enabled
# =============================================================================


class TestIsUltraBuilderEnabled:

    def test_returns_false_when_metadata_missing(self, tmp_path: Path):
        assert is_ultra_builder_enabled(tmp_path) is False

    def test_returns_false_when_key_absent(self, tmp_path: Path):
        _write_json(tmp_path / "task_metadata.json", {"other": "data"})
        assert is_ultra_builder_enabled(tmp_path) is False

    def test_returns_false_when_disabled(self, tmp_path: Path):
        _write_json(tmp_path / "task_metadata.json", {"ultraBuilderEnabled": False})
        assert is_ultra_builder_enabled(tmp_path) is False

    def test_returns_true_when_enabled(self, tmp_path: Path):
        _write_json(tmp_path / "task_metadata.json", {"ultraBuilderEnabled": True})
        assert is_ultra_builder_enabled(tmp_path) is True

    def test_handles_malformed_json(self, tmp_path: Path):
        (tmp_path / "task_metadata.json").write_text("{broken json!!!", encoding="utf-8")
        assert is_ultra_builder_enabled(tmp_path) is False

    def test_truthy_value_coerced_to_true(self, tmp_path: Path):
        _write_json(tmp_path / "task_metadata.json", {"ultraBuilderEnabled": 1})
        assert is_ultra_builder_enabled(tmp_path) is True

    def test_falsy_value_coerced_to_false(self, tmp_path: Path):
        _write_json(tmp_path / "task_metadata.json", {"ultraBuilderEnabled": 0})
        assert is_ultra_builder_enabled(tmp_path) is False


# =============================================================================
# TESTS: load_ultra_builder_overrides
# =============================================================================


class TestLoadUltraBuilderOverrides:

    def test_returns_defaults_when_no_file(self, tmp_path: Path):
        overrides = load_ultra_builder_overrides(tmp_path)
        assert overrides == _DEFAULT_OVERRIDES

    def test_merges_user_overrides(self, tmp_path: Path):
        _write_json(
            tmp_path / ".ultra-builder-overrides.json",
            {"tdd_required": False, "evidence_verification": False},
        )
        overrides = load_ultra_builder_overrides(tmp_path)
        assert overrides["tdd_required"] is False
        assert overrides["evidence_verification"] is False
        # Unmodified keys retain defaults
        assert overrides["architecture_layers"] is True

    def test_ignores_unknown_keys(self, tmp_path: Path):
        _write_json(
            tmp_path / ".ultra-builder-overrides.json",
            {"unknown_future_key": True, "tdd_required": False},
        )
        overrides = load_ultra_builder_overrides(tmp_path)
        assert "unknown_future_key" not in overrides
        assert overrides["tdd_required"] is False

    def test_handles_malformed_json(self, tmp_path: Path):
        (tmp_path / ".ultra-builder-overrides.json").write_text(
            "not json!", encoding="utf-8"
        )
        overrides = load_ultra_builder_overrides(tmp_path)
        assert overrides == _DEFAULT_OVERRIDES

    def test_handles_non_dict_json(self, tmp_path: Path):
        (tmp_path / ".ultra-builder-overrides.json").write_text(
            '["array"]', encoding="utf-8"
        )
        overrides = load_ultra_builder_overrides(tmp_path)
        assert overrides == _DEFAULT_OVERRIDES


# =============================================================================
# TESTS: is_rule_enabled
# =============================================================================


class TestIsRuleEnabled:

    def test_returns_false_when_globally_disabled(self, tmp_path: Path):
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        # No task_metadata.json => ultra builder disabled
        assert is_rule_enabled(spec_dir, project_dir, "tdd_required") is False

    def test_returns_false_when_rule_overridden_to_false(self, tmp_path: Path):
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        _write_json(spec_dir / "task_metadata.json", {"ultraBuilderEnabled": True})

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_json(
            project_dir / ".ultra-builder-overrides.json",
            {"tdd_required": False},
        )

        assert is_rule_enabled(spec_dir, project_dir, "tdd_required") is False

    def test_returns_true_when_enabled_and_not_overridden(self, tmp_path: Path):
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        _write_json(spec_dir / "task_metadata.json", {"ultraBuilderEnabled": True})

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        # No overrides file

        assert is_rule_enabled(spec_dir, project_dir, "tdd_required") is True

    def test_returns_true_for_unknown_rule_when_enabled(self, tmp_path: Path):
        """Unknown rule names default to True (forward-compatible)."""
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        _write_json(spec_dir / "task_metadata.json", {"ultraBuilderEnabled": True})

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        assert is_rule_enabled(spec_dir, project_dir, "future_rule") is True
