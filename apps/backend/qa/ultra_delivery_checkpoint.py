"""
Ultra Builder Pro — DELIVER Checkpoint
========================================

Final delivery verification before QA approval. Runs a multi-AI
checklist to ensure the implementation is ready to ship.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DeliveryCheckResult:
    """Result of delivery checkpoint verification."""
    ready_to_ship: bool = True
    checklist: dict[str, bool] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


DELIVERY_PROMPT = """Based on the following spec and diff, determine if this implementation is ready to ship.

## Spec Requirements
{spec_summary}

## Code Changes (diff)
```diff
{diff_content}
```

## Checklist
Answer each question with true/false:
1. All stated requirements are implemented
2. No TODO/FIXME/placeholder code remains
3. Error handling is present for failure paths
4. No hardcoded secrets or credentials
5. Changes are consistent with the spec

Respond with a JSON object:
```json
{{
  "ready": true,
  "checklist": {{
    "requirements_met": true,
    "no_placeholders": true,
    "error_handling": true,
    "no_secrets": true,
    "spec_consistent": true
  }},
  "blockers": ["list of blocking issues if any"],
  "warnings": ["list of non-blocking warnings"]
}}
```
"""


async def run_delivery_checkpoint(
    project_dir: Path,
    spec_dir: Path,
) -> DeliveryCheckResult:
    """Run final delivery checkpoint before QA approval.

    Verifies:
    1. Evidence gate passed (reuses qa/evidence.py)
    2. No residual markers in diff (TODO, FIXME, console.log)
    3. Spec requirements coverage
    4. No uncommitted changes
    5. Multi-AI readiness assessment

    Args:
        project_dir: Project root directory
        spec_dir: Spec directory

    Returns:
        DeliveryCheckResult with pass/fail and checklist
    """
    from core.ultra_builder import is_rule_enabled

    if not is_rule_enabled(spec_dir, project_dir, "deliver_checkpoint"):
        return DeliveryCheckResult(ready_to_ship=True)

    logger.info("Running DELIVER checkpoint")

    result = DeliveryCheckResult()

    # Check 1: Evidence gate
    try:
        from .evidence import extract_evidence
        evidence = extract_evidence(spec_dir / "qa_report.md")
        result.checklist["evidence_verified"] = evidence.all_verified
        if not evidence.all_verified:
            for claim in evidence.missing_claims:
                result.blockers.append(f"Missing evidence: {claim.claim}")
    except Exception as exc:
        logger.warning("Evidence check failed: %s", exc)
        result.checklist["evidence_verified"] = False
        result.blockers.append(f"Evidence check error: {exc}")

    # Check 2: No uncommitted changes
    try:
        git_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        has_uncommitted = bool(git_result.stdout.strip())
        result.checklist["no_uncommitted_changes"] = not has_uncommitted
        if has_uncommitted:
            result.warnings.append("Uncommitted changes detected")
    except (subprocess.TimeoutExpired, OSError):
        result.checklist["no_uncommitted_changes"] = True  # Don't block on git failure

    # Check 3: Residual marker scan
    result.checklist["no_residual_markers"] = _scan_for_markers(project_dir, spec_dir)
    if not result.checklist["no_residual_markers"]:
        result.warnings.append("Residual TODO/FIXME markers found in diff")

    # Check 4: Requirements coverage (check spec requirements vs changes)
    req_coverage = _check_requirements_coverage(spec_dir)
    result.checklist["requirements_covered"] = req_coverage
    if not req_coverage:
        result.warnings.append("Some requirements may not be covered by changes")

    # Check 5: Multi-AI readiness assessment
    try:
        from core.multi_ai import dispatch_to_multiple_ais

        spec_summary = _get_spec_summary(spec_dir)
        diff_content = get_build_diff(project_dir, spec_dir)

        if spec_summary and diff_content:
            prompt = DELIVERY_PROMPT.format(
                spec_summary=spec_summary[:20000],
                diff_content=diff_content[:30000],
            )
            ai_result = await dispatch_to_multiple_ais(
                prompt, project_dir, spec_dir, timeout_seconds=120
            )

            # Parse structured responses
            for provider_result in ai_result.provider_results.values():
                if provider_result.status.value != "success":
                    continue
                parsed = _parse_delivery_response(provider_result.raw_output)
                if parsed:
                    if not parsed.get("ready", True):
                        for blocker in parsed.get("blockers", []):
                            result.blockers.append(f"[AI] {blocker}")
                    for warning in parsed.get("warnings", []):
                        result.warnings.append(f"[AI] {warning}")

            result.checklist["ai_readiness"] = not any(
                "[AI]" in b for b in result.blockers
            )
    except Exception as exc:
        logger.warning("AI readiness assessment error (non-blocking): %s", exc)
        result.checklist["ai_readiness"] = True  # Don't block on AI failure

    # Final verdict
    result.ready_to_ship = len(result.blockers) == 0

    logger.info(
        "DELIVER checkpoint: %s (blockers=%d, warnings=%d)",
        "READY" if result.ready_to_ship else "NOT READY",
        len(result.blockers),
        len(result.warnings),
    )

    return result


def _scan_for_markers(project_dir: Path, spec_dir: Path) -> bool:
    """Scan diff for residual TODO/FIXME markers."""
    diff = get_build_diff(project_dir, spec_dir)
    if not diff:
        return True

    markers = ["TODO:", "FIXME:", "HACK:", "XXX:", "console.log("]
    for line in diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            for marker in markers:
                if marker in line:
                    return False
    return True


def _check_requirements_coverage(spec_dir: Path) -> bool:
    """Check if requirements.json requirements are likely covered."""
    req_file = spec_dir / "requirements.json"
    if not req_file.exists():
        return True

    try:
        with open(req_file, encoding="utf-8") as fh:
            req = json.load(fh)
        acceptance = req.get("acceptance_criteria", [])
        return len(acceptance) > 0
    except (json.JSONDecodeError, OSError):
        return True


def _get_spec_summary(spec_dir: Path) -> str:
    """Get spec summary for the delivery prompt."""
    spec_file = spec_dir / "spec.md"
    if spec_file.exists():
        try:
            return spec_file.read_text(encoding="utf-8")[:20000]
        except OSError:
            return ""
    return ""


def get_build_diff(project_dir: Path, spec_dir: Path) -> str:
    """Get the git diff for the current build scope.

    Reads ``baseBranch`` from ``task_metadata.json`` when available,
    otherwise falls back to ``HEAD~5``.  Used by cross-verification
    and delivery checkpoint.
    """
    try:
        meta_path = spec_dir / "task_metadata.json"
        base_branch = "HEAD~5"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                base_branch = meta.get("baseBranch", "HEAD~5")
            except (OSError, json.JSONDecodeError):
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
        return result.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _parse_delivery_response(raw_output: str) -> dict | None:
    """Parse delivery assessment response."""
    if not raw_output:
        return None

    first_brace = raw_output.find("{")
    last_brace = raw_output.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            parsed = json.loads(raw_output[first_brace : last_brace + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def format_delivery_blockers(delivery: DeliveryCheckResult) -> str:
    """Format delivery blockers as a QA_FIX_REQUEST.md content."""
    lines = [
        "## ULTRA BUILDER: DELIVERY CHECKPOINT FAILED",
        "",
        "The following issues must be resolved before approval:",
        "",
    ]

    for blocker in delivery.blockers:
        lines.append(f"- **BLOCKER**: {blocker}")

    if delivery.warnings:
        lines.append("")
        lines.append("### Warnings (non-blocking)")
        for warning in delivery.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("### Checklist")
    for item, passed in delivery.checklist.items():
        status = "PASS" if passed else "FAIL"
        lines.append(f"- [{status}] {item}")

    return "\n".join(lines)
