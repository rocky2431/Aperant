"""
Ultra Builder Pro — DEV Subtask Review
========================================

Lightweight multi-AI review of each subtask's diff before entering QA.
Catches bugs and forbidden patterns early.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DevReviewResult:
    """Result of a dev subtask review."""
    has_blockers: bool = False
    findings: list[dict] = field(default_factory=list)
    auto_fixable: list[dict] = field(default_factory=list)


DEV_REVIEW_PROMPT = """Review this code diff for blocking issues ONLY.

## Diff
```diff
{diff_content}
```

## Focus Areas (ONLY report blockers)
1. Obvious bugs (null dereference, off-by-one, missing await)
2. Security issues (injection, hardcoded secrets, missing auth)
3. Forbidden patterns (console.log in production, TODO/FIXME, mock in tests)

DO NOT report style issues, naming suggestions, or minor improvements.

Respond with a JSON array of BLOCKER findings only:
```json
[
  {{
    "severity": "critical|major",
    "file": "path/to/file",
    "line": 42,
    "title": "Bug description",
    "suggestion": "How to fix",
    "category": "bug|security|forbidden_pattern"
  }}
]
```
If no blockers: `[]`
"""


async def run_dev_subtask_review(
    project_dir: Path,
    spec_dir: Path,
    subtask_id: str,
    commit_before: str | None,
    commit_after: str | None,
) -> DevReviewResult:
    """Run lightweight multi-AI review on a subtask's changes.

    Args:
        project_dir: Project root directory
        spec_dir: Spec directory
        subtask_id: The subtask that was completed
        commit_before: Git commit hash before the subtask
        commit_after: Git commit hash after the subtask

    Returns:
        DevReviewResult with findings
    """
    from core.ultra_builder import is_rule_enabled

    if not is_rule_enabled(spec_dir, project_dir, "dev_subtask_review"):
        return DevReviewResult()

    # Get the diff for this subtask
    diff_content = _get_subtask_diff(project_dir, commit_before, commit_after)
    if not diff_content.strip():
        return DevReviewResult()

    # Truncate large diffs
    diff_content = diff_content[:50000]

    logger.info("Running DEV subtask review for %s", subtask_id)

    try:
        from core.multi_ai import dispatch_to_multiple_ais

        prompt = DEV_REVIEW_PROMPT.format(diff_content=diff_content)
        result = await dispatch_to_multiple_ais(
            prompt, project_dir, spec_dir, timeout_seconds=90
        )

        findings = []
        for finding in result.findings:
            findings.append({
                "provider": finding.provider,
                "severity": finding.severity,
                "file": finding.file,
                "line": finding.line,
                "title": finding.title,
                "suggestion": finding.suggestion,
                "category": finding.category,
            })

        has_blockers = any(
            f.get("severity") in ("critical", "major") for f in findings
        )

        logger.info(
            "DEV review for %s: %d findings, blockers=%s",
            subtask_id, len(findings), has_blockers,
        )

        return DevReviewResult(
            has_blockers=has_blockers,
            findings=findings,
        )

    except Exception as exc:
        logger.warning("DEV subtask review error (non-blocking): %s", exc)
        return DevReviewResult()


def _get_subtask_diff(
    project_dir: Path,
    commit_before: str | None,
    commit_after: str | None,
) -> str:
    """Get the git diff between two commits.

    Args:
        project_dir: Project root directory
        commit_before: Starting commit
        commit_after: Ending commit

    Returns:
        Diff text
    """
    if not commit_before or not commit_after:
        return ""

    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_before}...{commit_after}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""
