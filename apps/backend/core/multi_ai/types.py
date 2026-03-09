"""
Multi-AI Dispatcher — Data Types
=================================

Core data structures for multi-AI dispatch: provider names, dispatch status,
findings, provider results, and aggregated results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProviderName(str, Enum):
    """Supported AI provider names."""

    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"


class DispatchStatus(str, Enum):
    """Status of a provider dispatch attempt."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    NOT_AVAILABLE = "not_available"
    ERROR = "error"


@dataclass
class Finding:
    """A single finding from an AI provider review."""

    provider: str  # "claude" | "gemini" | "codex"
    severity: str  # "critical" | "major" | "minor"
    category: str
    file: str
    line: int
    title: str
    suggestion: str
    confidence: float = 0.0


@dataclass
class ProviderResult:
    """Result from a single AI provider dispatch."""

    provider: ProviderName
    status: DispatchStatus
    raw_output: str = ""
    findings: list[Finding] = field(default_factory=list)
    verdict: str = ""
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class AggregatedResult:
    """Aggregated result from multiple AI providers."""

    provider_results: dict[str, ProviderResult] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    high_confidence_findings: list[Finding] = field(default_factory=list)
    consensus_verdict: str = ""
    providers_succeeded: list[str] = field(default_factory=list)
    providers_failed: list[str] = field(default_factory=list)

    @property
    def has_results(self) -> bool:
        """Return True if at least one provider succeeded."""
        return len(self.providers_succeeded) > 0
