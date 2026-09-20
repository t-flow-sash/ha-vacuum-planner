"""Translate vacuum state observations into persisted planner transitions."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

from .adapters.observation import ObservationOutcome, normalize_observation
from .domain.models import BlockState, JobState, PlannerState
from .domain.queue import complete_job_and_advance_plan

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from .const import VacuumPlannerRuntimeData


def _dispatching_block_ids(state: PlannerState, observed_at: datetime) -> set[str]:
    committing = {
        block.block_id for block in state.ledger.blocks if block.state is BlockState.COMMITTING
    }
    return {
        job.block_id
        for job in state.ledger.jobs
        if job.block_id in committing
        and job.state is JobState.DISPATCHING
        and job.sent_at is not None
        and observed_at >= job.sent_at
    }


def _running(state: PlannerState, observed_at: datetime) -> PlannerState:
    ledger = state.ledger
    dispatching_blocks = _dispatching_block_ids(state, observed_at)
    active_blocks = {
        block.block_id
        for block in ledger.blocks
        if block.state in {BlockState.COMMITTED, BlockState.RUNNING}
    } | dispatching_blocks
    if not active_blocks:
        return state
    if dispatching_blocks:
        blocks = tuple(
            replace(block, state=BlockState.RUNNING, committed_at=observed_at)
            if block.block_id in dispatching_blocks
            else block
            for block in ledger.blocks
        )
        jobs = tuple(
            replace(job, state=JobState.RUNNING, started_at=observed_at)
            if job.block_id in dispatching_blocks and job.state is JobState.DISPATCHING
            else job
            for job in ledger.jobs
        )
        ledger = replace(
            ledger,
            revision=ledger.revision + 1,
            blocks=blocks,
            jobs=jobs,
            last_reconciled_at=observed_at,
        )
    for block_id in active_blocks:
        block = next(block for block in ledger.blocks if block.block_id == block_id)
        if block.state is BlockState.COMMITTED:
            ledger = ledger.replace_block_state(block_id, BlockState.RUNNING, observed_at)
        for job in tuple(ledger.jobs):
            if job.block_id == block_id and job.state is JobState.ACCEPTED:
                ledger = ledger.replace_job_state(job.job_id, JobState.RUNNING, observed_at)
    return replace(state, ledger=ledger)


def _completed(state: PlannerState, observed_at: datetime) -> PlannerState:
    if not any(job.state is JobState.RUNNING for job in state.ledger.jobs):
        return state
    current = state
    for job in tuple(state.ledger.jobs):
        if job.state is not JobState.RUNNING:
            continue
        result = complete_job_and_advance_plan(
            current.ledger,
            current.plan_revision,
            job.job_id,
            observed_at,
            str(uuid4()),
        )
        current = PlannerState(result.plan_revision, result.ledger)
    return current


def _failed(state: PlannerState, observed_at: datetime) -> PlannerState:
    dispatching_blocks = _dispatching_block_ids(state, observed_at)
    affected = {
        job.block_id
        for job in state.ledger.jobs
        if job.state in {JobState.ACCEPTED, JobState.RUNNING}
    } | dispatching_blocks
    if not affected:
        return state
    jobs = tuple(
        replace(
            job,
            state=JobState.FAILED,
            finished_at=observed_at,
            error_code="vacuum_reported_failure",
        )
        if job.block_id in affected
        and job.state in {JobState.DISPATCHING, JobState.ACCEPTED, JobState.RUNNING}
        else job
        for job in state.ledger.jobs
    )
    blocks = tuple(
        replace(block, state=BlockState.FAILED, completed_at=observed_at)
        if block.block_id in affected
        else block
        for block in state.ledger.blocks
    )
    return replace(
        state,
        ledger=replace(
            state.ledger,
            revision=state.ledger.revision + 1,
            blocks=blocks,
            jobs=jobs,
            last_reconciled_at=observed_at,
        ),
    )


def _uncertain(state: PlannerState, observed_at: datetime) -> PlannerState:
    dispatching_blocks = _dispatching_block_ids(state, observed_at)
    affected = {
        job.block_id
        for job in state.ledger.jobs
        if job.state in {JobState.ACCEPTED, JobState.RUNNING}
    } | dispatching_blocks
    if not affected:
        return state
    jobs = tuple(
        replace(job, state=JobState.UNCERTAIN)
        if job.block_id in affected
        and job.state in {JobState.DISPATCHING, JobState.ACCEPTED, JobState.RUNNING}
        else job
        for job in state.ledger.jobs
    )
    blocks = tuple(
        replace(block, state=BlockState.UNCERTAIN) if block.block_id in affected else block
        for block in state.ledger.blocks
    )
    return replace(
        state,
        ledger=replace(
            state.ledger,
            revision=state.ledger.revision + 1,
            blocks=blocks,
            jobs=jobs,
            last_reconciled_at=observed_at,
        ),
    )


async def async_apply_observation(
    runtime: VacuumPlannerRuntimeData,
    vacuum_state: str,
    attributes: Mapping[str, object],
    observed_at: datetime,
    *,
    observation_generation: int | None = None,
) -> PlannerState:
    """Apply one normalized observation through the coordinator command lock."""
    coordinator = runtime.coordinator
    if coordinator is None:
        raise RuntimeError("Vacuum Planner state is unavailable")
    outcome = normalize_observation(vacuum_state, attributes).outcome
    if outcome is ObservationOutcome.NO_CHANGE:
        return coordinator.state
    command = {
        ObservationOutcome.RUNNING: _running,
        ObservationOutcome.COMPLETED: _completed,
        ObservationOutcome.FAILED: _failed,
        ObservationOutcome.UNCERTAIN: _uncertain,
    }[outcome]

    def apply(state: PlannerState) -> PlannerState:
        if observation_generation is not None and (
            not runtime.observation_active
            or runtime.observation_generation != observation_generation
        ):
            return state
        return command(state, observed_at)

    return await coordinator.async_command(apply)
