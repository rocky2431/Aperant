"""
Multi-AI Dispatcher
====================

Unified abstraction for dispatching tasks to multiple AI providers
(Claude SDK, Gemini CLI, Codex CLI) with parallel execution,
output parsing, and consensus-based aggregation.

Usage::

    from core.multi_ai import dispatch_to_multiple_ais

    result = await dispatch_to_multiple_ais(
        prompt="Review this code for bugs",
        cwd=project_dir,
        spec_dir=spec_dir,
    )
    for finding in result.high_confidence_findings:
        print(f"[{finding.severity}] {finding.file}:{finding.line} — {finding.title}")
"""

from .dispatcher import MultiAIDispatcher, dispatch_to_multiple_ais
from .types import (
    AggregatedResult,
    DispatchStatus,
    Finding,
    ProviderName,
    ProviderResult,
)

__all__ = [
    "AggregatedResult",
    "DispatchStatus",
    "Finding",
    "MultiAIDispatcher",
    "ProviderName",
    "ProviderResult",
    "dispatch_to_multiple_ais",
]
