#!/usr/bin/env python3
"""
Tests for Subtask Risk Classifier
====================================

Tests agents/coder.py:_classify_subtask_risk -- a pure function that
classifies subtask risk based on file paths and description text.

No mocks needed. Input dict in, risk string out.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "backend"))

from agents.coder import _classify_subtask_risk


# =============================================================================
# TESTS: Critical risk level
# =============================================================================


class TestCriticalRisk:

    def test_payment_in_files(self):
        subtask = {"files_to_modify": ["src/services/payment.py"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_auth_login_in_files(self):
        subtask = {"files_to_modify": ["src/auth/login.py"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_billing_in_files(self):
        subtask = {"files_to_modify": ["src/billing/invoice.py"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_token_in_files(self):
        subtask = {"files_to_modify": ["src/auth/token.py"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_secret_in_files(self):
        subtask = {"files_to_modify": ["config/secret.yaml"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_credential_in_files(self):
        subtask = {"files_to_modify": ["src/credential.py"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_env_file(self):
        subtask = {"files_to_modify": [".env"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_payment_in_description(self):
        subtask = {"description": "Update payment processing logic"}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_files_to_create_also_checked(self):
        """files_to_create list is merged with files_to_modify for risk analysis."""
        subtask = {"files_to_create": ["src/services/payment.py"]}
        assert _classify_subtask_risk(subtask) == "critical"

    def test_payment_gateway_no_word_boundary(self):
        """'payment_gateway' does not trigger \\bpayment\\b because _ is a word char."""
        subtask = {"files_to_create": ["src/services/payment_gateway.py"]}
        assert _classify_subtask_risk(subtask) == "low"


# =============================================================================
# TESTS: High risk level
# =============================================================================


class TestHighRisk:

    def test_migration_in_files(self):
        subtask = {"files_to_modify": ["migration/001.sql"]}
        assert _classify_subtask_risk(subtask) == "high"

    def test_permission_in_files(self):
        subtask = {"files_to_modify": ["src/permission.py"]}
        assert _classify_subtask_risk(subtask) == "high"

    def test_schema_in_files(self):
        subtask = {"files_to_modify": ["db/schema.sql"]}
        assert _classify_subtask_risk(subtask) == "high"

    def test_database_in_description(self):
        subtask = {"description": "Update database connection pooling"}
        assert _classify_subtask_risk(subtask) == "high"

    def test_deploy_in_description(self):
        subtask = {"description": "Configure deploy pipeline"}
        assert _classify_subtask_risk(subtask) == "high"


# =============================================================================
# TESTS: Medium risk level
# =============================================================================


class TestMediumRisk:

    def test_delete_in_description(self):
        subtask = {"description": "delete all users from inactive list"}
        assert _classify_subtask_risk(subtask) == "medium"

    def test_refactor_in_description(self):
        subtask = {"description": "refactor the logging subsystem"}
        assert _classify_subtask_risk(subtask) == "medium"

    def test_drop_in_description(self):
        subtask = {"description": "drop the legacy endpoint"}
        assert _classify_subtask_risk(subtask) == "medium"


# =============================================================================
# TESTS: Low risk level
# =============================================================================


class TestLowRisk:

    def test_no_patterns(self):
        subtask = {
            "files_to_modify": ["src/utils/helpers.py"],
            "description": "Add string formatting utility",
        }
        assert _classify_subtask_risk(subtask) == "low"

    def test_empty_subtask(self):
        assert _classify_subtask_risk({}) == "low"

    def test_empty_files_and_description(self):
        subtask = {"files_to_modify": [], "description": ""}
        assert _classify_subtask_risk(subtask) == "low"


# =============================================================================
# TESTS: Word-boundary false positives
# =============================================================================


class TestWordBoundaryFalsePositives:

    def test_author_does_not_match_auth(self):
        """'author.py' must NOT trigger the 'auth' pattern."""
        subtask = {"files_to_modify": ["src/models/author.py"]}
        assert _classify_subtask_risk(subtask) == "low"

    def test_tokenizer_does_not_match_token(self):
        """'tokenizer.py' must NOT trigger the 'token' pattern."""
        subtask = {"files_to_modify": ["src/nlp/tokenizer.py"]}
        assert _classify_subtask_risk(subtask) == "low"

    def test_authority_does_not_match_auth(self):
        subtask = {"files_to_modify": ["src/authority.py"]}
        assert _classify_subtask_risk(subtask) == "low"

    def test_authorize_description_does_not_match(self):
        """Descriptions use the same word-boundary patterns."""
        subtask = {"description": "fix the authorization middleware"}
        # "authorization" does NOT contain standalone \bauth\b
        assert _classify_subtask_risk(subtask) == "low"
