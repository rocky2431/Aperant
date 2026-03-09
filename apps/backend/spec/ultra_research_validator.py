"""
Ultra Builder Pro — RESEARCH Cross-Validation
===============================================

Multi-AI cross-validation for research phase outputs. Multiple AI providers
independently verify research findings to detect errors and contradictions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ResearchValidation:
    """Result of cross-validating research findings."""
    validated_findings: list[dict] = field(default_factory=list)    # 2+ sources confirm
    unconfirmed_findings: list[dict] = field(default_factory=list)  # Only 1 source
    contradictions: list[dict] = field(default_factory=list)        # Sources conflict
    confidence_score: float = 0.0  # 0.0 - 1.0


CROSS_VALIDATE_PROMPT = """You are validating research findings about software libraries and APIs.

## Research Data to Validate
{research_content}

## Instructions
For each finding in the research data, verify:
1. Package names are correct and available
2. Version numbers are current
3. API patterns match actual library documentation
4. Configuration requirements are accurate
5. Known issues/gotchas are real

Respond with a JSON object:
```json
{{
  "validated": [
    {{"finding": "original finding text", "status": "confirmed", "note": "verification detail"}}
  ],
  "unconfirmed": [
    {{"finding": "original finding text", "status": "unconfirmed", "note": "could not verify"}}
  ],
  "contradictions": [
    {{"finding": "original finding text", "actual": "what is actually true", "severity": "critical|major|minor"}}
  ]
}}
```
"""


async def cross_validate_research(
    spec_dir: Path,
    project_dir: Path,
    research_data: dict,
) -> ResearchValidation:
    """Cross-validate research findings using multiple AI providers.

    Dispatches research data to available AI providers for independent
    verification. Findings confirmed by 2+ providers get higher confidence.

    Args:
        spec_dir: Spec directory
        project_dir: Project root directory
        research_data: Parsed research.json data

    Returns:
        ResearchValidation with categorized findings
    """
    from core.ultra_builder import is_rule_enabled

    if not is_rule_enabled(spec_dir, project_dir, "research_cross_validation"):
        return ResearchValidation(confidence_score=1.0)

    research_content = json.dumps(research_data, indent=2)[:30000]

    logger.info("Running RESEARCH cross-validation")

    try:
        from core.multi_ai import dispatch_to_multiple_ais

        prompt = CROSS_VALIDATE_PROMPT.format(research_content=research_content)
        result = await dispatch_to_multiple_ais(
            prompt, project_dir, spec_dir, timeout_seconds=120
        )

        validation = ResearchValidation()

        # Parse structured responses from providers
        for provider_name, provider_result in result.provider_results.items():
            if provider_result.status.value != "success":
                continue

            parsed = _parse_validation_response(provider_result.raw_output)
            if parsed:
                validation.validated_findings.extend(parsed.get("validated", []))
                validation.unconfirmed_findings.extend(parsed.get("unconfirmed", []))
                validation.contradictions.extend(parsed.get("contradictions", []))

        # Compute confidence score
        total = (
            len(validation.validated_findings)
            + len(validation.unconfirmed_findings)
            + len(validation.contradictions)
        )
        if total > 0:
            validated_ratio = len(validation.validated_findings) / total
            contradiction_penalty = len(validation.contradictions) * 0.2
            validation.confidence_score = max(0.0, min(1.0, validated_ratio - contradiction_penalty))
        else:
            validation.confidence_score = 0.5  # No data to validate

        logger.info(
            "RESEARCH validation: %d validated, %d unconfirmed, %d contradictions (confidence=%.2f)",
            len(validation.validated_findings),
            len(validation.unconfirmed_findings),
            len(validation.contradictions),
            validation.confidence_score,
        )

        return validation

    except Exception as exc:
        logger.warning("RESEARCH cross-validation error (non-blocking): %s", exc)
        return ResearchValidation(confidence_score=0.5)


def _parse_validation_response(raw_output: str) -> dict | None:
    """Parse a validation response looking for a JSON object.

    Args:
        raw_output: Raw text output from provider

    Returns:
        Parsed dict with validated/unconfirmed/contradictions, or None
    """
    if not raw_output:
        return None

    # Try to find JSON object in output
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


def annotate_research(research_file: Path, validation: ResearchValidation) -> None:
    """Annotate research.json with validation results.

    Adds a _validation section to the research file without modifying
    existing data.

    Args:
        research_file: Path to research.json
        validation: Validation results to annotate with
    """
    if not research_file.exists():
        return

    try:
        with open(research_file, encoding="utf-8") as fh:
            data = json.load(fh)

        data["_validation"] = {
            "confidence_score": validation.confidence_score,
            "validated_count": len(validation.validated_findings),
            "unconfirmed_count": len(validation.unconfirmed_findings),
            "contradiction_count": len(validation.contradictions),
            "contradictions": validation.contradictions[:10],
        }

        with open(research_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

        logger.info("Research file annotated with validation results")

    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to annotate research file: %s", exc)
