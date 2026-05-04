"""Session-level token usage tracker.

Accumulates per-turn RunUsage into a session-scoped summary that can be
used for billing, monitoring, and periodic log emission.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic_ai import RunUsage


@dataclass
class UsageTracker:
    """Accumulates LLM token usage across multiple turns within a session."""

    session_id: str
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0
    turn_count: int = 0
    _created_at: float = field(default_factory=time.time)
    _last_recorded_at: float = 0.0

    def record(self, usage: RunUsage) -> None:
        """Accumulate a single agent run's usage into session totals."""
        self.total_requests += usage.requests
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_tool_calls += usage.tool_calls
        self.turn_count += 1
        self._last_recorded_at = time.time()

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def duration_seconds(self) -> float:
        return round(time.time() - self._created_at, 1)

    def summary(self) -> dict:
        """Return a serializable summary dict for logging / upstream reporting."""
        return {
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "total_requests": self.total_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "duration_seconds": self.duration_seconds,
        }
