"""
Multi-AI Dispatcher — Configuration
=====================================

Configuration loading for the multi-AI dispatch system.
Priority: environment variables > task_metadata.json > defaults.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .types import ProviderName

logger = logging.getLogger(__name__)


@dataclass
class DispatcherConfig:
    """Configuration for the multi-AI dispatcher."""

    enabled: bool = False
    providers: list[ProviderName] = field(
        default_factory=lambda: [ProviderName.CLAUDE]
    )
    timeout_seconds: int = 300
    parallel: bool = True
    require_consensus: bool = False

    @property
    def is_multi_ai(self) -> bool:
        """Return True if more than one provider is configured."""
        return len(self.providers) > 1


def _parse_providers(raw: str) -> list[ProviderName]:
    """Parse a comma-separated provider string into ProviderName list.

    Args:
        raw: Comma-separated string like "claude,gemini,codex"

    Returns:
        List of valid ProviderName values
    """
    result = []
    for name in raw.split(","):
        name = name.strip().lower()
        try:
            result.append(ProviderName(name))
        except ValueError:
            logger.warning("Unknown provider name '%s', ignoring", name)
    return result if result else [ProviderName.CLAUDE]


def load_dispatcher_config(spec_dir: Path | None = None) -> DispatcherConfig:
    """Load dispatcher configuration from environment and task metadata.

    Priority:
        1. Environment variables (MULTI_AI_ENABLED, MULTI_AI_PROVIDERS, etc.)
        2. task_metadata.json multiAiConfig section
        3. Defaults (Claude-only, disabled)

    Args:
        spec_dir: Optional spec directory for task_metadata.json lookup

    Returns:
        DispatcherConfig with resolved settings
    """
    config = DispatcherConfig()

    # Level 2: task_metadata.json (lower priority)
    if spec_dir:
        metadata_path = spec_dir / "task_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as fh:
                    metadata = json.load(fh)
                    multi_ai = metadata.get("multiAiConfig", {})
                    if isinstance(multi_ai, dict):
                        if "enabled" in multi_ai:
                            config.enabled = bool(multi_ai["enabled"])
                        if "providers" in multi_ai:
                            if isinstance(multi_ai["providers"], list):
                                config.providers = _parse_providers(
                                    ",".join(multi_ai["providers"])
                                )
                            elif isinstance(multi_ai["providers"], str):
                                config.providers = _parse_providers(
                                    multi_ai["providers"]
                                )
                        if "timeout" in multi_ai:
                            config.timeout_seconds = int(multi_ai["timeout"])
                        if "parallel" in multi_ai:
                            config.parallel = bool(multi_ai["parallel"])
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read multiAiConfig from task_metadata: %s", exc)

    # Level 1: Environment variables (higher priority, override file config)
    env_enabled = os.environ.get("MULTI_AI_ENABLED")
    if env_enabled is not None:
        config.enabled = env_enabled.lower() in ("true", "1", "yes")

    env_providers = os.environ.get("MULTI_AI_PROVIDERS")
    if env_providers:
        config.providers = _parse_providers(env_providers)

    env_timeout = os.environ.get("MULTI_AI_TIMEOUT")
    if env_timeout:
        try:
            config.timeout_seconds = int(env_timeout)
        except ValueError:
            logger.warning("Invalid MULTI_AI_TIMEOUT value '%s', using default", env_timeout)

    # Ensure Claude is always in the provider list
    if ProviderName.CLAUDE not in config.providers:
        config.providers.insert(0, ProviderName.CLAUDE)

    return config
