"""
Multi-AI Dispatcher — Output Parser
=====================================

Parse AI provider output into structured findings.
Handles JSON arrays, markdown-wrapped JSON, and free-text output.
"""

from __future__ import annotations

import json
import logging
import re

from .types import Finding

logger = logging.getLogger(__name__)


def parse_provider_output(raw_output: str, provider: str) -> list[Finding]:
    """Parse raw output from an AI provider into structured findings.

    Tries multiple parsing strategies:
    1. Direct JSON array
    2. JSON array within markdown code blocks
    3. JSON array between first [ and last ]

    Args:
        raw_output: Raw text output from the provider
        provider: Provider name for attribution

    Returns:
        List of Finding objects
    """
    if not raw_output or not raw_output.strip():
        return []

    # Strategy 1: Try parsing as direct JSON array
    findings = _try_parse_json_array(raw_output.strip(), provider)
    if findings is not None:
        return findings

    # Strategy 2: Extract JSON from markdown code blocks
    code_block_match = re.search(
        r"```(?:json)?\s*\n?(.*?)```", raw_output, re.DOTALL
    )
    if code_block_match:
        findings = _try_parse_json_array(code_block_match.group(1).strip(), provider)
        if findings is not None:
            return findings

    # Strategy 3: Find first [ to last ] (like ultra_review.py)
    first_bracket = raw_output.find("[")
    last_bracket = raw_output.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        findings = _try_parse_json_array(
            raw_output[first_bracket : last_bracket + 1], provider
        )
        if findings is not None:
            return findings

    logger.debug(
        "Could not parse findings from %s output (%d chars)",
        provider,
        len(raw_output),
    )
    return []


def _try_parse_json_array(text: str, provider: str) -> list[Finding] | None:
    """Attempt to parse text as a JSON array of findings.

    Args:
        text: Text to parse
        provider: Provider name for attribution

    Returns:
        List of Finding objects, or None if parsing failed
    """
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return None
        return _dicts_to_findings(parsed, provider)
    except (json.JSONDecodeError, ValueError):
        return None


def _dicts_to_findings(dicts: list, provider: str) -> list[Finding]:
    """Convert a list of dicts to Finding objects.

    Args:
        dicts: List of finding dictionaries
        provider: Provider name for attribution

    Returns:
        List of Finding objects
    """
    findings = []
    for item in dicts:
        if not isinstance(item, dict):
            continue
        finding = Finding(
            provider=provider,
            severity=item.get("severity", "minor"),
            category=item.get("category", ""),
            file=item.get("file", "unknown"),
            line=int(item.get("line", 0)),
            title=item.get("title", ""),
            suggestion=item.get("suggestion", ""),
            confidence=float(item.get("confidence", 0.0)),
        )
        findings.append(finding)
    return findings


def extract_verdict(raw_output: str) -> str:
    """Extract a verdict from provider output.

    Looks for common verdict keywords in the output text.

    Args:
        raw_output: Raw text output from the provider

    Returns:
        Verdict string: "APPROVE", "REJECT", or "COMMENT"
    """
    if not raw_output:
        return ""

    upper = raw_output.upper()

    # Look for explicit verdict markers
    verdict_patterns = [
        (r"\bAPPROVE[D]?\b", "APPROVE"),
        (r"\bREJECT(?:ED)?\b", "REJECT"),
        (r"\bREQUEST.?CHANGES?\b", "REJECT"),
        (r"\bBLOCK(?:ED|ER|ING)?\b", "REJECT"),
        (r"\bPASS(?:ED|ES)?\b", "APPROVE"),
        (r"\bFAIL(?:ED|S)?\b", "REJECT"),
    ]

    for pattern, verdict in verdict_patterns:
        if re.search(pattern, upper):
            return verdict

    return "COMMENT"
