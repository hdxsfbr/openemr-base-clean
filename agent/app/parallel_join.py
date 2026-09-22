"""Bounded, lane-local join for patient and guideline evidence.

The coordinator carries only opaque in-process values. It neither verifies
claims nor allows one branch to substitute for the other.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, Literal, TypeVar

T = TypeVar("T")
LaneName = Literal["patient", "guideline"]
LaneStatus = Literal["completed", "unavailable", "failed", "canceled"]
JoinStatus = Literal["complete", "partial", "unavailable", "failed", "canceled"]


@dataclass(frozen=True)
class LaneTerminal(Generic[T]):
    lane: LaneName
    status: LaneStatus
    value: T | None = None
    limitation_code: str | None = None


@dataclass(frozen=True)
class JoinedBranches(Generic[T]):
    status: JoinStatus
    patient: LaneTerminal[T]
    guideline: LaneTerminal[T] | None


async def join_chat_branches(
    *,
    patient: Callable[[], Awaitable[T]],
    guideline: Callable[[], Awaitable[T]] | None = None,
    canceled: asyncio.Event | None = None,
    patient_timeout_seconds: float = 45.0,
    guideline_timeout_seconds: float = 2.0,
) -> JoinedBranches[T]:
    """Start every selected read branch concurrently and join terminal states.

    Exceptions and timeout details are deliberately collapsed to fixed codes;
    raw source content and dependency messages never enter the join result.
    """

    cancel_event = canceled or asyncio.Event()
    patient_task = asyncio.create_task(
        _run_lane("patient", patient, cancel_event, patient_timeout_seconds),
    )
    guideline_task = (
        asyncio.create_task(
            _run_lane("guideline", guideline, cancel_event, guideline_timeout_seconds),
        )
        if guideline is not None
        else None
    )
    if guideline_task is None:
        patient_result = await patient_task
        return JoinedBranches(status=_single_status(patient_result), patient=patient_result, guideline=None)

    patient_result, guideline_result = await asyncio.gather(patient_task, guideline_task)
    return JoinedBranches(
        status=_joined_status(patient_result, guideline_result),
        patient=patient_result,
        guideline=guideline_result,
    )


async def _run_lane(
    lane: LaneName,
    operation: Callable[[], Awaitable[T]],
    canceled: asyncio.Event,
    timeout_seconds: float,
) -> LaneTerminal[T]:
    if canceled.is_set():
        return _terminal(lane, "canceled")
    if timeout_seconds <= 0:
        return _terminal(lane, "unavailable")

    operation_task = asyncio.create_task(_invoke(operation))
    cancellation_task = asyncio.create_task(canceled.wait())
    try:
        done, _ = await asyncio.wait(
            {operation_task, cancellation_task},
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation_task in done and canceled.is_set():
            operation_task.cancel()
            await _drain(operation_task)
            return _terminal(lane, "canceled")
        if operation_task not in done:
            operation_task.cancel()
            await _drain(operation_task)
            return _terminal(lane, "unavailable")
        try:
            return LaneTerminal(lane=lane, status="completed", value=operation_task.result())
        except asyncio.CancelledError:
            return _terminal(lane, "canceled")
        except Exception:  # noqa: BLE001 - dependency detail must not escape
            return _terminal(lane, "failed")
    finally:
        cancellation_task.cancel()
        await _drain(cancellation_task)


async def _invoke(operation: Callable[[], Awaitable[T]]) -> T:
    return await operation()


async def _drain(task: asyncio.Task[object]) -> None:
    with suppress(asyncio.CancelledError, Exception):
        await task


def _terminal(lane: LaneName, status: LaneStatus) -> LaneTerminal[T]:
    if status == "canceled":
        code = "turn_canceled"
    elif lane == "guideline":
        code = "guideline_retrieval_unavailable"
    else:
        code = "patient_retrieval_unavailable"
    return LaneTerminal(lane=lane, status=status, limitation_code=code)


def _single_status(result: LaneTerminal[object]) -> JoinStatus:
    return {
        "completed": "complete",
        "unavailable": "unavailable",
        "failed": "failed",
        "canceled": "canceled",
    }[result.status]


def _joined_status(patient: LaneTerminal[object], guideline: LaneTerminal[object]) -> JoinStatus:
    statuses = {patient.status, guideline.status}
    if statuses == {"completed"}:
        return "complete"
    if "completed" in statuses:
        return "partial"
    if statuses == {"canceled"}:
        return "canceled"
    if "failed" in statuses:
        return "failed"
    return "unavailable"
