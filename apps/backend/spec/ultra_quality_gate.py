"""
Ultra Builder Pro -- INIT Quality Gate
=======================================

Multi-AI quality gate for spec pipeline phases. Runs completeness,
feasibility, and risk reviews in parallel after spec_writing and
planning phases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class QualityGateResult:
    """Result of an INIT quality gate check."""
    passed: bool = True
    findings: list[dict] = field(default_factory=list)
    confidence: str = "no_consensus"  # "consensus" | "majority" | "no_consensus"
    recommendations: list[str] = field(default_factory=list)


COMPLETENESS_PROMPT = """You are reviewing a software specification for COMPLETENESS.

## Phase Output
{phase_content}

## Review Instructions
Check whether the specification:
1. Covers all stated requirements
2. Defines clear acceptance criteria
3. Specifies error handling and edge cases
4. Has no ambiguous or missing sections

Respond with a JSON array of findings:
```json
[
  {{
    "severity": "critical|major|minor",
    "file": "spec file",
    "line": 0,
    "title": "Brief description",
    "suggestion": "How to fix",
    "category": "completeness"
  }}
]
```
If no issues: `[]`
"""

FEASIBILITY_PROMPT = """You are reviewing a software specification for TECHNICAL FEASIBILITY.

## Phase Output
{phase_content}

## Review Instructions
Check whether:
1. The proposed technical approach is implementable
2. Dependencies and integrations are realistic
3. Performance requirements are achievable
4. The scope is appropriate for the estimated complexity

Respond with a JSON array of findings (same format as above). If no issues: `[]`
"""

RISK_PROMPT = """You are reviewing a software specification for RISKS.

## Phase Output
{phase_content}

## Review Instructions
Identify:
1. Security risks in the proposed approach
2. Scalability concerns
3. Breaking changes or backward compatibility issues
4. External dependency risks (unmaintained libraries, API changes)

Respond with a JSON array of findings (same format as above). If no issues: `[]`
"""


async def run_init_quality_gate(
    spec_dir: Path,
    project_dir: Path,
    phase_name: str,
    phase_output_files: list[Path],
) -> QualityGateResult:
    """Run multi-AI quality gate on a completed spec pipeline phase.

    Dispatches completeness, feasibility, and risk prompts in parallel
    to available AI providers and aggregates results.

    Args:
        spec_dir: Spec directory
        project_dir: Project root directory
        phase_name: Name of the phase ("spec_writing" or "planning")
        phase_output_files: Output files from the phase to review

    Returns:
        QualityGateResult with pass/fail and findings
    """
    from core.ultra_builder import is_rule_enabled

    if not is_rule_enabled(spec_dir, project_dir, "init_quality_gate"):
        return QualityGateResult(passed=True)

    # Read phase output content
    phase_content = _read_phase_outputs(phase_output_files)
    if not phase_content.strip():
        logger.info("No phase output to review, skipping quality gate")
        return QualityGateResult(passed=True)

    # Truncate to prevent prompt overflow
    phase_content = phase_content[:50000]

    logger.info("Running INIT quality gate for phase: %s", phase_name)

    try:
        from core.multi_ai import dispatch_to_multiple_ais

        # Run 3 review perspectives in parallel via multi-AI dispatch
        import asyncio

        prompts = [
            ("completeness", COMPLETENESS_PROMPT.format(phase_content=phase_content)),
            ("feasibility", FEASIBILITY_PROMPT.format(phase_content=phase_content)),
            ("risk", RISK_PROMPT.format(phase_content=phase_content)),
        ]

        tasks = [
            dispatch_to_multiple_ais(prompt, project_dir, spec_dir, timeout_seconds=120)
            for _, prompt in prompts
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all findings
        all_findings: list[dict] = []
        recommendations: list[str] = []

        for i, result in enumerate(results):
            perspective = prompts[i][0]
            if isinstance(result, Exception):
                logger.warning("Quality gate %s failed: %s", perspective, result)
                continue

            for finding in result.findings:
                all_findings.append({
                    "perspective": perspective,
                    "provider": finding.provider,
                    "severity": finding.severity,
                    "title": finding.title,
                    "suggestion": finding.suggestion,
                    "category": finding.category or perspective,
                })

            if result.high_confidence_findings:
                for hcf in result.high_confidence_findings:
                    recommendations.append(f"[{perspective}] {hcf.title}: {hcf.suggestion}")

        # Determine pass/fail
        critical_count = sum(1 for f in all_findings if f.get("severity") == "critical")
        major_count = sum(1 for f in all_findings if f.get("severity") == "major")

        passed = critical_count == 0
        confidence = _compute_confidence(results)

        logger.info(
            "INIT quality gate: %s (critical=%d, major=%d, total=%d)",
            "PASSED" if passed else "FAILED",
            critical_count,
            major_count,
            len(all_findings),
        )

        return QualityGateResult(
            passed=passed,
            findings=all_findings,
            confidence=confidence,
            recommendations=recommendations,
        )

    except Exception as exc:
        logger.warning("INIT quality gate error (non-blocking): %s", exc)
        return QualityGateResult(passed=True)


def _read_phase_outputs(files: list[Path]) -> str:
    """Read and concatenate phase output files.

    Args:
        files: List of file paths to read

    Returns:
        Concatenated content string
    """
    parts = []
    for f in files:
        path = Path(f)
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                parts.append(f"### {path.name}\n\n{content}")
            except OSError as exc:
                logger.warning("Failed to read phase output %s: %s", path, exc)
    return "\n\n---\n\n".join(parts)


def _compute_confidence(results: list) -> str:
    """Compute confidence level from aggregated results.

    Args:
        results: List of AggregatedResult objects

    Returns:
        Confidence string: "consensus", "majority", or "no_consensus"
    """
    succeeded = 0
    for r in results:
        if not isinstance(r, Exception) and hasattr(r, "providers_succeeded"):
            succeeded += len(r.providers_succeeded)

    if succeeded >= 6:  # 3 perspectives x 2+ providers each
        return "consensus"
    elif succeeded >= 3:
        return "majority"
    return "no_consensus"


def write_gate_feedback(spec_dir: Path, gate_result: QualityGateResult) -> None:
    """Write quality gate feedback for the self_critique phase to consume.

    Args:
        spec_dir: Spec directory
        gate_result: Quality gate result
    """
    feedback_file = spec_dir / "quality_gate_feedback.md"
    lines = [
        "## Ultra Builder: Quality Gate Feedback\n",
        f"**Status**: {'PASSED' if gate_result.passed else 'FAILED'}",
        f"**Confidence**: {gate_result.confidence}\n",
    ]

    if gate_result.findings:
        lines.append(f"### Findings ({len(gate_result.findings)} total)\n")
        for f in gate_result.findings[:20]:
            lines.append(
                f"- **[{f.get('severity', 'minor').upper()}]** ({f.get('perspective', '')}) "
                f"{f.get('title', '')}  "
            )
            if f.get("suggestion"):
                lines.append(f"  Fix: {f['suggestion']}")

    if gate_result.recommendations:
        lines.append("\n### High-Confidence Recommendations\n")
        for rec in gate_result.recommendations[:10]:
            lines.append(f"- {rec}")

    feedback_file.write_text("\n".join(lines), encoding="utf-8")
