"""Durable Week 2 cost, capacity, and retention controls."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import sqlite3
from types import SimpleNamespace

import pytest

from app.model import ModelError, NarrateResult, _usage_of
from app.state_store import mark_conversation_closed, sweep_closed_checkpoints
from app.week2_operations import (
    BudgetedModel,
    DailySpendLedger,
    ExtractionEnvelopeUsage,
    TokenUsage,
    assess_extraction_admission,
    price_sonnet5_usage,
    sweep_transient_directories,
)


UTC = timezone.utc


def test_daily_spend_reservations_survive_restart_and_settle_idempotently(tmp_path) -> None:
    path = tmp_path / "week2-operations.sqlite3"
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    first = DailySpendLedger(path)

    reservation = first.reserve(
        reservation_id="chat-turn-0001",
        operation="chat",
        maximum_usd=Decimal("0.15"),
        now=now,
    )
    replay = DailySpendLedger(path).reserve(
        reservation_id="chat-turn-0001",
        operation="chat",
        maximum_usd=Decimal("0.15"),
        now=now,
    )
    settlement = DailySpendLedger(path).settle(
        reservation_id="chat-turn-0001",
        actual_usd=Decimal("0.03125"),
        now=now,
    )
    settlement_replay = DailySpendLedger(path).settle(
        reservation_id="chat-turn-0001",
        actual_usd=Decimal("0.03125"),
        now=now,
    )

    assert reservation.accepted is True
    assert reservation.outcome == "created"
    assert replay.outcome == "replayed"
    assert settlement.outcome == "settled"
    assert settlement_replay.outcome == "replayed"
    assert settlement.total_usd == Decimal("0.031250")


def test_daily_spend_warns_at_fourteen_refuses_above_twenty_and_rolls_over_utc(tmp_path) -> None:
    ledger = DailySpendLedger(tmp_path / "ledger.sqlite3")
    day_one = datetime(2026, 9, 21, 23, 59, tzinfo=UTC)

    assert ledger.reserve(
        reservation_id="first", operation="chat", maximum_usd=Decimal("13.99"), now=day_one
    ).warning is False
    warning = ledger.reserve(
        reservation_id="second", operation="chat", maximum_usd=Decimal("0.01"), now=day_one
    )
    at_limit = ledger.reserve(
        reservation_id="third", operation="extraction", maximum_usd=Decimal("6"), now=day_one
    )
    refused = ledger.reserve(
        reservation_id="fourth", operation="chat", maximum_usd=Decimal("0.000001"), now=day_one
    )
    next_day = ledger.reserve(
        reservation_id="next-day", operation="chat", maximum_usd=Decimal("0.15"),
        now=datetime(2026, 9, 22, 0, 0, tzinfo=UTC),
    )

    assert warning.warning is True and warning.total_usd == Decimal("14")
    assert at_limit.accepted is True and at_limit.total_usd == Decimal("20")
    assert refused.accepted is False and refused.reason == "daily_limit"
    assert next_day.accepted is True and next_day.total_usd == Decimal("0.15")


def test_model_cost_prices_every_provider_billing_token_class() -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_creation_tokens=1_000_000,
    )

    assert price_sonnet5_usage(usage) == Decimal("14.700000")


def test_provider_usage_preserves_cache_creation_tokens() -> None:
    usage = _usage_of(SimpleNamespace(usage=SimpleNamespace(
        input_tokens=100,
        output_tokens=25,
        cache_read_input_tokens=300,
        cache_creation_input_tokens=400,
    )))

    assert usage.cache_creation_tokens == 400


@pytest.mark.anyio
async def test_budgeted_model_refuses_before_provider_call_when_daily_room_is_insufficient(tmp_path) -> None:
    class Provider:
        calls = 0

        async def narrate(self, *args, **kwargs):
            self.calls += 1
            return NarrateResult(None, _usage_of(SimpleNamespace(usage=None)), "unused")

        async def plan(self, *args, **kwargs):
            raise AssertionError("not used")

    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    ledger = DailySpendLedger(tmp_path / "ledger.sqlite3")
    assert ledger.reserve(
        reservation_id="existing-spend",
        operation="extraction",
        maximum_usd=Decimal("19.90"),
        now=now,
    ).accepted
    provider = Provider()
    model = BudgetedModel(provider, ledger=ledger, reservation_usd=Decimal("0.15"), now=lambda: now)

    with pytest.raises(ModelError, match="model_budget_exhausted"):
        await model.narrate("question", "pack", "low")

    assert provider.calls == 0


def test_extraction_admission_refuses_fourth_version_without_deleting_history() -> None:
    decision = assess_extraction_admission(
        existing_versions=3,
        retained_derivative_bytes=30_000_000,
        disk_total_bytes=50 * 1024**3,
        disk_free_bytes=30 * 1024**3,
        proposed=ExtractionEnvelopeUsage(
            temporary_bytes=100_000_000,
            ocr_text_bytes=500_000,
            positioned_tokens=5_000,
            maximum_page_tokens=1_000,
            serialized_bytes=5_000_000,
        ),
    )

    assert decision.allowed is False
    assert decision.reason == "extraction_version_limit"
    assert decision.delete_existing is False


def test_transient_sweeper_removes_only_marked_job_directories_older_than_one_hour(tmp_path) -> None:
    old_marked = tmp_path / "job-old-marked"
    old_unmarked = tmp_path / "source-record-must-stay"
    new_marked = tmp_path / "job-new-marked"
    for directory in (old_marked, old_unmarked, new_marked):
        directory.mkdir()
        (directory / "page.png").write_bytes(b"synthetic")
    (old_marked / ".copilot-transient").touch()
    (new_marked / ".copilot-transient").touch()
    old_epoch = datetime(2026, 9, 21, 10, 0, tzinfo=UTC).timestamp()
    for path in (old_marked, old_marked / ".copilot-transient", old_unmarked):
        os.utime(path, (old_epoch, old_epoch))
    new_epoch = datetime(2026, 9, 21, 11, 30, tzinfo=UTC).timestamp()
    for path in (new_marked, new_marked / ".copilot-transient"):
        os.utime(path, (new_epoch, new_epoch))

    removed = sweep_transient_directories(
        tmp_path,
        now=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
    )

    assert removed == ["job-old-marked"]
    assert not old_marked.exists()
    assert old_unmarked.exists()
    assert new_marked.exists()


def test_closed_conversation_sweeper_removes_checkpoints_after_twenty_four_hours(tmp_path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE checkpoints (
                thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT,
                parent_checkpoint_id TEXT, type TEXT, checkpoint BLOB, metadata BLOB
            );
            CREATE TABLE writes (
                thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT,
                task_id TEXT, idx INTEGER, channel TEXT, type TEXT, value BLOB
            );
        """)
        for conversation in ("expired-conversation", "recent-conversation"):
            connection.execute(
                "INSERT INTO checkpoints(thread_id, checkpoint_ns, checkpoint_id) VALUES (?, '', 'one')",
                (conversation,),
            )
            connection.execute(
                "INSERT INTO writes(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel) VALUES (?, '', 'one', 'task', 0, 'state')",
                (conversation,),
            )
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    mark_conversation_closed(path, "expired-conversation", closed_at=datetime(2026, 9, 20, 10, 0, tzinfo=UTC))
    mark_conversation_closed(path, "recent-conversation", closed_at=datetime(2026, 9, 20, 13, 0, tzinfo=UTC))

    assert sweep_closed_checkpoints(path, now=now) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT thread_id FROM checkpoints").fetchall() == [("recent-conversation",)]
        assert connection.execute("SELECT thread_id FROM writes").fetchall() == [("recent-conversation",)]
