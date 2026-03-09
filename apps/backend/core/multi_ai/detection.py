"""
Multi-AI Dispatcher — CLI Detection
=====================================

Detect available AI CLI tools (gemini, codex) with caching and validation.
Follows the pattern from ``core.gh_executable``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from .types import ProviderName

logger = logging.getLogger(__name__)

# Global cache for detected CLI paths
_cli_cache: dict[str, str | None] = {}


def invalidate_cache() -> None:
    """Invalidate all cached CLI paths."""
    global _cli_cache
    _cli_cache.clear()


def _verify_cli(path: str, version_flag: str = "--version") -> bool:
    """Verify that a path is a valid CLI executable by checking version.

    Args:
        path: Path to the potential executable
        version_flag: Flag to check version (default: --version)

    Returns:
        True if the path points to a valid executable
    """
    try:
        result = subprocess.run(
            [path, version_flag],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


def _find_cli(name: str, env_var: str | None = None) -> str | None:
    """Find a CLI executable with environment override and PATH lookup.

    Args:
        name: Executable name (e.g., "gemini", "codex")
        env_var: Optional environment variable for custom path

    Returns:
        Path to the executable or None if not found
    """
    # 1. Check environment variable override
    if env_var:
        env_path = os.environ.get(env_var)
        if env_path and os.path.isfile(env_path) and _verify_cli(env_path):
            return env_path

    # 2. Try shutil.which (PATH lookup)
    cli_path = shutil.which(name)
    if cli_path and _verify_cli(cli_path):
        return cli_path

    return None


def is_cli_available(name: str) -> bool:
    """Check whether a CLI tool is available.

    Args:
        name: CLI tool name ("gemini" or "codex")

    Returns:
        True if the tool is installed and responds to --version
    """
    return get_cli_path(name) is not None


def get_cli_path(name: str) -> str | None:
    """Get the path to a CLI tool, with caching.

    Args:
        name: CLI tool name ("gemini" or "codex")

    Returns:
        Path to the executable or None
    """
    if name in _cli_cache:
        cached = _cli_cache[name]
        # Verify cached path still exists
        if cached is not None and os.path.isfile(cached):
            return cached
        if cached is None:
            return None

    env_vars = {
        "gemini": "GEMINI_CLI_PATH",
        "codex": "CODEX_CLI_PATH",
    }

    path = _find_cli(name, env_vars.get(name))
    _cli_cache[name] = path

    if path:
        logger.info("Found %s CLI at: %s", name, path)
    else:
        logger.debug("%s CLI not found (will use Claude-only mode)", name)

    return path


def detect_available_providers() -> list[ProviderName]:
    """Detect all available AI providers.

    Claude is always available (SDK fallback). Gemini and Codex are
    detected via CLI presence.

    Returns:
        List of available provider names
    """
    providers = [ProviderName.CLAUDE]  # Always available

    if is_cli_available("gemini"):
        providers.append(ProviderName.GEMINI)

    if is_cli_available("codex"):
        providers.append(ProviderName.CODEX)

    logger.info(
        "Available AI providers: %s", [p.value for p in providers]
    )
    return providers
