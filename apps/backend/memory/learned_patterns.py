"""
Ultra Builder Pro — Learned Pattern Tracker
=============================================

Tracks patterns with confidence levels that escalate through confirmation:
  speculation → inference (3+ occurrences) → fact (user confirmed)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .fts_memory import FTSMemory


ConfidenceLevel = Literal["fact", "inference", "speculation"]

# Auto-escalation thresholds
INFERENCE_THRESHOLD = 3  # occurrences to promote speculation → inference


@dataclass
class PatternRecord:
    """A learned pattern with confidence tracking."""
    pattern: str
    confidence: ConfidenceLevel
    occurrences: int
    entry_id: int = 0


class LearnedPatternTracker:
    """Manages pattern learning with confidence escalation.

    New patterns start as 'speculation'. After being observed 3+ times,
    they auto-promote to 'inference'. Only explicit user confirmation
    promotes to 'fact'.

    Usage::

        tracker = LearnedPatternTracker(spec_dir)
        tracker.record_pattern("Always validate email format before saving")
        patterns = tracker.get_confirmed_patterns()
        tracker.close()
    """

    def __init__(self, base_dir: Path) -> None:
        self._memory = FTSMemory(base_dir)

    def record_pattern(self, pattern: str, metadata: dict | None = None) -> PatternRecord:
        """Record a new pattern or increment existing one.

        If the pattern already exists (fuzzy match), increments its
        occurrence count and potentially escalates confidence.
        """
        # Check for existing similar pattern
        existing = self._memory.search(pattern, limit=3)
        for entry in existing:
            if entry.entry_type == "pattern" and _is_similar(entry.content, pattern):
                self._memory.increment_occurrences(entry.id)
                new_occurrences = entry.occurrences + 1
                # Auto-escalate confidence
                new_confidence = entry.confidence
                if (
                    entry.confidence == "speculation"
                    and new_occurrences >= INFERENCE_THRESHOLD
                ):
                    new_confidence = "inference"
                    self._memory.update_confidence(entry.id, "inference")
                return PatternRecord(
                    pattern=entry.content,
                    confidence=new_confidence,
                    occurrences=new_occurrences,
                    entry_id=entry.id,
                )

        # New pattern — start as speculation
        entry_id = self._memory.save_pattern(
            pattern,
            confidence="speculation",
            metadata=metadata,
        )
        return PatternRecord(
            pattern=pattern,
            confidence="speculation",
            occurrences=1,
            entry_id=entry_id,
        )

    def confirm_pattern(self, entry_id: int) -> None:
        """Manually confirm a pattern, promoting it to 'fact'."""
        self._memory.update_confidence(entry_id, "fact")

    def get_confirmed_patterns(self) -> list[PatternRecord]:
        """Get patterns with confidence 'fact' or 'inference'."""
        entries = self._memory.get_patterns()
        return [
            PatternRecord(
                pattern=e.content,
                confidence=e.confidence,
                occurrences=e.occurrences,
                entry_id=e.id,
            )
            for e in entries
            if e.confidence in ("fact", "inference")
        ]

    def get_all_patterns(self) -> list[PatternRecord]:
        """Get all patterns regardless of confidence."""
        entries = self._memory.get_patterns()
        return [
            PatternRecord(
                pattern=e.content,
                confidence=e.confidence,
                occurrences=e.occurrences,
                entry_id=e.id,
            )
            for e in entries
        ]

    def close(self) -> None:
        """Close underlying storage."""
        self._memory.close()


def _is_similar(a: str, b: str) -> bool:
    """Simple similarity check — normalized word overlap > 60%.

    Uses the smaller set size as denominator to handle subset matches.
    """
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    min_len = min(len(words_a), len(words_b))
    return (overlap / min_len) > 0.6
