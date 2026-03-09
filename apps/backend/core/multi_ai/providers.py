"""
Multi-AI Dispatcher — Provider Implementations
================================================

AIProvider protocol and concrete implementations for Claude (SDK),
Gemini (subprocess), and Codex (subprocess).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Protocol

from .detection import get_cli_path, is_cli_available
from .output_parser import extract_verdict, parse_provider_output
from .types import DispatchStatus, ProviderName, ProviderResult

logger = logging.getLogger(__name__)


class AIProvider(Protocol):
    """Protocol for AI provider implementations."""

    @property
    def name(self) -> ProviderName: ...

    def is_available(self) -> bool: ...

    async def dispatch(
        self,
        prompt: str,
        cwd: Path,
        timeout_seconds: int = 300,
    ) -> ProviderResult: ...


class ClaudeProvider:
    """Claude AI provider using the Claude Agent SDK."""

    @property
    def name(self) -> ProviderName:
        return ProviderName.CLAUDE

    def is_available(self) -> bool:
        return True  # Always available via SDK

    async def dispatch(
        self,
        prompt: str,
        cwd: Path,
        timeout_seconds: int = 300,
        spec_dir: Path | None = None,
    ) -> ProviderResult:
        """Dispatch a prompt to Claude via the Agent SDK.

        Args:
            prompt: The prompt to send
            cwd: Working directory (project_dir)
            timeout_seconds: Maximum time to wait
            spec_dir: Optional spec directory for client configuration

        Returns:
            ProviderResult with findings and verdict
        """
        start = time.monotonic()
        try:
            from core.client import create_client
            from phase_config import get_thinking_kwargs_for_model, resolve_model_id

            model_id = resolve_model_id("haiku")
            thinking_kwargs = get_thinking_kwargs_for_model(model_id, "low")

            client = create_client(
                cwd,
                spec_dir or cwd,
                model_id,
                agent_type="qa_reviewer",
                **thinking_kwargs,
            )

            response_text = ""
            async with client:
                await client.query(prompt)
                async for msg in client.receive_response():
                    msg_type = type(msg).__name__
                    if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                        for block in msg.content:
                            block_type = type(block).__name__
                            if block_type == "TextBlock" and hasattr(block, "text"):
                                response_text += block.text

            duration = time.monotonic() - start
            findings = parse_provider_output(response_text, self.name.value)
            verdict = extract_verdict(response_text)

            return ProviderResult(
                provider=self.name,
                status=DispatchStatus.SUCCESS,
                raw_output=response_text,
                findings=findings,
                verdict=verdict,
                duration_seconds=duration,
            )

        except asyncio.TimeoutError:
            return ProviderResult(
                provider=self.name,
                status=DispatchStatus.TIMEOUT,
                duration_seconds=time.monotonic() - start,
                error_message=f"Claude timed out after {timeout_seconds}s",
            )
        except Exception as exc:
            logger.warning("Claude dispatch failed: %s", exc)
            return ProviderResult(
                provider=self.name,
                status=DispatchStatus.ERROR,
                duration_seconds=time.monotonic() - start,
                error_message=str(exc),
            )


class GeminiProvider:
    """Gemini AI provider using the Gemini CLI (subprocess)."""

    @property
    def name(self) -> ProviderName:
        return ProviderName.GEMINI

    def is_available(self) -> bool:
        return is_cli_available("gemini")

    async def dispatch(
        self,
        prompt: str,
        cwd: Path,
        timeout_seconds: int = 300,
    ) -> ProviderResult:
        """Dispatch a prompt to Gemini CLI.

        Uses asyncio.create_subprocess_exec (not shell) for safe subprocess
        execution without command injection risk.

        Args:
            prompt: The prompt to send
            cwd: Working directory
            timeout_seconds: Maximum time to wait

        Returns:
            ProviderResult with findings and verdict
        """
        cli_path = get_cli_path("gemini")
        if not cli_path:
            return ProviderResult(
                provider=self.name,
                status=DispatchStatus.NOT_AVAILABLE,
                error_message="Gemini CLI not found",
            )

        return await _run_cli_provider(
            provider_name=self.name,
            cli_path=cli_path,
            args=["-p", prompt],
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )


class CodexProvider:
    """Codex AI provider using the Codex CLI (subprocess)."""

    @property
    def name(self) -> ProviderName:
        return ProviderName.CODEX

    def is_available(self) -> bool:
        return is_cli_available("codex")

    async def dispatch(
        self,
        prompt: str,
        cwd: Path,
        timeout_seconds: int = 300,
    ) -> ProviderResult:
        """Dispatch a prompt to Codex CLI.

        Uses asyncio.create_subprocess_exec (not shell) for safe subprocess
        execution without command injection risk.

        Args:
            prompt: The prompt to send
            cwd: Working directory
            timeout_seconds: Maximum time to wait

        Returns:
            ProviderResult with findings and verdict
        """
        cli_path = get_cli_path("codex")
        if not cli_path:
            return ProviderResult(
                provider=self.name,
                status=DispatchStatus.NOT_AVAILABLE,
                error_message="Codex CLI not found",
            )

        return await _run_cli_provider(
            provider_name=self.name,
            cli_path=cli_path,
            args=["-p", prompt, "-a", "read-only"],
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )


async def _run_cli_provider(
    provider_name: ProviderName,
    cli_path: str,
    args: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> ProviderResult:
    """Run an external CLI AI provider as a subprocess.

    Uses asyncio.create_subprocess_exec which passes arguments as a list
    (no shell interpretation), preventing command injection.

    Args:
        provider_name: Name of the provider
        cli_path: Path to the CLI executable
        args: Command-line arguments (passed as list, not shell string)
        cwd: Working directory
        timeout_seconds: Maximum time to wait

    Returns:
        ProviderResult with parsed findings
    """
    start = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            cli_path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )

        duration = time.monotonic() - start
        raw_output = stdout.decode("utf-8", errors="replace") if stdout else ""

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            logger.warning(
                "%s CLI exited with code %d: %s",
                provider_name.value,
                process.returncode,
                stderr_text[:200],
            )
            return ProviderResult(
                provider=provider_name,
                status=DispatchStatus.ERROR,
                raw_output=raw_output,
                duration_seconds=duration,
                error_message=f"Exit code {process.returncode}: {stderr_text[:200]}",
            )

        findings = parse_provider_output(raw_output, provider_name.value)
        verdict = extract_verdict(raw_output)

        return ProviderResult(
            provider=provider_name,
            status=DispatchStatus.SUCCESS,
            raw_output=raw_output,
            findings=findings,
            verdict=verdict,
            duration_seconds=duration,
        )

    except asyncio.TimeoutError:
        logger.warning(
            "%s CLI timed out after %ds", provider_name.value, timeout_seconds
        )
        return ProviderResult(
            provider=provider_name,
            status=DispatchStatus.TIMEOUT,
            duration_seconds=time.monotonic() - start,
            error_message=f"Timed out after {timeout_seconds}s",
        )
    except OSError as exc:
        logger.warning("%s CLI failed: %s", provider_name.value, exc)
        return ProviderResult(
            provider=provider_name,
            status=DispatchStatus.ERROR,
            duration_seconds=time.monotonic() - start,
            error_message=str(exc),
        )
