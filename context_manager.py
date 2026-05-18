"""In-memory per-user context and lightweight usage statistics."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict


Message = Dict[str, str]


@dataclass(slots=True)
class UsageRecord:
    """One OpenAI API call record stored in RAM for /stats."""

    timestamp: str
    mode: str
    model: str
    planned_temperature: float | None
    actual_temperature: float | None
    reasoning_effort: str | None
    max_output_tokens: int
    response_status: str | None
    incomplete_reason: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    response_id: str | None
    warning: str | None = None


class ContextManager:
    """Stores recent dialogue context for each Telegram user.

    This intentionally uses process memory only, as required by the homework.
    If the bot restarts, all contexts and /stats data are reset.
    """

    def __init__(
        self,
        *,
        max_messages: int = 12,
        max_assistant_chars: int = 1800,
        max_usage_records: int = 100,
    ) -> None:
        self.max_messages = max_messages
        self.max_assistant_chars = max_assistant_chars
        self._contexts: dict[int, list[Message]] = defaultdict(list)
        self._usage: dict[int, Deque[UsageRecord]] = defaultdict(
            lambda: deque(maxlen=max_usage_records)
        )

    def get_messages(self, user_id: int) -> list[Message]:
        """Return a copy of user's current context."""
        return list(self._contexts[user_id])

    def append_user_message(self, user_id: int, text: str) -> None:
        self._append(user_id, {"role": "user", "content": text})

    def append_assistant_message(self, user_id: int, text: str) -> None:
        clipped = self._clip(text, self.max_assistant_chars)
        self._append(user_id, {"role": "assistant", "content": clipped})

    def append_pair(self, user_id: int, user_text: str, assistant_text: str) -> None:
        self.append_user_message(user_id, user_text)
        self.append_assistant_message(user_id, assistant_text)

    def reset(self, user_id: int) -> None:
        self._contexts.pop(user_id, None)
        self._usage.pop(user_id, None)

    def add_usage(self, user_id: int, record: UsageRecord) -> None:
        self._usage[user_id].append(record)

    def get_usage_records(self, user_id: int) -> list[UsageRecord]:
        return list(self._usage[user_id])

    def usage_summary(self, user_id: int) -> dict[str, Any]:
        records = self.get_usage_records(user_id)
        return {
            "requests": len(records),
            "input_tokens": sum(r.input_tokens for r in records),
            "output_tokens": sum(r.output_tokens for r in records),
            "total_tokens": sum(r.total_tokens for r in records),
            "estimated_cost_usd": sum(r.estimated_cost_usd for r in records),
            "last_records": records[-5:],
        }

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _append(self, user_id: int, message: Message) -> None:
        self._contexts[user_id].append(message)
        if len(self._contexts[user_id]) > self.max_messages:
            self._contexts[user_id] = self._contexts[user_id][-self.max_messages :]

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 20].rstrip() + "\n...[truncated]"
