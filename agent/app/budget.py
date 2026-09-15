"""Token budgets and the daily halt (ADR-0004 decision 5; Week 3 cost defense)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .settings import settings


@dataclass
class DailySpend:
    day: str = ""
    tokens: int = 0
    halted: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, tokens: int) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self.lock:
            if self.day != today:
                self.day, self.tokens, self.halted = today, 0, False
            self.tokens += tokens
            if self.tokens >= settings.daily_token_halt:
                self.halted = True

    def is_halted(self) -> bool:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self.lock:
            return self.halted and self.day == today

    def reset(self) -> None:
        with self.lock:
            self.day, self.tokens, self.halted = "", 0, False


daily = DailySpend()


def check(turn_tokens: int, conversation_tokens: int) -> str | None:
    """Returns a limitation kind when a budget forbids a model call, else None."""
    if daily.is_halted():
        return "model_budget_exhausted"
    if turn_tokens >= settings.tokens_per_turn or conversation_tokens >= settings.tokens_per_conversation:
        return "model_budget_exhausted"
    return None
