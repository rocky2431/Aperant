"""
Code Quality Validators
========================

Ultra Builder Pro git commit validators that check for forbidden patterns
in staged changes. Only active when ultraBuilderEnabled is set.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

from .validation_models import ValidationResult


def _get_staged_diff(project_dir: Path) -> str:
    """Get the staged diff content."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--unified=0"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Failed to get staged diff for quality check: %s", exc)
        return ""


def _is_test_file(filepath: str) -> bool:
    """Check if a file path is a test file."""
    test_patterns = [
        r'test[_.]', r'\.test\.', r'\.spec\.', r'__tests__',
        r'/tests/', r'/test/', r'_test\.py$',
    ]
    return any(re.search(p, filepath, re.IGNORECASE) for p in test_patterns)


def validate_no_todos_in_commit(
    _args: list[str], project_dir: Path
) -> ValidationResult:
    """Detect TODO/FIXME/HACK/XXX in staged diff."""
    diff = _get_staged_diff(project_dir)
    if not diff:
        return True, ""

    violations = []
    current_file = ""
    for line in diff.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            # Only check added lines
            if _is_test_file(current_file):
                continue
            for pattern in ["TODO", "FIXME", "HACK", "XXX"]:
                if pattern in line:
                    violations.append(f"  {current_file}: {line.strip()[:100]}")
                    break

    if violations:
        detail = "\n".join(violations[:10])
        return False, (
            f"ULTRA BUILDER: TODO/FIXME/HACK/XXX found in staged changes\n\n"
            f"Violations:\n{detail}\n\n"
            f"Complete the implementation before committing."
        )
    return True, ""


def validate_no_console_log_in_commit(
    _args: list[str], project_dir: Path
) -> ValidationResult:
    """Detect console.log/warn/error in staged diff (non-test files)."""
    diff = _get_staged_diff(project_dir)
    if not diff:
        return True, ""

    violations = []
    current_file = ""
    console_pattern = re.compile(r'console\.(log|warn|error)\s*\(')

    for line in diff.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            if _is_test_file(current_file):
                continue
            if console_pattern.search(line):
                violations.append(f"  {current_file}: {line.strip()[:100]}")

    if violations:
        detail = "\n".join(violations[:10])
        return False, (
            f"ULTRA BUILDER: console.log/warn/error found in production code\n\n"
            f"Violations:\n{detail}\n\n"
            f"Use a structured logger instead of console methods."
        )
    return True, ""


def validate_no_mocks_in_domain(
    _args: list[str], project_dir: Path
) -> ValidationResult:
    """Detect mock usage in domain/core layer staged changes."""
    diff = _get_staged_diff(project_dir)
    if not diff:
        return True, ""

    violations = []
    current_file = ""
    mock_pattern = re.compile(
        r'jest\.(fn|mock)|InMemoryRepository|Mock[A-Z]|Fake[A-Z]'
    )
    domain_patterns = ['/domain/', '/core/', '/entities/', '/value_objects/']

    for line in diff.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            if not any(p in current_file for p in domain_patterns):
                continue
            if _is_test_file(current_file):
                continue
            if mock_pattern.search(line):
                violations.append(f"  {current_file}: {line.strip()[:100]}")

    if violations:
        detail = "\n".join(violations[:10])
        return False, (
            f"ULTRA BUILDER: Mock usage detected in Domain/Core layer\n\n"
            f"Violations:\n{detail}\n\n"
            f"Domain/Core layer must use direct instantiation, not mocks."
        )
    return True, ""
