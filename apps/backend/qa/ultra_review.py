"""
Ultra Builder Pro — 6-Agent Parallel Review
=============================================

Runs 6 specialized review agents concurrently to analyze code quality,
then aggregates and deduplicates findings into a unified report.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.client import create_client
from core.ultra_builder import is_ultra_builder_enabled
from phase_config import get_thinking_kwargs_for_model, resolve_model_id

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "ultra_review"

# Use lightweight model for review agents (cost optimization)
REVIEW_MODEL_SHORT = "haiku"
REVIEW_THINKING_LEVEL = "low"


@dataclass
class ReviewFinding:
    """A single finding from a review agent."""

    reviewer: str
    severity: str  # critical, major, minor
    file: str
    line: int
    title: str
    suggestion: str
    category: str = ""


@dataclass
class UltraReviewReport:
    """Aggregated report from all 6 review agents."""

    findings: list[ReviewFinding] = field(default_factory=list)
    high_confidence_findings: list[ReviewFinding] = field(default_factory=list)
    has_critical: bool = False
    agent_results: dict[str, Any] = field(default_factory=dict)
    error_agents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [
                {
                    "reviewer": f.reviewer,
                    "severity": f.severity,
                    "file": f.file,
                    "line": f.line,
                    "title": f.title,
                    "suggestion": f.suggestion,
                    "category": f.category,
                }
                for f in self.findings
            ],
            "high_confidence_findings": [
                {
                    "reviewer": f.reviewer,
                    "severity": f.severity,
                    "file": f.file,
                    "line": f.line,
                    "title": f.title,
                    "suggestion": f.suggestion,
                }
                for f in self.high_confidence_findings
            ],
            "has_critical": self.has_critical,
            "error_agents": self.error_agents,
        }


REVIEW_AGENTS = [
    "review_code",
    "review_tests",
    "review_errors",
    "review_types",
    "review_comments",
    "review_simplify",
]


async def _run_single_review(
    project_dir: Path,
    spec_dir: Path,
    agent_name: str,
    diff_context: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Run a single review agent and return its findings."""
    prompt_file = PROMPTS_DIR / f"{agent_name}.md"
    if not prompt_file.exists():
        logger.warning("Review prompt not found: %s", prompt_file)
        return agent_name, []

    prompt = prompt_file.read_text(encoding="utf-8")
    prompt += f"\n\n## CODE TO REVIEW\n\n```diff\n{diff_context[:50000]}\n```\n"
    prompt += """
\n## OUTPUT FORMAT

You MUST respond with ONLY a JSON array of findings. No other text.

```json
[
  {
    "severity": "critical|major|minor",
    "file": "path/to/file.ts",
    "line": 42,
    "title": "Brief description",
    "suggestion": "How to fix",
    "category": "category_name"
  }
]
```

If no issues found, respond with: `[]`
"""

    model_id = resolve_model_id(REVIEW_MODEL_SHORT)
    thinking_kwargs = get_thinking_kwargs_for_model(model_id, REVIEW_THINKING_LEVEL)

    try:
        client = create_client(
            project_dir,
            spec_dir,
            model_id,
            agent_type="qa_reviewer",
            **thinking_kwargs,
        )

        response_text = ""
        async with client:
            await client.query(prompt)
            async for msg in client.receive_response():
                msg_type = type(msg).__name__
                if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        block_type = type(block).__name__
                        if block_type == "TextBlock" and hasattr(block, "text"):
                            response_text += block.text

        findings = _parse_findings(response_text)
        return agent_name, findings

    except Exception as exc:
        logger.warning("Review agent %s failed: %s", agent_name, exc)
        raise  # Let caller track as error_agent via asyncio.gather


def _parse_findings(response: str) -> list[dict[str, Any]]:
    """Extract JSON findings array from agent response."""
    # Try to find a balanced JSON array — match from first [ to last ]
    first_bracket = response.find("[")
    last_bracket = response.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        try:
            parsed = json.loads(response[first_bracket : last_bracket + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


def _deduplicate_findings(
    all_findings: dict[str, list[dict[str, Any]]],
) -> UltraReviewReport:
    """Deduplicate findings across agents and compute confidence scores."""
    report = UltraReviewReport()

    # Track findings by (file, line) for dedup
    location_counts: dict[tuple[str, int], list[ReviewFinding]] = {}

    for agent_name, findings in all_findings.items():
        report.agent_results[agent_name] = len(findings)
        for f in findings:
            finding = ReviewFinding(
                reviewer=agent_name,
                severity=f.get("severity", "minor"),
                file=f.get("file", "unknown"),
                line=f.get("line", 0),
                title=f.get("title", ""),
                suggestion=f.get("suggestion", ""),
                category=f.get("category", ""),
            )
            report.findings.append(finding)

            if finding.severity == "critical":
                report.has_critical = True

            # Track location for cross-agent agreement
            loc_key = (finding.file, finding.line)
            if loc_key not in location_counts:
                location_counts[loc_key] = []
            location_counts[loc_key].append(finding)

    # High confidence: 2+ agents flagged same location
    severity_order = {"critical": 0, "major": 1, "minor": 2}
    for loc_findings in location_counts.values():
        if len(loc_findings) >= 2:
            # Use the highest severity finding as representative
            loc_findings.sort(key=lambda x: severity_order.get(x.severity, 3))
            report.high_confidence_findings.append(loc_findings[0])

    return report


async def run_ultra_review(
    project_dir: Path,
    spec_dir: Path,
) -> UltraReviewReport:
    """Run all 6 review agents in parallel and aggregate results.

    Returns an UltraReviewReport with deduplicated, confidence-scored findings.
    """
    if not is_ultra_builder_enabled(spec_dir):
        return UltraReviewReport()

    logger.info("Starting Ultra Builder 6-agent parallel review")

    # Get the diff to review — use base branch if available, fall back gracefully
    diff_context = ""
    try:
        # Try reading base branch from task metadata
        import json as _json
        meta_path = spec_dir / "task_metadata.json"
        base_branch = "HEAD~5"
        if meta_path.exists():
            try:
                meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                base_branch = meta.get("baseBranch", "HEAD~5")
            except (OSError, _json.JSONDecodeError):
                pass

        result = subprocess.run(
            ["git", "diff", f"{base_branch}...HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        diff_context = result.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Fallback: if base branch diff failed (shallow clone, missing ref), try HEAD~5
    if not diff_context.strip():
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD~5...HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            diff_context = result.stdout or ""
        except (subprocess.TimeoutExpired, OSError):
            diff_context = ""

    if not diff_context.strip():
        logger.info("No diff to review, skipping Ultra Review")
        return UltraReviewReport()

    # Launch all 6 agents in parallel
    tasks = [
        _run_single_review(project_dir, spec_dir, agent_name, diff_context)
        for agent_name in REVIEW_AGENTS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results
    all_findings: dict[str, list[dict[str, Any]]] = {}
    error_agents: list[str] = []

    for i, result in enumerate(results):
        agent_name = REVIEW_AGENTS[i]
        if isinstance(result, Exception):
            logger.warning("Agent %s raised: %s", agent_name, result)
            error_agents.append(agent_name)
        elif isinstance(result, tuple):
            name, findings = result
            all_findings[name] = findings
        else:
            error_agents.append(agent_name)

    # Deduplicate and aggregate
    report = _deduplicate_findings(all_findings)
    report.error_agents = error_agents

    logger.info(
        "Ultra Review complete: %d findings (%d critical, %d high-confidence)",
        len(report.findings),
        sum(1 for f in report.findings if f.severity == "critical"),
        len(report.high_confidence_findings),
    )

    return report


def write_ultra_review_context(spec_dir: Path, report: UltraReviewReport) -> None:
    """Write review findings as context for the QA reviewer agent."""
    output_path = spec_dir / "ultra_review_report.json"
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2)

    # Also write a markdown summary for injection into QA context
    summary_path = spec_dir / "ultra_review_summary.md"
    lines = ["## Ultra Builder Review Findings\n"]

    if report.has_critical:
        lines.append(
            "**CRITICAL ISSUES DETECTED** — These MUST be fixed before approval.\n"
        )

    if report.high_confidence_findings:
        lines.append("### High-Confidence Findings (multiple reviewers agree)\n")
        for f in report.high_confidence_findings:
            lines.append(
                f"- **[{f.severity.upper()}]** `{f.file}:{f.line}` — {f.title}"
            )
            lines.append(f"  Suggestion: {f.suggestion}\n")

    if report.findings:
        lines.append(f"\n### All Findings ({len(report.findings)} total)\n")
        for f in report.findings[:20]:  # Limit to top 20
            lines.append(
                f"- **[{f.severity}]** `{f.file}:{f.line}` ({f.reviewer}) — {f.title}"
            )

    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
