#!/usr/bin/env python3
"""
Tests for Evidence Verification Module
========================================

Tests qa/evidence.py pure functions:
- extract_evidence: parses EVIDENCE markers from QA reports
- _is_meaningful_evidence: validates evidence content is substantive
- EvidenceReport.all_verified: checks all claims are verified
- format_missing_evidence_feedback: renders markdown feedback

All functions under test are pure (file I/O uses tmp_path fixture).
No mocks needed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "backend"))

from qa.evidence import (
    EvidenceClaim,
    EvidenceReport,
    REQUIRED_EVIDENCE_TYPES,
    _is_meaningful_evidence,
    extract_evidence,
    format_missing_evidence_feedback,
)


# =============================================================================
# HELPERS
# =============================================================================


def _write_report(path: Path, content: str) -> Path:
    """Write a QA report file and return the path."""
    path.write_text(content, encoding="utf-8")
    return path


# =============================================================================
# TESTS: _is_meaningful_evidence (pure function)
# =============================================================================


class TestIsMeaningfulEvidence:

    def test_rejects_yes(self):
        assert _is_meaningful_evidence("yes") is False

    def test_rejects_ok(self):
        assert _is_meaningful_evidence("ok") is False

    def test_rejects_it_works(self):
        assert _is_meaningful_evidence("it works") is False

    def test_rejects_short_text(self):
        assert _is_meaningful_evidence("passed") is False

    def test_rejects_few_words_long_text(self):
        """30+ chars but fewer than 5 words should fail."""
        assert _is_meaningful_evidence("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ok") is False

    def test_accepts_substantive_evidence(self):
        text = "5 tests passed with 0 failures in 2.3 seconds"
        assert _is_meaningful_evidence(text) is True

    def test_accepts_build_output(self):
        text = "Build completed successfully with exit code 0 in 14s"
        assert _is_meaningful_evidence(text) is True

    def test_strips_whitespace(self):
        text = "   5 tests passed with 0 failures in 2.3 seconds   "
        assert _is_meaningful_evidence(text) is True


# =============================================================================
# TESTS: extract_evidence
# =============================================================================


class TestExtractEvidence:

    def test_valid_report_with_evidence(self, tmp_path: Path):
        report_path = tmp_path / "qa_report.md"
        _write_report(report_path, (
            "# QA Report\n\n"
            "<!-- EVIDENCE:tests -->\n"
            "$ pytest tests/ -v\n"
            "5 passed, 0 failed in 1.2 seconds total\n"
            "<!-- /EVIDENCE -->\n\n"
            "<!-- EVIDENCE:build -->\n"
            "$ npm run build\n"
            "Build succeeded with exit code 0 cleanly\n"
            "<!-- /EVIDENCE -->\n"
        ))

        report = extract_evidence(report_path)

        assert report.all_verified is True
        assert len(report.claims) >= 2

    def test_missing_evidence_yields_unverified(self, tmp_path: Path):
        report_path = tmp_path / "qa_report.md"
        _write_report(report_path, "# QA Report\nAll looks good.\n")

        report = extract_evidence(report_path)

        assert report.all_verified is False
        # Should have claims for all REQUIRED_EVIDENCE_TYPES
        assert len(report.claims) == len(REQUIRED_EVIDENCE_TYPES)
        assert all(not c.verified for c in report.claims)

    def test_nonexistent_file_all_unverified(self, tmp_path: Path):
        report_path = tmp_path / "nonexistent.md"

        report = extract_evidence(report_path)

        assert report.all_verified is False
        assert len(report.claims) == len(REQUIRED_EVIDENCE_TYPES)
        for claim in report.claims:
            assert claim.verified is False
            assert claim.evidence is None

    def test_partial_evidence(self, tmp_path: Path):
        """Only tests evidence provided, build missing."""
        report_path = tmp_path / "qa_report.md"
        _write_report(report_path, (
            "<!-- EVIDENCE:tests -->\n"
            "$ pytest tests/ -v\n"
            "10 passed, 0 failed in 3.5 seconds total\n"
            "<!-- /EVIDENCE -->\n"
        ))

        report = extract_evidence(report_path)

        assert report.all_verified is False
        tests_claim = next(c for c in report.claims if c.claim == "Tests pass")
        build_claim = next(c for c in report.claims if c.claim == "Build succeeds")
        assert tests_claim.verified is True
        assert build_claim.verified is False

    def test_trivial_evidence_rejected(self, tmp_path: Path):
        """Evidence that is too short / few words is marked unverified."""
        report_path = tmp_path / "qa_report.md"
        _write_report(report_path, (
            "<!-- EVIDENCE:tests -->\nyes\n<!-- /EVIDENCE -->\n"
            "<!-- EVIDENCE:build -->\nok\n<!-- /EVIDENCE -->\n"
        ))

        report = extract_evidence(report_path)

        assert report.all_verified is False

    def test_optional_evidence_included_when_present(self, tmp_path: Path):
        report_path = tmp_path / "qa_report.md"
        _write_report(report_path, (
            "<!-- EVIDENCE:tests -->\n"
            "$ pytest tests/ -v\n"
            "5 passed, 0 failed in 1.2 seconds total\n"
            "<!-- /EVIDENCE -->\n"
            "<!-- EVIDENCE:build -->\n"
            "$ npm run build\n"
            "Build succeeded with exit code 0 cleanly\n"
            "<!-- /EVIDENCE -->\n"
            "<!-- EVIDENCE:coverage -->\n"
            "Coverage is at 92 percent across all modules checked\n"
            "<!-- /EVIDENCE -->\n"
        ))

        report = extract_evidence(report_path)

        claim_names = [c.claim for c in report.claims]
        assert "Coverage meets threshold" in claim_names


# =============================================================================
# TESTS: EvidenceReport.all_verified
# =============================================================================


class TestEvidenceReportAllVerified:

    def test_all_verified_when_all_claims_pass(self):
        report = EvidenceReport(claims=[
            EvidenceClaim(claim="Tests pass", evidence="output", verified=True),
            EvidenceClaim(claim="Build succeeds", evidence="output", verified=True),
        ])
        assert report.all_verified is True

    def test_not_verified_when_any_fails(self):
        report = EvidenceReport(claims=[
            EvidenceClaim(claim="Tests pass", evidence="output", verified=True),
            EvidenceClaim(claim="Build succeeds", verified=False),
        ])
        assert report.all_verified is False

    def test_not_verified_when_empty(self):
        report = EvidenceReport(claims=[])
        assert report.all_verified is False

    def test_missing_claims_property(self):
        report = EvidenceReport(claims=[
            EvidenceClaim(claim="Tests pass", verified=True),
            EvidenceClaim(claim="Build succeeds", verified=False),
            EvidenceClaim(claim="Coverage", verified=False),
        ])
        missing = report.missing_claims
        assert len(missing) == 2
        assert all(not c.verified for c in missing)


# =============================================================================
# TESTS: format_missing_evidence_feedback
# =============================================================================


class TestFormatMissingEvidenceFeedback:

    def test_includes_missing_claim_titles(self):
        report = EvidenceReport(claims=[
            EvidenceClaim(claim="Tests pass", verified=False),
            EvidenceClaim(claim="Build succeeds", verified=False),
        ])

        feedback = format_missing_evidence_feedback(report)

        assert "Tests pass" in feedback
        assert "Build succeeds" in feedback

    def test_includes_header(self):
        report = EvidenceReport(claims=[
            EvidenceClaim(claim="Tests pass", verified=False),
        ])

        feedback = format_missing_evidence_feedback(report)

        assert "EVIDENCE VERIFICATION FAILED" in feedback

    def test_verified_claims_not_in_feedback(self):
        report = EvidenceReport(claims=[
            EvidenceClaim(claim="Tests pass", verified=True),
            EvidenceClaim(claim="Build succeeds", verified=False),
        ])

        feedback = format_missing_evidence_feedback(report)

        assert "Tests pass" not in feedback
        assert "Build succeeds" in feedback

    def test_includes_supported_evidence_types(self):
        report = EvidenceReport(claims=[
            EvidenceClaim(claim="Tests pass", verified=False),
        ])

        feedback = format_missing_evidence_feedback(report)

        assert "tests" in feedback
        assert "build" in feedback
