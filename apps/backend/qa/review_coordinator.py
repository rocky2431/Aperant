"""
Ultra Builder Pro -- Review Coordinator
========================================

Aggregates findings from 6 parallel review agents, performs proximity-based
deduplication, severity escalation, and verdict calculation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Import ReviewFinding from ultra_review to avoid circular import issues
# at module level -- coordinate_findings receives raw dicts and creates
# ReviewFinding instances itself.


SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
PROXIMITY_BUCKET_SIZE = 4  # lines within same bucket are considered "same location"
ESCALATION_THRESHOLD = 3  # agents flagging same area -> escalate to critical


@dataclass
class CoordinatedReport:
    """Aggregated, deduplicated report with verdict."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    high_confidence: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = "APPROVE"  # APPROVE | COMMENT | REQUEST_CHANGES
    critical_count: int = 0
    major_count: int = 0
    minor_count: int = 0
    agent_stats: dict[str, int] = field(default_factory=dict)
    total_raw: int = 0
    total_deduped: int = 0


def _bucket_key(file: str, line: int) -> tuple[str, int]:
    """Create a proximity bucket key from file and line number."""
    return (file, line // PROXIMITY_BUCKET_SIZE)


def _severity_rank(severity: str) -> int:
    """Lower rank = higher severity."""
    return SEVERITY_ORDER.get(severity, 3)


def coordinate_findings(
    all_findings: dict[str, list[dict[str, Any]]],
) -> CoordinatedReport:
    """Aggregate, deduplicate, and compute verdict for review findings.

    Args:
        all_findings: Dict mapping agent_name -> list of raw finding dicts.
            Each finding dict has keys: severity, file, line, title, suggestion, category.

    Returns:
        CoordinatedReport with deduplicated findings and computed verdict.
    """
    report = CoordinatedReport()

    # Phase 1: Collect all findings and track per-agent stats
    # bucket_key -> list of (agent_name, finding_dict)
    buckets: dict[tuple[str, int], list[tuple[str, dict[str, Any]]]] = {}

    for agent_name, findings in all_findings.items():
        report.agent_stats[agent_name] = len(findings)
        report.total_raw += len(findings)

        for finding in findings:
            file_path = finding.get("file", "unknown")
            line_num = finding.get("line", 0)
            key = _bucket_key(file_path, line_num)

            if key not in buckets:
                buckets[key] = []
            buckets[key].append((agent_name, finding))

    # Phase 2: Deduplicate within each bucket
    for bucket_key, entries in buckets.items():
        # Collect unique reviewers for this bucket
        reviewers = {agent for agent, _ in entries}

        # Pick the highest-severity finding as representative
        entries.sort(key=lambda x: _severity_rank(x[1].get("severity", "minor")))
        best_agent, best_finding = entries[0]

        # Severity escalation: 3+ agents -> critical
        effective_severity = best_finding.get("severity", "minor")
        if len(reviewers) >= ESCALATION_THRESHOLD:
            effective_severity = "critical"

        deduped = {
            "reviewer": best_agent,
            "severity": effective_severity,
            "file": best_finding.get("file", "unknown"),
            "line": best_finding.get("line", 0),
            "title": best_finding.get("title", ""),
            "suggestion": best_finding.get("suggestion", ""),
            "category": best_finding.get("category", ""),
            "agreeing_reviewers": sorted(reviewers),
        }

        report.findings.append(deduped)

        # Track high-confidence (2+ reviewers agree)
        if len(reviewers) >= 2:
            report.high_confidence.append(deduped)

        # Count by severity
        if effective_severity == "critical":
            report.critical_count += 1
        elif effective_severity == "major":
            report.major_count += 1
        else:
            report.minor_count += 1

    report.total_deduped = len(report.findings)

    # Sort findings: critical first, then major, then minor
    report.findings.sort(key=lambda f: _severity_rank(f.get("severity", "minor")))
    report.high_confidence.sort(key=lambda f: _severity_rank(f.get("severity", "minor")))

    # Phase 3: Compute verdict
    if report.critical_count > 0:
        report.verdict = "REQUEST_CHANGES"
    elif report.major_count > 0:
        report.verdict = "COMMENT"
    else:
        report.verdict = "APPROVE"

    logger.info(
        "Coordinated review: %d raw -> %d deduped (%d critical, %d major, %d minor) -> %s",
        report.total_raw,
        report.total_deduped,
        report.critical_count,
        report.major_count,
        report.minor_count,
        report.verdict,
    )

    return report
