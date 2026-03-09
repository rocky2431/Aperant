"""Tests for INIT Quality Gate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from spec.ultra_quality_gate import (
    QualityGateResult,
    _read_phase_outputs,
    run_init_quality_gate,
    write_gate_feedback,
)


class TestQualityGateResult:
    def test_default_passed(self):
        r = QualityGateResult()
        assert r.passed is True
        assert r.findings == []

    def test_failed(self):
        r = QualityGateResult(passed=False, findings=[{"severity": "critical"}])
        assert r.passed is False


class TestReadPhaseOutputs:
    def test_reads_existing_files(self, tmp_path):
        f1 = tmp_path / "spec.md"
        f1.write_text("# Spec content", encoding="utf-8")
        content = _read_phase_outputs([f1])
        assert "Spec content" in content

    def test_handles_missing_files(self, tmp_path):
        content = _read_phase_outputs([tmp_path / "nonexistent.md"])
        assert content == ""


class TestWriteGateFeedback:
    def test_writes_feedback(self, tmp_path):
        gate = QualityGateResult(
            passed=False,
            findings=[{"severity": "critical", "perspective": "completeness", "title": "Missing req", "suggestion": "Add it"}],
            recommendations=["Fix the thing"],
        )
        write_gate_feedback(tmp_path, gate)
        feedback = (tmp_path / "quality_gate_feedback.md").read_text(encoding="utf-8")
        assert "FAILED" in feedback
        assert "Missing req" in feedback


@pytest.mark.asyncio
class TestRunInitQualityGate:
    async def test_disabled_returns_passed(self, tmp_path):
        # No task_metadata.json = Ultra Builder disabled
        result = await run_init_quality_gate(tmp_path, tmp_path, "spec_writing", [])
        assert result.passed is True

    async def test_no_output_files_returns_passed(self, tmp_path):
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        (spec_dir / "task_metadata.json").write_text(
            json.dumps({"ultraBuilderEnabled": True}), encoding="utf-8"
        )
        result = await run_init_quality_gate(spec_dir, tmp_path, "spec_writing", [])
        assert result.passed is True
