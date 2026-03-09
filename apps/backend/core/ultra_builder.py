"""
Ultra Builder Pro Integration
==============================

Detection and configuration for Ultra Builder Pro quality methodology.
All downstream workflows check this module to determine whether Ultra Builder
constraints (TDD, architecture, forbidden patterns, evidence verification)
should be enforced.

The feature is gated by the ``ultraBuilderEnabled`` flag in
``task_metadata.json`` (written by the Electron frontend).  Project-level
overrides can be placed in ``.ultra-builder-overrides.json`` at the
project root.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default overrides schema – every key can be set to ``false`` to disable
# the corresponding Ultra Builder rule category.
_DEFAULT_OVERRIDES: dict[str, Any] = {
    "tdd_required": True,
    "architecture_layers": True,
    "forbidden_patterns": True,
    "evidence_verification": True,
    "six_agent_review": True,
    "risk_brake": True,
    "code_quality_validators": True,
    "multi_ai_dispatch": True,
    "init_quality_gate": True,
    "research_cross_validation": True,
    "plan_adversarial_review": True,
    "dev_subtask_review": True,
    "deliver_checkpoint": True,
}


def is_ultra_builder_enabled(spec_dir: Path) -> bool:
    """Return ``True`` when Ultra Builder Pro mode is active for this task.

    The canonical flag lives in ``task_metadata.json`` under the key
    ``ultraBuilderEnabled``.  When the file is absent or the key is not
    set the feature defaults to **off** (zero regression risk).
    """
    metadata_path = spec_dir / "task_metadata.json"
    if not metadata_path.exists():
        return False

    try:
        with open(metadata_path, encoding="utf-8") as fh:
            metadata = json.load(fh)
            return bool(metadata.get("ultraBuilderEnabled", False))
    except (json.JSONDecodeError, OSError):
        return False


def load_ultra_builder_overrides(project_dir: Path) -> dict[str, Any]:
    """Load project-level rule overrides from ``.ultra-builder-overrides.json``.

    Returns the merged result of ``_DEFAULT_OVERRIDES`` with whatever the
    user provided.  Unknown keys are silently ignored so that forward-
    compatible override files do not break older backend versions.
    """
    overrides = _DEFAULT_OVERRIDES.copy()
    overrides_path = project_dir / ".ultra-builder-overrides.json"
    if not overrides_path.exists():
        return overrides

    try:
        with open(overrides_path, encoding="utf-8") as fh:
            user_overrides = json.load(fh)
            if not isinstance(user_overrides, dict):
                logger.warning(
                    ".ultra-builder-overrides.json must be a JSON object, ignoring"
                )
                return overrides
            for key in _DEFAULT_OVERRIDES:
                if key in user_overrides:
                    overrides[key] = bool(user_overrides[key])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read .ultra-builder-overrides.json: %s", exc)

    return overrides


def is_rule_enabled(
    spec_dir: Path, project_dir: Path, rule_name: str
) -> bool:
    """Check whether a specific Ultra Builder rule is active.

    Convenience wrapper that combines the global toggle with per-rule
    overrides.  Returns ``False`` when Ultra Builder is disabled entirely
    or when the specific *rule_name* has been overridden to ``false``.
    """
    if not is_ultra_builder_enabled(spec_dir):
        return False
    overrides = load_ultra_builder_overrides(project_dir)
    return bool(overrides.get(rule_name, True))
