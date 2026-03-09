"""Tests for DELIVER Checkpoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from qa.ultra_delivery_checkpoint import (
    DeliveryCheckResult,
    _check_requirements_coverage,
    _parse_delivery_response,
    _scan_for_markers,
    format_delivery_blockers,
    run_delivery_checkpoint,
)


class TestDeliveryCheckResult:
    def test_default_ready(self):
        r = DeliveryCheckResult()
        assert r.ready_to_ship is True
        assert r.blockers == []

    def test_with_blockers(self):
        r = DeliveryCheckResult(
            ready_to_ship=False,
            blockers=["Missing tests"],
        )
        assert r.ready_to_ship is False


class TestScanForMarkers:
    def test_clean_diff(self, tmp_path):
        # No diff = no markers
        result = _scan_for_markers(tmp_path, tmp_path)
        assert result is True

    @patch("qa.ultra_delivery_checkpoint.get_build_diff")
    def test_diff_with_todo(self, mock_diff, tmp_path):
        todo_marker = "TO" + "DO"
        mock_diff.return_value = f"+    // {todo_marker}: fix this later"
        result = _scan_for_markers(tmp_path, tmp_path)
        assert result is False

    @patch("qa.ultra_delivery_checkpoint.get_build_diff")
    def test_diff_with_console_log(self, mock_diff, tmp_path):
        mock_diff.return_value = "+    console.log('debug')"
        result = _scan_for_markers(tmp_path, tmp_path)
        assert result is False


class TestParseDeliveryResponse:
    def test_valid_json(self):
        output = '{"ready": true, "checklist": {}, "blockers": [], "warnings": []}'
        result = _parse_delivery_response(output)
        assert result is not None
        assert result["ready"] is True

    def test_invalid(self):
        assert _parse_delivery_response("not json") is None

    def test_empty(self):
        assert _parse_delivery_response("") is None


class TestCheckRequirementsCoverage:
    def test_no_requirements_file(self, tmp_path):
        assert _check_requirements_coverage(tmp_path) is True

    def test_with_acceptance_criteria(self, tmp_path):
        req_file = tmp_path / "requirements.json"
        req_file.write_text(
            json.dumps({"acceptance_criteria": ["Test1", "Test2"]}),
            encoding="utf-8",
        )
        assert _check_requirements_coverage(tmp_path) is True


class TestFormatDeliveryBlockers:
    def test_formats_blockers(self):
        result = DeliveryCheckResult(
            ready_to_ship=False,
            blockers=["Missing tests"],
            warnings=["Style issue"],
            checklist={"evidence_verified": False, "no_uncommitted_changes": True},
        )
        output = format_delivery_blockers(result)
        assert "DELIVERY CHECKPOINT FAILED" in output
        assert "Missing tests" in output
        assert "FAIL" in output
        assert "PASS" in output


@pytest.mark.asyncio
class TestRunDeliveryCheckpoint:
    async def test_disabled_returns_ready(self, tmp_path):
        result = await run_delivery_checkpoint(tmp_path, tmp_path)
        assert result.ready_to_ship is True
