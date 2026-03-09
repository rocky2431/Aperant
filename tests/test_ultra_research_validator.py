"""Tests for RESEARCH Cross-Validation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from spec.ultra_research_validator import (
    ResearchValidation,
    _parse_validation_response,
    annotate_research,
    cross_validate_research,
)


class TestResearchValidation:
    def test_default(self):
        v = ResearchValidation()
        assert v.confidence_score == 0.0
        assert v.validated_findings == []


class TestParseValidationResponse:
    def test_valid_json(self):
        output = '{"validated": [{"finding": "test"}], "unconfirmed": [], "contradictions": []}'
        result = _parse_validation_response(output)
        assert result is not None
        assert len(result["validated"]) == 1

    def test_invalid_json(self):
        result = _parse_validation_response("not json")
        assert result is None

    def test_empty(self):
        result = _parse_validation_response("")
        assert result is None


class TestAnnotateResearch:
    def test_annotates_file(self, tmp_path):
        research_file = tmp_path / "research.json"
        research_file.write_text(json.dumps({"findings": []}), encoding="utf-8")

        validation = ResearchValidation(
            confidence_score=0.8,
            validated_findings=[{"finding": "test"}],
            contradictions=[{"finding": "wrong", "actual": "right"}],
        )
        annotate_research(research_file, validation)

        data = json.loads(research_file.read_text(encoding="utf-8"))
        assert "_validation" in data
        assert data["_validation"]["confidence_score"] == 0.8

    def test_handles_missing_file(self, tmp_path):
        annotate_research(tmp_path / "nonexistent.json", ResearchValidation())


@pytest.mark.asyncio
class TestCrossValidateResearch:
    async def test_disabled_returns_high_confidence(self, tmp_path):
        result = await cross_validate_research(tmp_path, tmp_path, {})
        assert result.confidence_score == 1.0
