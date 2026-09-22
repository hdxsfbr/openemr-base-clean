"""Durable, PHI-free operational controls accepted in ADR-0014."""

from __future__ import annotations

import sqlite3
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from .metrics import metrics
from .model import ModelError, ModelPort, NarrateResult, PlanResult, Usage

MICRO_USD = Decimal("1000000")
WARNING_USD = Decimal("14")
HARD_LIMIT_USD = Decimal("20")
SONNET5_USD_PER_MTOK = {
    "input": Decimal("2.00"),
    "output": Decimal("10.00"),
    "cache_read": Decimal("0.20"),
    "cache_creation": Decimal("2.50"),
}


@dataclass(frozen=True)
class SpendDecision:
    accepted: bool
    warning: bool
    outcome: Literal["created", "replayed", "refused", "settled"]
    total_usd: Decimal
    reason: Literal["reserved", "daily_limit", "settled"]


@dataclass(frozen=True)
class SpendAvailability:
    available: bool
    warning: bool
    total_usd: Decimal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.__dict__.values()):
            raise ValueError("token counts cannot be negative")


@dataclass(frozen=True)
class ExtractionEnvelopeUsage:
    temporary_bytes: int
    ocr_text_bytes: int
    positioned_tokens: int
    maximum_page_tokens: int
    serialized_bytes: int

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.__dict__.values()):
            raise ValueError("extraction usage cannot be negative")


@dataclass(frozen=True)
class ExtractionAdmission:
    allowed: bool
    reason: str | None
    storage_warning: bool
    delete_existing: Literal[False] = False


def assess_extraction_admission(
    *,
    existing_versions: int,
    retained_derivative_bytes: int,
    disk_total_bytes: int,
    disk_free_bytes: int,
    proposed: ExtractionEnvelopeUsage,
) -> ExtractionAdmission:
    """Apply immutable version, per-source, per-job, and host-disk bounds."""

    if min(existing_versions, retained_derivative_bytes, disk_total_bytes, disk_free_bytes) < 0:
        raise ValueError("storage observations cannot be negative")
    if disk_total_bytes <= 0 or disk_free_bytes > disk_total_bytes:
        raise ValueError("disk totals are invalid")
    used_ratio = Decimal(disk_total_bytes - disk_free_bytes) / Decimal(disk_total_bytes)
    warning = used_ratio >= Decimal("0.70")
    reason: str | None = None
    if existing_versions >= 3:
        reason = "extraction_version_limit"
    elif proposed.temporary_bytes > 1024**3:
        reason = "temporary_storage_limit"
    elif proposed.ocr_text_bytes > 2_000_000:
        reason = "ocr_text_limit"
    elif proposed.maximum_page_tokens > 10_000 or proposed.positioned_tokens > 100_000:
        reason = "ocr_token_limit"
    elif proposed.serialized_bytes > 30 * 1024**2:
        reason = "extraction_payload_limit"
    elif retained_derivative_bytes + proposed.serialized_bytes > 100 * 1024**2:
        reason = "source_storage_limit"
    elif disk_free_bytes < 10 * 1024**3 or used_ratio >= Decimal("0.90"):
        reason = "host_storage_unavailable"
    return ExtractionAdmission(allowed=reason is None, reason=reason, storage_warning=warning)


def sweep_transient_directories(
    root: Path,
    *,
    now: datetime,
    maximum_age: timedelta = timedelta(hours=1),
) -> list[str]:
    """Remove only explicitly marked, direct-child transient job directories."""

    _require_utc(now)
    if maximum_age <= timedelta(0):
        raise ValueError("maximum transient age must be positive")
    if root.is_symlink() or not root.is_dir() or root.resolve() == Path(root.anchor):
        raise ValueError("transient root must be a concrete bounded directory")
    cutoff = now.timestamp() - maximum_age.total_seconds()
    removed: list[str] = []
    for candidate in sorted(root.iterdir(), key=lambda path: path.name):
        marker = candidate / ".copilot-transient"
        if candidate.is_symlink() or not candidate.is_dir() or not marker.is_file() or marker.is_symlink():
            continue
        if marker.stat().st_mtime > cutoff:
            continue
        shutil.rmtree(candidate)
        removed.append(candidate.name)
    return removed


def price_sonnet5_usage(usage: TokenUsage) -> Decimal:
    """Versioned Sonnet 5 list price, including cache writes (2026-09-15)."""

    total = (
        Decimal(usage.input_tokens) * SONNET5_USD_PER_MTOK["input"]
        + Decimal(usage.output_tokens) * SONNET5_USD_PER_MTOK["output"]
        + Decimal(usage.cache_read_tokens) * SONNET5_USD_PER_MTOK["cache_read"]
        + Decimal(usage.cache_creation_tokens) * SONNET5_USD_PER_MTOK["cache_creation"]
    )
    return total / Decimal("1000000")


class BudgetedModel:
    """Reserve before every provider call and settle all four token classes."""

    def __init__(
        self,
        provider: ModelPort,
        *,
        ledger: "DailySpendLedger",
        reservation_usd: Decimal,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._provider = provider
        self._ledger = ledger
        self._reservation_usd = reservation_usd
        self._now = now

    async def narrate(
        self,
        question: str,
        pack_text: str,
        effort: str,
        rejections: list[dict[str, str]] | None = None,
        correlation_id: str | None = None,
    ) -> NarrateResult:
        reservation_id = self._reserve("narrate")
        try:
            result = await self._provider.narrate(
                question,
                pack_text,
                effort,
                rejections=rejections,
                correlation_id=correlation_id,
            )
        except Exception:
            self._settle(reservation_id, "narrate", Usage())
            raise
        self._settle(reservation_id, "narrate", result.usage)
        return result

    async def plan(
        self,
        question: str,
        pack_text: str,
        prior_calls: list[tuple[str, dict]],
        correlation_id: str | None = None,
    ) -> PlanResult:
        reservation_id = self._reserve("plan")
        try:
            result = await self._provider.plan(
                question,
                pack_text,
                prior_calls,
                correlation_id=correlation_id,
            )
        except Exception:
            self._settle(reservation_id, "plan", Usage())
            raise
        self._settle(reservation_id, "plan", result.usage)
        return result

    def _reserve(self, operation: str) -> str:
        reservation_id = f"{operation}-{uuid4()}"
        decision = self._ledger.reserve(
            reservation_id=reservation_id,
            operation=operation,
            maximum_usd=self._reservation_usd,
            now=self._now(),
        )
        if not decision.accepted:
            raise ModelError("model_budget_exhausted")
        return reservation_id

    def _settle(self, reservation_id: str, operation: str, usage: Usage) -> None:
        cost = price_sonnet5_usage(TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
        ))
        decision = self._ledger.settle(
            reservation_id=reservation_id,
            actual_usd=cost,
            now=self._now(),
        )
        metrics.model_spend(operation, float(cost), float(decision.total_usd))


class DailySpendLedger:
    """Atomic reservation/settlement ledger shared through one SQLite file."""

    def __init__(
        self,
        path: Path,
        *,
        warning_usd: Decimal = WARNING_USD,
        hard_limit_usd: Decimal = HARD_LIMIT_USD,
    ) -> None:
        if warning_usd < 0 or hard_limit_usd <= 0 or warning_usd >= hard_limit_usd:
            raise ValueError("spend thresholds must be ordered and positive")
        self._path = path
        self._warning = _microusd(warning_usd)
        self._hard_limit = _microusd(hard_limit_usd)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS spend_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    utc_day TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    reserved_microusd INTEGER NOT NULL CHECK (reserved_microusd >= 0),
                    actual_microusd INTEGER CHECK (actual_microusd >= 0),
                    created_at TEXT NOT NULL,
                    settled_at TEXT
                )
                """
            )

    def reserve(
        self,
        *,
        reservation_id: str,
        operation: str,
        maximum_usd: Decimal,
        now: datetime,
    ) -> SpendDecision:
        _require_utc(now)
        if not reservation_id or len(reservation_id) > 128 or not operation or len(operation) > 64:
            raise ValueError("reservation identity and operation must be bounded")
        maximum = _microusd(maximum_usd)
        day = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT utc_day, operation, reserved_microusd, actual_microusd FROM spend_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != day or existing[1] != operation or existing[2] != maximum:
                    raise ValueError("reservation ID was reused with different immutable inputs")
                total = self._total(connection, day)
                return self._decision(True, "replayed", total, "settled" if existing[3] is not None else "reserved")

            total = self._total(connection, day)
            projected = total + maximum
            if projected > self._hard_limit:
                return self._decision(False, "refused", total, "daily_limit")
            connection.execute(
                """
                INSERT INTO spend_reservations
                    (reservation_id, utc_day, operation, reserved_microusd, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (reservation_id, day, operation, maximum, _iso(now)),
            )
            return self._decision(True, "created", projected, "reserved")

    def availability(self, *, maximum_usd: Decimal, now: datetime) -> SpendAvailability:
        _require_utc(now)
        maximum = _microusd(maximum_usd)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            total = self._total(connection, now.date().isoformat())
        return SpendAvailability(
            available=total + maximum <= self._hard_limit,
            warning=total >= self._warning,
            total_usd=Decimal(total) / MICRO_USD,
        )

    def settle(
        self,
        *,
        reservation_id: str,
        actual_usd: Decimal,
        now: datetime,
    ) -> SpendDecision:
        _require_utc(now)
        actual = _microusd(actual_usd)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT utc_day, actual_microusd FROM spend_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if existing is None:
                raise ValueError("cannot settle an unknown reservation")
            day, prior_actual = existing
            if prior_actual is not None:
                if prior_actual != actual:
                    raise ValueError("settlement replay differs from the recorded actual cost")
                return self._decision(True, "replayed", self._total(connection, day), "settled")
            connection.execute(
                "UPDATE spend_reservations SET actual_microusd = ?, settled_at = ? WHERE reservation_id = ?",
                (actual, _iso(now), reservation_id),
            )
            return self._decision(True, "settled", self._total(connection, day), "settled")

    @staticmethod
    def _total(connection: sqlite3.Connection, day: str) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(COALESCE(actual_microusd, reserved_microusd)), 0)
            FROM spend_reservations WHERE utc_day = ?
            """,
            (day,),
        ).fetchone()
        return int(row[0])

    def _decision(self, accepted: bool, outcome: str, total: int, reason: str) -> SpendDecision:
        return SpendDecision(
            accepted=accepted,
            warning=total >= self._warning,
            outcome=outcome,
            total_usd=Decimal(total) / MICRO_USD,
            reason=reason,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def _microusd(value: Decimal) -> int:
    if not value.is_finite() or value < 0:
        raise ValueError("cost must be a non-negative finite decimal")
    return int((value * MICRO_USD).to_integral_value(rounding=ROUND_CEILING))


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("ledger timestamps must be UTC")


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
