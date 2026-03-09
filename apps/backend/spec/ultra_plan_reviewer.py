"""
Ultra Builder Pro — PLAN Adversarial Review
=============================================

Multi-AI adversarial review for implementation plans. Challenge round
finds weaknesses, defense round addresses them, final ruling determines
if the plan needs revision.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PlanReviewResult:
    """Result of adversarial plan review."""
    approved: bool = True
    challenges: list[dict] = field(default_factory=list)
    defended: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    revised_plan: dict | None = None


CHALLENGE_PROMPT = """You are a senior architect CHALLENGING an implementation plan.
Find weaknesses, risks, and errors.

## Spec Summary
{spec_content}

## Implementation Plan
{plan_content}

## Instructions
Identify weaknesses in this plan:
1. Missing dependencies between subtasks
2. Incorrect ordering of tasks
3. Subtasks that are too large (should be split)
4. Missing error handling or rollback plans
5. Security considerations not addressed
6. Performance bottlenecks in the approach

Respond with a JSON array of challenges:
```json
[
  {{
    "severity": "critical|major|minor",
    "subtask_id": "affected subtask or 'general'",
    "title": "Brief challenge description",
    "detail": "Why this is a problem",
    "suggestion": "How to fix"
  }}
]
```
If no issues: `[]`
"""


DEFENSE_PROMPT = """You are defending an implementation plan against challenges.
For each challenge, either defend the current approach or propose a fix.

## Implementation Plan
{plan_content}

## Challenges Raised
{challenges_content}

## Instructions
For each challenge, respond with:
- "defended": why the current plan is correct despite the challenge
- "accepted": the challenge is valid, here's how to fix it

Respond with a JSON array:
```json
[
  {{
    "challenge_title": "original challenge title",
    "resolution": "defended|accepted",
    "rationale": "Why defended, or what to change"
  }}
]
```
"""


async def run_adversarial_plan_review(
    spec_dir: Path,
    project_dir: Path,
    plan_data: dict,
    spec_content: str,
) -> PlanReviewResult:
    """Run adversarial review: challenge round -> defense round -> ruling.

    Args:
        spec_dir: Spec directory
        project_dir: Project root
        plan_data: Parsed implementation_plan.json
        spec_content: Spec markdown content

    Returns:
        PlanReviewResult with challenges, defenses, and ruling
    """
    from core.ultra_builder import is_rule_enabled

    if not is_rule_enabled(spec_dir, project_dir, "plan_adversarial_review"):
        return PlanReviewResult(approved=True)

    plan_content = json.dumps(plan_data, indent=2)[:40000]
    spec_content = spec_content[:20000]

    logger.info("Running adversarial plan review")

    try:
        # Round 1: Challenge (parallel multi-AI dispatch)
        from core.multi_ai import dispatch_to_multiple_ais

        challenge_prompt = CHALLENGE_PROMPT.format(
            spec_content=spec_content, plan_content=plan_content
        )
        challenge_result = await dispatch_to_multiple_ais(
            challenge_prompt, project_dir, spec_dir, timeout_seconds=120
        )

        # Collect all challenges from findings
        challenges = []
        for finding in challenge_result.findings:
            challenges.append({
                "severity": finding.severity,
                "title": finding.title,
                "detail": finding.suggestion,
                "provider": finding.provider,
            })

        if not challenges:
            logger.info("No challenges raised — plan approved")
            return PlanReviewResult(approved=True)

        # Round 2: Defense (Claude-only for consistency)
        challenges_content = json.dumps(challenges, indent=2)
        defense_prompt = DEFENSE_PROMPT.format(
            plan_content=plan_content, challenges_content=challenges_content
        )

        defense_result = await dispatch_to_multiple_ais(
            defense_prompt, project_dir, spec_dir, timeout_seconds=120
        )

        # Parse defense responses
        defended = []
        unresolved = []
        for finding in defense_result.findings:
            # Findings from defense round represent unresolved issues
            unresolved.append({
                "title": finding.title,
                "severity": finding.severity,
                "detail": finding.suggestion,
            })

        # Also parse structured defense responses from raw output
        for provider_result in defense_result.provider_results.values():
            if provider_result.status.value != "success":
                continue
            defenses = _parse_defense_response(provider_result.raw_output)
            for d in defenses:
                if d.get("resolution") == "defended":
                    defended.append(d)
                else:
                    unresolved.append({
                        "title": d.get("challenge_title", "Unknown"),
                        "severity": "major",
                        "detail": d.get("rationale", ""),
                    })

        # Ruling: >50% unresolved = needs human review
        total_challenges = len(challenges)
        unresolved_count = len(unresolved)
        approved = unresolved_count <= total_challenges * 0.5

        logger.info(
            "Plan review: %d challenges, %d defended, %d unresolved -> %s",
            total_challenges,
            len(defended),
            unresolved_count,
            "APPROVED" if approved else "NEEDS REVISION",
        )

        return PlanReviewResult(
            approved=approved,
            challenges=challenges,
            defended=defended,
            unresolved=unresolved,
        )

    except Exception as exc:
        logger.warning("Adversarial plan review error (non-blocking): %s", exc)
        return PlanReviewResult(approved=True)


def _parse_defense_response(raw_output: str) -> list[dict]:
    """Parse defense round response for structured resolutions."""
    if not raw_output:
        return []

    first_bracket = raw_output.find("[")
    last_bracket = raw_output.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        try:
            parsed = json.loads(raw_output[first_bracket : last_bracket + 1])
            if isinstance(parsed, list):
                return [d for d in parsed if isinstance(d, dict)]
        except json.JSONDecodeError:
            pass
    return []
