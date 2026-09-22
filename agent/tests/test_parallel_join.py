"""Bounded parallel patient/guideline join required by ADR-0013."""

from __future__ import annotations

import asyncio

from app.parallel_join import join_chat_branches


def test_mixed_turn_starts_both_read_only_lanes_before_either_finishes() -> None:
    asyncio.run(_assert_mixed_turn_starts_concurrently())


async def _assert_mixed_turn_starts_concurrently() -> None:
    both_started = asyncio.Event()
    started: set[str] = set()

    async def lane(name: str) -> str:
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.1)
        return f"{name}-evidence-ref"

    joined = await join_chat_branches(
        patient=lambda: lane("patient"),
        guideline=lambda: lane("guideline"),
        patient_timeout_seconds=0.2,
        guideline_timeout_seconds=0.2,
    )

    assert joined.status == "complete"
    assert joined.patient.status == "completed"
    assert joined.guideline is not None and joined.guideline.status == "completed"
    assert joined.patient.value == "patient-evidence-ref"
    assert joined.guideline.value == "guideline-evidence-ref"


def test_optional_lane_failure_preserves_completed_patient_lane() -> None:
    asyncio.run(_assert_optional_lane_failure())


async def _assert_optional_lane_failure() -> None:
    async def patient() -> str:
        return "patient-evidence-ref"

    async def guideline() -> str:
        raise RuntimeError("index details must not escape")

    joined = await join_chat_branches(patient=patient, guideline=guideline)

    assert joined.status == "partial"
    assert joined.patient.status == "completed"
    assert joined.guideline is not None
    assert joined.guideline.status == "failed"
    assert joined.guideline.value is None
    assert joined.guideline.limitation_code == "guideline_retrieval_unavailable"
    assert "index details" not in repr(joined)


def test_guideline_timeout_has_no_unbounded_or_single_leg_fallback() -> None:
    asyncio.run(_assert_guideline_timeout())


async def _assert_guideline_timeout() -> None:
    async def patient() -> str:
        return "patient-evidence-ref"

    async def guideline() -> str:
        await asyncio.sleep(1)
        return "late-ref"

    joined = await join_chat_branches(
        patient=patient,
        guideline=guideline,
        guideline_timeout_seconds=0.01,
    )

    assert joined.status == "partial"
    assert joined.guideline is not None
    assert joined.guideline.status == "unavailable"
    assert joined.guideline.value is None
    assert joined.guideline.limitation_code == "guideline_retrieval_unavailable"


def test_cancellation_produces_one_terminal_result_per_started_lane() -> None:
    asyncio.run(_assert_cancellation_is_terminal())


async def _assert_cancellation_is_terminal() -> None:
    canceled = asyncio.Event()

    async def slow() -> str:
        await asyncio.sleep(1)
        return "late-ref"

    task = asyncio.create_task(join_chat_branches(patient=slow, guideline=slow, canceled=canceled))
    await asyncio.sleep(0)
    canceled.set()
    joined = await asyncio.wait_for(task, timeout=0.1)

    assert joined.status == "canceled"
    assert joined.patient.status == "canceled"
    assert joined.guideline is not None and joined.guideline.status == "canceled"
    assert joined.patient.limitation_code == "turn_canceled"
    assert joined.guideline.limitation_code == "turn_canceled"


def test_patient_only_route_does_not_start_a_guideline_lane() -> None:
    asyncio.run(_assert_patient_only_route())


async def _assert_patient_only_route() -> None:
    called = False

    async def patient() -> str:
        return "patient-evidence-ref"

    async def guideline() -> str:
        nonlocal called
        called = True
        return "unexpected"

    joined = await join_chat_branches(patient=patient)

    assert joined.status == "complete"
    assert joined.guideline is None
    assert called is False
