#!/usr/bin/env python3
"""
Tests for Dangerous Pattern Detection
=======================================

Tests the regex patterns from security/hooks.py bash_security_hook()
(lines 153-159) that block dangerous commands.

These are pure regex tests -- no mocking needed. We extract the same
pattern strings and validate them directly against input commands.
"""

import re

import pytest


# ---------------------------------------------------------------------------
# Patterns copied verbatim from security/hooks.py lines 153-159.
# We test the regex strings directly rather than importing the async function
# which has complex dependencies (security profile, validators, etc.).
# ---------------------------------------------------------------------------

DANGEROUS_PATTERNS = [
    (
        "git push --force",
        r"git\s+push\s+.*(?:--force|--force-with-lease).*\b(main|master|develop)\b"
        r"|git\s+push\s+.*\b(main|master|develop)\b.*(?:--force|--force-with-lease)",
    ),
    ("DROP TABLE", r"drop\s+table"),
    ("DROP DATABASE", r"drop\s+database"),
    ("TRUNCATE TABLE", r"truncate\s+table"),
    ("chmod 777", r"chmod\s+777"),
]


def _matches(command: str) -> list[str]:
    """Return names of all patterns that match *command* (lowercased)."""
    command_lower = command.lower()
    return [
        name
        for name, pattern in DANGEROUS_PATTERNS
        if re.search(pattern, command_lower)
    ]


# =============================================================================
# TESTS: git push --force on protected branches
# =============================================================================


class TestGitForceProtectedBranch:

    def test_force_push_main(self):
        assert "git push --force" in _matches("git push --force origin main")

    def test_force_push_master(self):
        assert "git push --force" in _matches("git push --force origin master")

    def test_force_push_develop(self):
        assert "git push --force" in _matches("git push --force origin develop")

    def test_force_with_lease_main(self):
        assert "git push --force" in _matches("git push --force-with-lease origin main")

    def test_branch_before_flag(self):
        """Pattern also matches when branch name comes before the flag."""
        assert "git push --force" in _matches("git push origin main --force")

    def test_regular_push_not_matched(self):
        assert _matches("git push origin feature-branch") == []

    def test_force_push_feature_branch_not_matched(self):
        """Force-pushing to a non-protected branch is allowed."""
        assert _matches("git push --force origin feature-branch") == []

    def test_force_push_no_branch_not_matched(self):
        """Force push without naming a protected branch is not matched."""
        assert _matches("git push --force") == []


# =============================================================================
# TESTS: SQL destructive operations
# =============================================================================


class TestSQLPatterns:

    def test_drop_table(self):
        assert "DROP TABLE" in _matches("DROP TABLE users")

    def test_drop_table_case_insensitive(self):
        assert "DROP TABLE" in _matches("drop table users")

    def test_drop_table_if_exists(self):
        assert "DROP TABLE" in _matches("DROP TABLE IF EXISTS users")

    def test_select_not_matched(self):
        assert _matches("SELECT * FROM users") == []

    def test_drop_database(self):
        assert "DROP DATABASE" in _matches("DROP DATABASE mydb")

    def test_drop_database_lower(self):
        assert "DROP DATABASE" in _matches("drop database mydb")

    def test_truncate_table(self):
        assert "TRUNCATE TABLE" in _matches("TRUNCATE TABLE orders")

    def test_truncate_table_lower(self):
        assert "TRUNCATE TABLE" in _matches("truncate table orders")

    def test_insert_not_matched(self):
        assert _matches("INSERT INTO orders VALUES (1, 'item')") == []


# =============================================================================
# TESTS: chmod 777
# =============================================================================


class TestChmodPattern:

    def test_chmod_777(self):
        assert "chmod 777" in _matches("chmod 777 /tmp/foo")

    def test_chmod_777_recursive_not_matched(self):
        """chmod -R 777 has flags between chmod and 777, so the pattern does not match."""
        assert _matches("chmod -R 777 /var/www") == []

    def test_chmod_755_not_matched(self):
        assert _matches("chmod 755 /tmp/foo") == []

    def test_chmod_644_not_matched(self):
        assert _matches("chmod 644 /etc/config") == []
