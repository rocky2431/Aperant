"""Tests for DEV Subtask Review."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.ultra_dev_review import (
    DevReviewResult,
    _get_subtask_diff,
    run_dev_subtask_review,
)


class TestDevReviewResult:
    def test_default(self):
        r = DevReviewResult()
        assert r.has_blockers is False
        assert r.findings == []


class TestGetSubtaskDiff:
    def test_no_commits(self):
        assert _get_subtask_diff(Path("."), None, None) == ""

    @patch("agents.ultra_dev_review.subprocess.run")
    def test_returns_diff(self, mock_run):
        from unittest.mock import MagicMock
        mock_run.return_value = MagicMock(stdout="diff content")
        result = _get_subtask_diff(Path("."), "abc123", "def456")
        assert result == "diff content"


@pytest.mark.asyncio
class TestRunDevSubtaskReview:
    async def test_disabled_returns_empty(self, tmp_path):
        result = await run_dev_subtask_review(tmp_path, tmp_path, "1.1", None, None)
        assert result.has_blockers is False
