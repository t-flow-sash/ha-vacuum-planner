"""Pure application commands used by public Home Assistant actions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .domain.models import BlockState, JobState, PlannerState, PlanRevision


def postpone_area(
    state: PlannerState,
    area_id: str,
    now: datetime,
    days: int,
    revision_id: str,
) -> PlannerState:
    """Postpone one configured area by a positive explicit number of days."""
    if days <= 0:
        raise ValueError("postpone_days must be positive")
    if not any(plan.area_id == area_id for plan in state.plan_revision.room_plans):
        raise KeyError(area_id)
    plans = tuple(
        replace(plan, skip_until=now + timedelta(days=days)) if plan.area_id == area_id else plan
        for plan in state.plan_revision.room_plans
    )
    revision = PlanRevision(revision_id, now, plans)
    return replace(state, plan_revision=revision)


def skip_area_today(
    state: PlannerState,
    area_id: str,
    now: datetime,
    time_zone: str,
    revision_id: str,
) -> PlannerState:
    """Skip one area until the next midnight in Home Assistant's timezone."""
    try:
        zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as err:
        raise ValueError("Home Assistant time zone is invalid") from err
    local_now = now.astimezone(zone)
    next_date = local_now.date() + timedelta(days=1)
    skip_until = datetime.combine(next_date, time.min, tzinfo=zone).astimezone(UTC)
    if not any(plan.area_id == area_id for plan in state.plan_revision.room_plans):
        raise KeyError(area_id)
    plans = tuple(
        replace(plan, skip_until=skip_until) if plan.area_id == area_id else plan
        for plan in state.plan_revision.room_plans
    )
    return replace(state, plan_revision=PlanRevision(revision_id, now, plans))


def cancel_pending_block(
    state: PlannerState,
    block_id: str,
    cancelled_at: datetime,
) -> PlannerState:
    """Cancel only a sealed block whose jobs cannot have external side effects."""
    block = next((item for item in state.ledger.blocks if item.block_id == block_id), None)
    if block is None:
        raise KeyError(block_id)
    if block.state is not BlockState.SEALED:
        raise ValueError(
            "block may have external work; adapter cancellation confirmation is not implemented"
        )
    jobs = tuple(job for job in state.ledger.jobs if job.block_id == block_id)
    if not jobs or any(job.state is not JobState.PENDING for job in jobs):
        raise ValueError(
            "block may have external work; adapter cancellation confirmation is not implemented"
        )
    ledger = state.ledger
    for job in jobs:
        ledger = ledger.replace_job_state(job.job_id, JobState.CANCELLED, cancelled_at)
    ledger = ledger.replace_block_state(block_id, BlockState.CANCELLED, cancelled_at)
    return replace(state, ledger=ledger)
