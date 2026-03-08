"""
Ultra Builder Pro — Evidence Verification
==========================================

Extracts and validates evidence claims from QA reports.
Evidence is wrapped in structured markers for reliable parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


def _is_meaningful_evidence(text: str) -> bool:
    """Check that evidence content is substantive, not just filler.

    Requires at least 30 characters and multiple words to avoid
    trivially gamed evidence like "yes" or "it works".
    """
    stripped = text.strip()
    return len(stripped) >= 30 and len(stripped.split()) >= 5


@dataclass
class EvidenceClaim:
    """A single claim that requires evidence."""
    claim: str
    evidence: str | None = None
    verified: bool = False


@dataclass
class EvidenceReport:
    """Collection of evidence claims from a QA report."""
    claims: list[EvidenceClaim] = field(default_factory=list)

    @property
    def all_verified(self) -> bool:
        """Return True only when every claim has evidence."""
        return bool(self.claims) and all(c.verified for c in self.claims)

    @property
    def missing_claims(self) -> list[EvidenceClaim]:
        """Return claims that lack evidence."""
        return [c for c in self.claims if not c.verified]


# Expected evidence types that must be present for approval
REQUIRED_EVIDENCE_TYPES = {
    "tests": "Tests pass",
    "build": "Build succeeds",
}

# Optional evidence types (reported but not required for approval)
OPTIONAL_EVIDENCE_TYPES = {
    "e2e": "E2E tests pass",
    "coverage": "Coverage meets threshold",
    "lint": "Linting passes",
}

# Regex to match evidence blocks: <!-- EVIDENCE:type -->...<!-- /EVIDENCE -->
_EVIDENCE_PATTERN = re.compile(
    r'<!-- EVIDENCE:(\w+) -->\s*(.*?)\s*<!-- /EVIDENCE -->',
    re.DOTALL,
)


def extract_evidence(qa_report_path: Path) -> EvidenceReport:
    """Extract evidence blocks from a QA report markdown file.

    Looks for structured markers of the form:
        <!-- EVIDENCE:tests -->
        $ pytest tests/ -v
        ...
        5 passed, 0 failed
        <!-- /EVIDENCE -->

    Args:
        qa_report_path: Path to the qa_report.md file

    Returns:
        EvidenceReport with all found and missing claims
    """
    report = EvidenceReport()

    if not qa_report_path.exists():
        # No report at all — create claims for all required types as unverified
        for etype, description in REQUIRED_EVIDENCE_TYPES.items():
            report.claims.append(EvidenceClaim(claim=description))
        return report

    try:
        content = qa_report_path.read_text(encoding="utf-8")
    except OSError:
        for etype, description in REQUIRED_EVIDENCE_TYPES.items():
            report.claims.append(EvidenceClaim(claim=description))
        return report

    # Parse evidence blocks
    found_types: dict[str, str] = {}
    for match in _EVIDENCE_PATTERN.finditer(content):
        evidence_type = match.group(1).lower()
        evidence_content = match.group(2).strip()
        if evidence_content:
            found_types[evidence_type] = evidence_content

    # Check required evidence types
    for etype, description in REQUIRED_EVIDENCE_TYPES.items():
        evidence = found_types.get(etype)
        claim = EvidenceClaim(
            claim=description,
            evidence=evidence,
            verified=evidence is not None and _is_meaningful_evidence(evidence),
        )
        report.claims.append(claim)

    # Check optional evidence types (add if found)
    for etype, description in OPTIONAL_EVIDENCE_TYPES.items():
        if etype in found_types:
            evidence = found_types[etype]
            claim = EvidenceClaim(
                claim=description,
                evidence=evidence,
                verified=evidence is not None and _is_meaningful_evidence(evidence),
            )
            report.claims.append(claim)

    return report


def format_missing_evidence_feedback(report: EvidenceReport) -> str:
    """Format feedback for the QA fixer about missing evidence.

    Returns a markdown string describing what evidence is missing and
    how to provide it.
    """
    lines = [
        "## ULTRA BUILDER: EVIDENCE VERIFICATION FAILED",
        "",
        "The following claims lack required evidence:",
        "",
    ]

    for claim in report.missing_claims:
        lines.append(f"- **{claim.claim}**: No evidence provided")

    lines.extend([
        "",
        "### How to Provide Evidence",
        "",
        "Wrap actual command output in evidence markers:",
        "",
        "```markdown",
        "<!-- EVIDENCE:tests -->",
        "$ pytest tests/ -v",
        "...",
        "5 passed, 0 failed",
        "<!-- /EVIDENCE -->",
        "```",
        "",
        "Supported evidence types: " + ", ".join(
            list(REQUIRED_EVIDENCE_TYPES.keys()) + list(OPTIONAL_EVIDENCE_TYPES.keys())
        ),
    ])

    return "\n".join(lines)
