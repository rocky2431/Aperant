"""Tests for TEST Cross-Verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from qa.ultra_cross_verify import (
    CrossVerifyResult,
    merge_cross_verify_findings,
    run_cross_verification,
)


class TestCrossVerifyResult:
    def test_default(self):
        r = CrossVerifyResult()
        assert r.external_findings == {}
        assert r.corroborated == []
        assert r.new_findings == []


class TestMergeCrossVerifyFindings:
    def test_corroboration_upgrades_severity(self):
        ultra = [{"file": "a.py", "line": 10, "severity": "minor", "title": "Bug"}]
        cross = CrossVerifyResult(
            corroborated=[{"file": "a.py", "line": 10}],
        )
        result = merge_cross_verify_findings(ultra, cross)
        assert result[0]["severity"] == "major"
        assert result[0]["cross_verified"] is True

    def test_new_findings_appended(self):
        ultra = [{"file": "a.py", "line": 10, "severity": "minor", "title": "Bug"}]
        cross = CrossVerifyResult(
            new_findings=[{"file": "b.py", "line": 20, "severity": "major", "title": "New bug", "suggestion": "Fix"}],
        )
        result = merge_cross_verify_findings(ultra, cross)
        assert len(result) == 2
        assert result[1]["reviewer"] == "external_ai"


@pytest.mark.asyncio
class TestRunCrossVerification:
    async def test_disabled_returns_empty(self, tmp_path):
        result = await run_cross_verification(tmp_path, tmp_path, "", [])
        assert result.corroborated == []
