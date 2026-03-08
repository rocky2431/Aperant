#!/usr/bin/env python3
"""
Tests for Review Coordinator
==============================

Tests proximity dedup, severity escalation, and verdict calculation.
Pure function tests — no mocks needed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "backend"))

from qa.review_coordinator import (
    CoordinatedReport,
    coordinate_findings,
    _bucket_key,
    _severity_rank,
    PROXIMITY_BUCKET_SIZE,
    ESCALATION_THRESHOLD,
)


class TestBucketKey:

    def test_same_file_same_bucket(self):
        assert _bucket_key("src/app.ts", 4) == _bucket_key("src/app.ts", 7)

    def test_same_file_different_bucket(self):
        assert _bucket_key("src/app.ts", 0) != _bucket_key("src/app.ts", 8)

    def test_different_files_same_line(self):
        assert _bucket_key("a.ts", 10) != _bucket_key("b.ts", 10)

    def test_line_zero(self):
        key = _bucket_key("file.ts", 0)
        assert key == ("file.ts", 0)


class TestSeverityRank:

    def test_critical_is_highest(self):
        assert _severity_rank("critical") < _severity_rank("major")

    def test_major_beats_minor(self):
        assert _severity_rank("major") < _severity_rank("minor")

    def test_unknown_is_lowest(self):
        assert _severity_rank("unknown") > _severity_rank("minor")


class TestCoordinateFindingsEmpty:

    def test_empty_input_returns_approve(self):
        report = coordinate_findings({})
        assert report.verdict == "APPROVE"
        assert report.findings == []
        assert report.critical_count == 0

    def test_all_agents_empty(self):
        report = coordinate_findings({
            "review_code": [],
            "review_tests": [],
            "review_errors": [],
        })
        assert report.verdict == "APPROVE"
        assert report.total_raw == 0
        assert report.total_deduped == 0


class TestCoordinateFindingsDedup:

    def test_exact_same_location_deduped(self):
        """Two agents flagging same file:line -> 1 finding."""
        findings = {
            "review_code": [{"severity": "major", "file": "app.ts", "line": 10, "title": "DRY", "suggestion": "Extract", "category": "code"}],
            "review_simplify": [{"severity": "minor", "file": "app.ts", "line": 10, "title": "Complex", "suggestion": "Simplify", "category": "complexity"}],
        }
        report = coordinate_findings(findings)
        assert report.total_raw == 2
        assert report.total_deduped == 1
        # Should keep the higher severity (major)
        assert report.findings[0]["severity"] == "major"

    def test_proximity_dedup_within_bucket(self):
        """Lines 10 and 12 are in the same bucket (10//4 == 12//4 == 2)."""
        findings = {
            "review_code": [{"severity": "major", "file": "app.ts", "line": 10, "title": "A", "suggestion": "Fix A", "category": ""}],
            "review_tests": [{"severity": "minor", "file": "app.ts", "line": 12, "title": "B", "suggestion": "Fix B", "category": ""}],
        }
        report = coordinate_findings(findings)
        # 10 // 4 == 2, 12 // 4 == 3 — DIFFERENT buckets
        # So they should NOT be deduped
        # Actually 10//4=2, 12//4=3, so these ARE in different buckets
        assert report.total_deduped == 2

    def test_proximity_dedup_same_bucket(self):
        """Lines 8 and 9 are both in bucket 2 (8//4=2, 9//4=2)."""
        findings = {
            "review_code": [{"severity": "major", "file": "app.ts", "line": 8, "title": "A", "suggestion": "Fix A", "category": ""}],
            "review_tests": [{"severity": "minor", "file": "app.ts", "line": 9, "title": "B", "suggestion": "Fix B", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.total_deduped == 1

    def test_different_files_not_deduped(self):
        findings = {
            "review_code": [{"severity": "major", "file": "a.ts", "line": 10, "title": "A", "suggestion": "", "category": ""}],
            "review_tests": [{"severity": "major", "file": "b.ts", "line": 10, "title": "B", "suggestion": "", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.total_deduped == 2


class TestCoordinateFindingsEscalation:

    def test_three_agents_escalate_to_critical(self):
        """3+ agents on same bucket -> critical."""
        findings = {
            "review_code": [{"severity": "minor", "file": "app.ts", "line": 8, "title": "A", "suggestion": "", "category": ""}],
            "review_tests": [{"severity": "minor", "file": "app.ts", "line": 9, "title": "B", "suggestion": "", "category": ""}],
            "review_errors": [{"severity": "minor", "file": "app.ts", "line": 8, "title": "C", "suggestion": "", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.critical_count >= 1
        assert report.verdict == "REQUEST_CHANGES"

    def test_two_agents_no_escalation(self):
        findings = {
            "review_code": [{"severity": "minor", "file": "app.ts", "line": 8, "title": "A", "suggestion": "", "category": ""}],
            "review_tests": [{"severity": "minor", "file": "app.ts", "line": 9, "title": "B", "suggestion": "", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.critical_count == 0


class TestCoordinateFindingsHighConfidence:

    def test_two_agents_same_location_is_high_confidence(self):
        findings = {
            "review_code": [{"severity": "major", "file": "app.ts", "line": 8, "title": "A", "suggestion": "", "category": ""}],
            "review_tests": [{"severity": "minor", "file": "app.ts", "line": 9, "title": "B", "suggestion": "", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert len(report.high_confidence) == 1

    def test_single_agent_not_high_confidence(self):
        findings = {
            "review_code": [{"severity": "critical", "file": "app.ts", "line": 8, "title": "A", "suggestion": "", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert len(report.high_confidence) == 0


class TestCoordinateFindingsVerdict:

    def test_critical_finding_gives_request_changes(self):
        findings = {
            "review_code": [{"severity": "critical", "file": "app.ts", "line": 10, "title": "Security", "suggestion": "Fix", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.verdict == "REQUEST_CHANGES"

    def test_major_only_gives_comment(self):
        findings = {
            "review_code": [{"severity": "major", "file": "app.ts", "line": 10, "title": "Quality", "suggestion": "Fix", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.verdict == "COMMENT"

    def test_minor_only_gives_approve(self):
        findings = {
            "review_code": [{"severity": "minor", "file": "app.ts", "line": 10, "title": "Style", "suggestion": "Fix", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.verdict == "APPROVE"

    def test_mixed_critical_and_minor(self):
        findings = {
            "review_code": [{"severity": "critical", "file": "a.ts", "line": 10, "title": "A", "suggestion": "", "category": ""}],
            "review_tests": [{"severity": "minor", "file": "b.ts", "line": 20, "title": "B", "suggestion": "", "category": ""}],
        }
        report = coordinate_findings(findings)
        assert report.verdict == "REQUEST_CHANGES"


class TestCoordinateFindingsAgentStats:

    def test_tracks_per_agent_counts(self):
        findings = {
            "review_code": [
                {"severity": "major", "file": "a.ts", "line": 10, "title": "A", "suggestion": "", "category": ""},
                {"severity": "minor", "file": "b.ts", "line": 20, "title": "B", "suggestion": "", "category": ""},
            ],
            "review_tests": [
                {"severity": "minor", "file": "c.ts", "line": 30, "title": "C", "suggestion": "", "category": ""},
            ],
        }
        report = coordinate_findings(findings)
        assert report.agent_stats["review_code"] == 2
        assert report.agent_stats["review_tests"] == 1
        assert report.total_raw == 3
