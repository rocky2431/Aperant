"""
Ultra Builder Pro — TEST Cross-Verification
=============================================

After the 6-agent review, dispatches the same diff to external AI providers
(Gemini, Codex) for independent verification. Corroborated findings get
higher confidence; new findings are added to the report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CrossVerifyResult:
    """Result of cross-verification with external AI providers."""
    external_findings: dict[str, list[dict]] = field(default_factory=dict)
    corroborated: list[dict] = field(default_factory=list)
    new_findings: list[dict] = field(default_factory=list)


CROSS_VERIFY_PROMPT = """You are independently reviewing a code diff for quality issues.

## Diff
```diff
{diff_content}
```

## Instructions
Review the code changes for:
1. Bugs and logic errors
2. Security vulnerabilities
3. Missing error handling
4. Forbidden patterns (console.log, TODO/FIXME, hardcoded secrets)
5. Test quality issues

Respond with a JSON array of findings:
```json
[
  {{
    "severity": "critical|major|minor",
    "file": "path/to/file",
    "line": 42,
    "title": "Issue description",
    "suggestion": "How to fix",
    "category": "bug|security|error_handling|forbidden|test"
  }}
]
```
If no issues: `[]`
"""


async def run_cross_verification(
    project_dir: Path,
    spec_dir: Path,
    diff_context: str,
    ultra_findings: list[dict],
) -> CrossVerifyResult:
    """Run cross-verification of ultra review findings with external AIs.

    Args:
        project_dir: Project root directory
        spec_dir: Spec directory
        diff_context: The diff being reviewed
        ultra_findings: Existing findings from the 6-agent review

    Returns:
        CrossVerifyResult with corroborated and new findings
    """
    from core.ultra_builder import is_rule_enabled

    if not is_rule_enabled(spec_dir, project_dir, "multi_ai_dispatch"):
        return CrossVerifyResult()

    diff_context = diff_context[:50000]

    logger.info("Running TEST cross-verification")

    try:
        from core.multi_ai import dispatch_to_multiple_ais

        prompt = CROSS_VERIFY_PROMPT.format(diff_content=diff_context)
        result = await dispatch_to_multiple_ais(
            prompt, project_dir, spec_dir, timeout_seconds=120
        )

        cross_result = CrossVerifyResult()

        # Collect external findings (non-Claude)
        for provider_name, provider_result in result.provider_results.items():
            if provider_name == "claude":
                continue
            if provider_result.status.value == "success":
                cross_result.external_findings[provider_name] = [
                    {
                        "severity": f.severity,
                        "file": f.file,
                        "line": f.line,
                        "title": f.title,
                        "suggestion": f.suggestion,
                    }
                    for f in provider_result.findings
                ]

        # Cross-reference with ultra_findings
        ultra_keys = {
            (f.get("file", ""), f.get("line", 0) // 4)
            for f in ultra_findings
        }

        for ext_findings in cross_result.external_findings.values():
            for ef in ext_findings:
                key = (ef.get("file", ""), ef.get("line", 0) // 4)
                if key in ultra_keys:
                    cross_result.corroborated.append(ef)
                else:
                    cross_result.new_findings.append(ef)

        logger.info(
            "Cross-verification: %d external findings, %d corroborated, %d new",
            sum(len(v) for v in cross_result.external_findings.values()),
            len(cross_result.corroborated),
            len(cross_result.new_findings),
        )

        return cross_result

    except Exception as exc:
        logger.warning("TEST cross-verification error (non-blocking): %s", exc)
        return CrossVerifyResult()


def merge_cross_verify_findings(
    ultra_findings_list: list[dict],
    cross_result: CrossVerifyResult,
) -> list[dict]:
    """Merge cross-verification results into ultra review findings.

    Corroborated findings get severity upgraded. New findings are appended.

    Args:
        ultra_findings_list: Existing ultra review findings (list of dicts)
        cross_result: Cross-verification results

    Returns:
        Updated findings list
    """
    # Upgrade corroborated findings
    corroborated_keys = {
        (f.get("file", ""), f.get("line", 0) // 4)
        for f in cross_result.corroborated
    }

    for finding in ultra_findings_list:
        key = (finding.get("file", ""), finding.get("line", 0) // 4)
        if key in corroborated_keys:
            # Add cross-verification marker
            finding["cross_verified"] = True
            # Escalate minor -> major if externally confirmed
            if finding.get("severity") == "minor":
                finding["severity"] = "major"

    # Add genuinely new findings from external AIs
    for new_finding in cross_result.new_findings:
        ultra_findings_list.append({
            **new_finding,
            "reviewer": "external_ai",
            "cross_verified": True,
        })

    return ultra_findings_list
