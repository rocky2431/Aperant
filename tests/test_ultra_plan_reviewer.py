"""Tests for PLAN Adversarial Review."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from spec.ultra_plan_reviewer import (
    PlanReviewResult,
    _parse_defense_response,
    run_adversarial_plan_review,
)


class TestPlanReviewResult:
    def test_default_approved(self):
        r = PlanReviewResult()
        assert r.approved is True
        assert r.challenges == []

    def test_with_unresolved(self):
        r = PlanReviewResult(approved=False, unresolved=[{"title": "Issue"}])
        assert r.approved is False


class TestParseDefenseResponse:
    def test_valid_array(self):
        output = '[{"challenge_title": "Test", "resolution": "defended", "rationale": "OK"}]'
        result = _parse_defense_response(output)
        assert len(result) == 1
        assert result[0]["resolution"] == "defended"

    def test_empty_output(self):
        assert _parse_defense_response("") == []

    def test_invalid_json(self):
        assert _parse_defense_response("not json") == []


@pytest.mark.asyncio
class TestRunAdversarialPlanReview:
    async def test_disabled_returns_approved(self, tmp_path):
        result = await run_adversarial_plan_review(tmp_path, tmp_path, {}, "")
        assert result.approved is True
