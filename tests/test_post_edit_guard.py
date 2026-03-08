#!/usr/bin/env python3
"""
Tests for Post-Edit Guard
===========================

Tests the runtime code quality enforcement hook.
All tests exercise pure functions (no mocks needed).
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "backend"))

from security.post_edit_guard import _is_test_file, _scan_content, post_edit_guard


# ---------------------------------------------------------------------------
# Helper: build test input strings dynamically so the post-edit hook that
# scans THIS file does not flag them as real violations.
# ---------------------------------------------------------------------------

def _todo_comment(style="hash"):
    """Build a TODO comment string without a literal TODO: in source."""
    tag = "TO" + "DO"
    if style == "hash":
        return f"# {tag}: fix this later"
    return f"// {tag}: fix this later"


def _fixme_comment():
    tag = "FIX" + "ME"
    return f"// {tag}: broken"


def _hack_comment():
    tag = "HA" + "CK"
    return f"// {tag}: workaround"


def _xxx_comment():
    tag = "XX" + "X"
    return f"// {tag}: temporary"


def _openai_key():
    prefix = "sk" + "-"
    return f'key = "{prefix}abcdefghijklmnopqrstuvwx"'


def _github_pat():
    prefix = "gh" + "p_"
    return f'token = "{prefix}aAbBcCdDeEfFgGhHiIjJkKlLmMnNoOpPqQrRsS"'


def _aws_key():
    prefix = "AKI" + "A"
    return f'key = "{prefix}IOSFODNN7EXAMPLE"'


class TestIsTestFile:

    def test_test_underscore_prefix(self):
        assert _is_test_file("src/tests/test_foo.py") is True

    def test_dot_test_suffix(self):
        assert _is_test_file("src/components/Button.test.tsx") is True

    def test_dot_spec_suffix(self):
        assert _is_test_file("src/components/Button.spec.ts") is True

    def test_dunder_tests_dir(self):
        assert _is_test_file("src/__tests__/Button.tsx") is True

    def test_tests_dir(self):
        assert _is_test_file("tests/test_security.py") is True

    def test_fixture_file(self):
        assert _is_test_file("tests/fixtures/data.py") is True

    def test_conftest(self):
        assert _is_test_file("tests/conftest.py") is True

    def test_stories_file(self):
        assert _is_test_file("src/Button.stories.tsx") is True

    def test_production_file(self):
        assert _is_test_file("src/components/Button.tsx") is False

    def test_production_python(self):
        assert _is_test_file("apps/backend/core/client.py") is False


class TestScanContentTodoFixme:

    def test_detects_todo(self):
        content = "x = 1\n" + _todo_comment("hash") + "\ny = 2"
        violations = _scan_content(content, "src/app.py")
        assert len(violations) == 1
        assert "TODO_FIXME" in violations[0]

    def test_detects_fixme(self):
        violations = _scan_content(_fixme_comment(), "src/app.ts")
        assert len(violations) == 1

    def test_detects_hack(self):
        violations = _scan_content(_hack_comment(), "src/app.js")
        assert len(violations) == 1

    def test_detects_xxx(self):
        violations = _scan_content(_xxx_comment(), "src/app.ts")
        assert len(violations) == 1

    def test_no_false_positive_in_word(self):
        # "orthodox" contains no word-boundary match
        violations = _scan_content("orthodox = True", "src/app.py")
        assert len(violations) == 0


class TestScanContentConsoleLog:

    def test_detects_console_log(self):
        content = 'console.log("debug")'
        violations = _scan_content(content, "src/app.ts")
        assert any("CONSOLE_LOG" in v for v in violations)

    def test_detects_console_warn(self):
        violations = _scan_content('console.warn("warning")', "src/app.ts")
        assert any("CONSOLE_LOG" in v for v in violations)

    def test_detects_console_error(self):
        violations = _scan_content('console.error("err")', "src/app.ts")
        assert any("CONSOLE_LOG" in v for v in violations)

    def test_no_false_positive_logger(self):
        violations = _scan_content('logger.info("msg")', "src/app.ts")
        assert not any("CONSOLE_LOG" in v for v in violations)


class TestScanContentMockInDomain:

    def test_detects_jest_fn_in_domain(self):
        content = "const mock = jest.fn()"
        violations = _scan_content(content, "src/domain/user.ts")
        assert any("MOCK_IN_DOMAIN" in v for v in violations)

    def test_detects_jest_mock_in_core(self):
        content = "jest.mock('./repo')"
        violations = _scan_content(content, "src/core/service.ts")
        assert any("MOCK_IN_DOMAIN" in v for v in violations)

    def test_detects_in_memory_repo_in_domain(self):
        content = "const repo = new InMemoryRepository()"
        violations = _scan_content(content, "src/domain/repo.ts")
        assert any("MOCK_IN_DOMAIN" in v for v in violations)

    def test_detects_mock_class_in_entities(self):
        content = "class MockUserService {}"
        violations = _scan_content(content, "src/entities/user.ts")
        assert any("MOCK_IN_DOMAIN" in v for v in violations)

    def test_detects_fake_class_in_value_objects(self):
        content = "class FakeEmail {}"
        violations = _scan_content(content, "src/value_objects/email.ts")
        assert any("MOCK_IN_DOMAIN" in v for v in violations)

    def test_allows_mock_outside_domain(self):
        content = "const mock = jest.fn()"
        violations = _scan_content(content, "src/infrastructure/repo.ts")
        assert not any("MOCK_IN_DOMAIN" in v for v in violations)


class TestScanContentHardcodedSecrets:

    def test_detects_openai_key(self):
        content = _openai_key()
        violations = _scan_content(content, "src/config.py")
        assert any("HARDCODED_SECRET" in v for v in violations)

    def test_detects_github_pat(self):
        content = _github_pat()
        violations = _scan_content(content, "src/config.ts")
        assert any("HARDCODED_SECRET" in v for v in violations)

    def test_detects_aws_key(self):
        content = _aws_key()
        violations = _scan_content(content, "src/config.py")
        assert any("HARDCODED_SECRET" in v for v in violations)

    def test_no_false_positive_env_var(self):
        content = 'key = os.environ["API_KEY"]'
        violations = _scan_content(content, "src/config.py")
        assert not any("HARDCODED_SECRET" in v for v in violations)


class TestScanContentSqlConcat:

    def test_detects_fstring_select(self):
        # Build the pattern dynamically to avoid triggering hooks
        sel = "SEL" + "ECT"
        content = 'f"' + sel + ' * FROM users WHERE id = {user_id}"'
        violations = _scan_content(content, "src/repo.py")
        assert any("SQL_CONCAT" in v for v in violations)

    def test_detects_string_concat_select(self):
        sel = "SEL" + "ECT"
        content = '"' + sel + ' * FROM users WHERE id = " + user_id'
        violations = _scan_content(content, "src/repo.py")
        assert any("SQL_CONCAT" in v for v in violations)

    def test_no_false_positive_parameterized(self):
        sel = "SEL" + "ECT"
        content = f'cursor.execute("{sel} * FROM users WHERE id = ?", (user_id,))'
        violations = _scan_content(content, "src/repo.py")
        assert not any("SQL_CONCAT" in v for v in violations)


class TestScanContentEmptyCatch:

    def test_detects_empty_js_catch(self):
        # Build pattern to avoid hook trigger
        cat = "cat" + "ch"
        content = f"try {{ foo() }} {cat}(e) {{}}"
        violations = _scan_content(content, "src/app.ts")
        assert any("EMPTY_CATCH" in v for v in violations)

    def test_detects_bare_except_pass(self):
        exc = "exce" + "pt"
        pas = "pa" + "ss"
        # Single-line form: except: pass (line-by-line scanner)
        content = f"try:\n    foo()\n{exc}: {pas}"
        violations = _scan_content(content, "src/app.py")
        assert any("EMPTY_CATCH" in v for v in violations)


class TestScanContentGenericError:

    def test_detects_throw_generic_error(self):
        thr = "thr" + "ow"
        err = "Err" + "or"
        content = f'{thr} new {err}("{err}")'
        violations = _scan_content(content, "src/app.ts")
        assert any("GENERIC_ERROR" in v for v in violations)

    def test_detects_raise_generic_exception(self):
        rai = "rai" + "se"
        exc = "Excep" + "tion"
        content = f'{rai} {exc}("error")'
        violations = _scan_content(content, "src/app.py")
        assert any("GENERIC_ERROR" in v for v in violations)


class TestPostEditGuardHook:

    @pytest.mark.asyncio
    async def test_noop_for_non_write_tools(self):
        result = await post_edit_guard({"tool_name": "Read"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_when_spec_dir_not_set(self, monkeypatch):
        monkeypatch.delenv("SPEC_DIR", raising=False)
        result = await post_edit_guard({"tool_name": "Write", "tool_input": {}})
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_when_ultra_builder_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEC_DIR", str(tmp_path))
        # No task_metadata.json means ultra builder is disabled
        result = await post_edit_guard({
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.py", "content": "x = 1"},
        })
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_for_test_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEC_DIR", str(tmp_path))
        (tmp_path / "task_metadata.json").write_text(
            json.dumps({"ultraBuilderEnabled": True}), encoding="utf-8"
        )
        todo_content = _todo_comment("hash").replace("fix this later", "add more tests")
        result = await post_edit_guard({
            "tool_name": "Write",
            "tool_input": {
                "file_path": "tests/test_app.py",
                "content": todo_content,
            },
        })
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_for_non_code_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEC_DIR", str(tmp_path))
        (tmp_path / "task_metadata.json").write_text(
            json.dumps({"ultraBuilderEnabled": True}), encoding="utf-8"
        )
        todo_content = _todo_comment("hash").replace("fix this later", "write docs")
        result = await post_edit_guard({
            "tool_name": "Write",
            "tool_input": {
                "file_path": "README.md",
                "content": todo_content,
            },
        })
        assert result == {}

    @pytest.mark.asyncio
    async def test_detects_violations_in_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEC_DIR", str(tmp_path))
        (tmp_path / "task_metadata.json").write_text(
            json.dumps({"ultraBuilderEnabled": True}), encoding="utf-8"
        )
        todo_line = "x = 1  " + _todo_comment("hash").replace("fix this later", "fix this")
        result = await post_edit_guard({
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/app.py",
                "content": todo_line,
            },
        })
        assert "hookSpecificOutput" in result
        assert "ULTRA BUILDER VIOLATION" in result["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.asyncio
    async def test_returns_empty_for_clean_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEC_DIR", str(tmp_path))
        (tmp_path / "task_metadata.json").write_text(
            json.dumps({"ultraBuilderEnabled": True}), encoding="utf-8"
        )
        result = await post_edit_guard({
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/app.py",
                "content": "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
            },
        })
        assert result == {}
