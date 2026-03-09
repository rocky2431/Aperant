"""
Multi-AI Dispatcher — Orchestrator
====================================

Dispatches prompts to multiple AI providers in parallel, aggregates results,
and computes consensus findings. Degrades gracefully when external CLIs
are unavailable.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .config import DispatcherConfig, load_dispatcher_config
from .detection import detect_available_providers
from .providers import AIProvider, ClaudeProvider, CodexProvider, GeminiProvider
from .types import (
    AggregatedResult,
    DispatchStatus,
    Finding,
    ProviderName,
    ProviderResult,
)

logger = logging.getLogger(__name__)

# Proximity bucket size for dedup (same as review_coordinator.py)
_PROXIMITY_BUCKET_SIZE = 4
_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


class MultiAIDispatcher:
    """Orchestrates parallel dispatch to multiple AI providers."""

    def __init__(self, config: DispatcherConfig | None = None) -> None:
        self._config = config or DispatcherConfig()
        self._providers: dict[ProviderName, AIProvider] = {
            ProviderName.CLAUDE: ClaudeProvider(),
            ProviderName.GEMINI: GeminiProvider(),
            ProviderName.CODEX: CodexProvider(),
        }

    async def dispatch(
        self,
        prompt: str,
        cwd: Path,
        timeout_seconds: int | None = None,
        spec_dir: Path | None = None,
    ) -> AggregatedResult:
        """Dispatch a prompt to configured providers and aggregate results.

        Args:
            prompt: The prompt to send to all providers
            cwd: Working directory (project_dir)
            timeout_seconds: Override timeout (uses config default if None)
            spec_dir: Optional spec directory for Claude SDK configuration

        Returns:
            AggregatedResult with merged findings and consensus verdict
        """
        timeout = timeout_seconds or self._config.timeout_seconds
        available = detect_available_providers()

        # Filter to providers that are both configured and available
        active_providers = [
            p for p in self._config.providers if p in available
        ]

        if not active_providers:
            active_providers = [ProviderName.CLAUDE]

        logger.info(
            "Dispatching to %d providers: %s",
            len(active_providers),
            [p.value for p in active_providers],
        )

        # Dispatch to all active providers
        if self._config.parallel and len(active_providers) > 1:
            results = await self._dispatch_parallel(
                prompt, cwd, active_providers, timeout, spec_dir
            )
        else:
            results = await self._dispatch_sequential(
                prompt, cwd, active_providers, timeout, spec_dir
            )

        return _aggregate_results(results)

    async def _dispatch_parallel(
        self,
        prompt: str,
        cwd: Path,
        providers: list[ProviderName],
        timeout: int,
        spec_dir: Path | None,
    ) -> list[ProviderResult]:
        """Dispatch to multiple providers in parallel."""
        tasks = []
        for provider_name in providers:
            provider = self._providers[provider_name]
            if provider_name == ProviderName.CLAUDE:
                tasks.append(
                    provider.dispatch(prompt, cwd, timeout, spec_dir=spec_dir)
                )
            else:
                tasks.append(provider.dispatch(prompt, cwd, timeout))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for i, result in enumerate(raw_results):
            if isinstance(result, Exception):
                logger.warning(
                    "Provider %s raised: %s", providers[i].value, result
                )
                results.append(
                    ProviderResult(
                        provider=providers[i],
                        status=DispatchStatus.ERROR,
                        error_message=str(result),
                    )
                )
            else:
                results.append(result)

        return results

    async def _dispatch_sequential(
        self,
        prompt: str,
        cwd: Path,
        providers: list[ProviderName],
        timeout: int,
        spec_dir: Path | None,
    ) -> list[ProviderResult]:
        """Dispatch to providers sequentially."""
        results = []
        for provider_name in providers:
            provider = self._providers[provider_name]
            try:
                if provider_name == ProviderName.CLAUDE:
                    result = await provider.dispatch(
                        prompt, cwd, timeout, spec_dir=spec_dir
                    )
                else:
                    result = await provider.dispatch(prompt, cwd, timeout)
                results.append(result)
            except Exception as exc:
                logger.warning("Provider %s failed: %s", provider_name.value, exc)
                results.append(
                    ProviderResult(
                        provider=provider_name,
                        status=DispatchStatus.ERROR,
                        error_message=str(exc),
                    )
                )
        return results


def _aggregate_results(results: list[ProviderResult]) -> AggregatedResult:
    """Aggregate results from multiple providers.

    Performs:
    - Finding collection from all providers
    - Proximity-based deduplication (reuses review_coordinator algorithm)
    - Consensus verdict via majority vote
    - High-confidence finding identification (2+ providers agree)

    Args:
        results: List of ProviderResult from dispatched providers

    Returns:
        AggregatedResult with merged and deduplicated findings
    """
    aggregated = AggregatedResult()

    for result in results:
        aggregated.provider_results[result.provider.value] = result
        if result.status == DispatchStatus.SUCCESS:
            aggregated.providers_succeeded.append(result.provider.value)
        else:
            aggregated.providers_failed.append(result.provider.value)

    # Collect all findings
    all_findings: list[Finding] = []
    for result in results:
        if result.status == DispatchStatus.SUCCESS:
            all_findings.extend(result.findings)

    # Deduplicate using proximity bucketing
    aggregated.findings, aggregated.high_confidence_findings = _deduplicate_findings(
        all_findings
    )

    # Compute consensus verdict
    verdicts = [
        r.verdict for r in results
        if r.status == DispatchStatus.SUCCESS and r.verdict
    ]
    aggregated.consensus_verdict = _majority_verdict(verdicts)

    logger.info(
        "Aggregated: %d findings (%d high-confidence), verdict=%s, "
        "succeeded=%s, failed=%s",
        len(aggregated.findings),
        len(aggregated.high_confidence_findings),
        aggregated.consensus_verdict,
        aggregated.providers_succeeded,
        aggregated.providers_failed,
    )

    return aggregated


def _deduplicate_findings(
    findings: list[Finding],
) -> tuple[list[Finding], list[Finding]]:
    """Deduplicate findings using proximity bucketing.

    Groups findings by (file, line // bucket_size) and picks the
    highest-severity finding as representative. Findings confirmed
    by 2+ providers are marked as high-confidence.

    Args:
        findings: All findings from all providers

    Returns:
        Tuple of (all deduplicated findings, high-confidence findings)
    """
    if not findings:
        return [], []

    # Group by proximity bucket
    buckets: dict[tuple[str, int], list[Finding]] = {}
    for finding in findings:
        key = (finding.file, finding.line // _PROXIMITY_BUCKET_SIZE)
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(finding)

    deduped: list[Finding] = []
    high_confidence: list[Finding] = []

    for _bucket_key, bucket_findings in buckets.items():
        # Pick highest-severity finding
        bucket_findings.sort(
            key=lambda f: _SEVERITY_ORDER.get(f.severity, 3)
        )
        representative = bucket_findings[0]

        # Check how many unique providers contributed
        unique_providers = {f.provider for f in bucket_findings}

        # Escalate severity if 3+ providers agree
        if len(unique_providers) >= 3:
            representative = Finding(
                provider=representative.provider,
                severity="critical",
                category=representative.category,
                file=representative.file,
                line=representative.line,
                title=representative.title,
                suggestion=representative.suggestion,
                confidence=representative.confidence,
            )

        deduped.append(representative)

        if len(unique_providers) >= 2:
            high_confidence.append(representative)

    # Sort by severity
    deduped.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 3))
    high_confidence.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 3))

    return deduped, high_confidence


def _majority_verdict(verdicts: list[str]) -> str:
    """Compute majority verdict from provider verdicts.

    Args:
        verdicts: List of verdict strings from providers

    Returns:
        Consensus verdict: "APPROVE", "REJECT", or "COMMENT"
    """
    if not verdicts:
        return ""

    # Count votes
    counts: dict[str, int] = {}
    for v in verdicts:
        normalized = v.upper()
        counts[normalized] = counts.get(normalized, 0) + 1

    # Return most common
    return max(counts, key=lambda k: counts[k])


async def dispatch_to_multiple_ais(
    prompt: str,
    cwd: Path,
    spec_dir: Path | None = None,
    timeout_seconds: int = 300,
) -> AggregatedResult:
    """Convenience function to dispatch a prompt to multiple AI providers.

    Creates a dispatcher with configuration from environment/task metadata,
    dispatches the prompt, and returns aggregated results.

    Args:
        prompt: The prompt to send
        cwd: Working directory (project_dir)
        spec_dir: Optional spec directory for configuration and Claude SDK
        timeout_seconds: Maximum time per provider

    Returns:
        AggregatedResult with merged findings and consensus verdict
    """
    config = load_dispatcher_config(spec_dir)
    if not config.enabled:
        # Multi-AI disabled — run Claude only
        config.providers = [ProviderName.CLAUDE]

    config.timeout_seconds = timeout_seconds

    dispatcher = MultiAIDispatcher(config)
    return await dispatcher.dispatch(prompt, cwd, spec_dir=spec_dir)
