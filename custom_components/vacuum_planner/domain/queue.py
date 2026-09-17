"""Pure queue commands for atomic sealing, idempotent start, and append-only ad-hoc work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime  # noqa: TC003 - command API exposes this runtime type
from enum import StrEnum

from .models import (
    BlockGuarantee,
    BlockKind,
    BlockState,
    DispatchStrategy,
    JobState,
    Mode,
    PlanSnapshot,
    QueueBlock,
    QueueJob,
    QueueLedger,
)
from .planning import AreaBinding  # noqa: TC001 - public command API exposes this domain type

IdFactory = Callable[[], str]

_TERMINAL_BLOCK_STATES = frozenset(
    {
        BlockState.COMPLETED,
        BlockState.REJECTED,
        BlockState.CANCELLED,
        BlockState.FAILED,
        BlockState.PARTIAL,
    }
)
_TERMINAL_JOB_STATES = frozenset(
    {JobState.COMPLETED, JobState.FAILED, JobState.SKIPPED, JobState.CANCELLED}
)
_ACTIVE_JOB_STATES = frozenset(
    {JobState.DISPATCHING, JobState.ACCEPTED, JobState.RUNNING}
)


def _has_external_correlation(value: str | None) -> bool:
    """Return whether a persisted adapter correlation is usable."""
    return value is not None and bool(value.strip())


def _is_uncorrelated_active(job: QueueJob) -> bool:
    """Return whether a job may have an untracked external side effect."""
    return job.state in _ACTIVE_JOB_STATES and not _has_external_correlation(
        job.adapter_token
    )


class StartStatus(StrEnum):
    """Outcome of a planner start command."""

    CREATED = "created"
    EXISTING = "existing"
    NO_WORK = "no_work"


class EnqueueStatus(StrEnum):
    """Outcome of an ad-hoc enqueue command."""

    CREATED = "created"
    DUPLICATE = "duplicate"


class UncertainResolution(StrEnum):
    """Explicit, operator-confirmed safe outcomes for an uncertain dispatch."""

    RETRY_SAFE = "retry_safe"


class DuplicateIdentityError(ValueError):
    """Generated block/job identities are not globally unique."""


class QueueBusyError(ValueError):
    """The lane append gate is closed during a critical block phase."""


class LaneAlreadyOpenError(ValueError):
    """A lane cannot accept a second open block."""


@dataclass(frozen=True, slots=True)
class StartResult:
    """Immutable result of ``start_due_block``."""

    status: StartStatus
    ledger: QueueLedger
    block: QueueBlock | None
    jobs: tuple[QueueJob, ...]


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """Immutable result of ``enqueue_area``."""

    status: EnqueueStatus
    ledger: QueueLedger
    block: QueueBlock
    job: QueueJob


def _jobs_for_block(ledger: QueueLedger, block: QueueBlock) -> tuple[QueueJob, ...]:
    by_id = {job.job_id: job for job in ledger.jobs}
    return tuple(by_id[job_id] for job_id in block.job_ids)


def start_due_block(
    ledger: QueueLedger,
    snapshot: PlanSnapshot,
    lane_id: str,
    idempotency_key: str,
    now: datetime,
    id_factory: IdFactory,
    dispatch_strategy: DispatchStrategy,
    guarantee: BlockGuarantee,
    *,
    atomic_device_commit: bool = False,
) -> StartResult:
    """Seal all snapshot jobs or none, deduplicating an open start command."""
    if snapshot.lane_id != lane_id:
        raise ValueError("snapshot lane does not match requested lane")
    if (
        guarantee is BlockGuarantee.ROBOT_ATOMIC
        and dispatch_strategy is not DispatchStrategy.DEVICE_QUEUE
    ):
        raise ValueError("robot_atomic requires device_queue")
    if guarantee is BlockGuarantee.ROBOT_ATOMIC and not atomic_device_commit:
        raise ValueError("robot_atomic requires atomic device commit proof")
    for block in ledger.blocks:
        if (
            block.lane_id == lane_id
            and block.idempotency_key == idempotency_key
            and block.state not in _TERMINAL_BLOCK_STATES
        ):
            return StartResult(
                StartStatus.EXISTING, ledger, block, _jobs_for_block(ledger, block)
            )
        if block.lane_id == lane_id and block.state not in _TERMINAL_BLOCK_STATES:
            raise LaneAlreadyOpenError("lane already has an open block")
    if not snapshot.jobs:
        return StartResult(StartStatus.NO_WORK, ledger, None, ())

    block_id = id_factory()
    job_ids = tuple(id_factory() for _ in snapshot.jobs)
    allocated = (block_id, *job_ids)
    existing_ids = {block.block_id for block in ledger.blocks} | {
        job.job_id for job in ledger.jobs
    }
    if len(allocated) != len(set(allocated)) or existing_ids.intersection(allocated):
        raise DuplicateIdentityError("generated queue identities must be globally unique")

    jobs = tuple(
        QueueJob(
            job_id=job_id,
            block_id=block_id,
            area_id=snapshot_job.area_id,
            area_name_snapshot=snapshot_job.area_name_snapshot,
            adapter_target_snapshot=snapshot_job.adapter_target_snapshot,
            mode=snapshot_job.mode,
            position=position,
            state=JobState.PENDING,
            attempt=0,
            planned_at=now,
        )
        for position, (job_id, snapshot_job) in enumerate(zip(job_ids, snapshot.jobs, strict=True))
    )
    block = QueueBlock(
        block_id=block_id,
        kind=BlockKind.SCHEDULED,
        lane_id=lane_id,
        plan_revision=snapshot.plan_revision,
        idempotency_key=idempotency_key,
        created_at=now,
        sealed_at=now,
        state=BlockState.SEALED,
        job_ids=job_ids,
        dispatch_strategy=dispatch_strategy,
        guarantee=guarantee,
    )
    updated = replace(
        ledger,
        revision=ledger.revision + 1,
        blocks=(*ledger.blocks, block),
        jobs=(*ledger.jobs, *jobs),
    )
    return StartResult(StartStatus.CREATED, updated, block, jobs)


def fail_block_commit(
    ledger: QueueLedger,
    block_id: str,
    failed_at: datetime,
    *,
    error_code: str,
    error_detail: str | None = None,
) -> QueueLedger:
    """Atomically record an adapter commit failure before any job was sent."""
    block = next((item for item in ledger.blocks if item.block_id == block_id), None)
    if block is None:
        raise KeyError(block_id)
    if block.state is not BlockState.COMMITTING:
        raise ValueError("block is not committing")
    block_jobs = tuple(job for job in ledger.jobs if job.block_id == block_id)
    if any(job.state is not JobState.PENDING for job in block_jobs):
        raise ValueError("commit failure requires unsent jobs")
    failed_jobs = {
        job.job_id: replace(
            job,
            state=JobState.FAILED,
            finished_at=failed_at,
            error_code=error_code,
            error_detail=error_detail,
        )
        for job in block_jobs
    }
    return replace(
        ledger,
        revision=ledger.revision + 1,
        blocks=tuple(
            replace(item, state=BlockState.FAILED) if item.block_id == block_id else item
            for item in ledger.blocks
        ),
        jobs=tuple(failed_jobs.get(job.job_id, job) for job in ledger.jobs),
    )


def enqueue_area(
    ledger: QueueLedger,
    lane_id: str,
    binding: AreaBinding,
    mode: Mode,
    now: datetime,
    id_factory: IdFactory,
    *,
    confirmed_repeat: bool = False,
) -> EnqueueResult:
    """Append one validated ad-hoc block to a lane without mutating sealed blocks."""
    lane_blocks = [block for block in ledger.blocks if block.lane_id == lane_id]
    if any(
        block.state in {BlockState.VALIDATING, BlockState.SEALED, BlockState.COMMITTING}
        for block in lane_blocks
    ):
        raise QueueBusyError("busy_committing")
    anchor = next(
        (
            block
            for block in reversed(lane_blocks)
            if block.kind is BlockKind.SCHEDULED
            and block.state in {BlockState.COMMITTED, BlockState.RUNNING}
        ),
        None,
    )
    if anchor is None:
        raise QueueBusyError("no committed scheduled block")
    if mode is Mode.VACUUM_AND_MOP and not binding.supports_vacuum_and_mop:
        raise ValueError("vacuum_and_mop is not supported")

    blocks_by_id = {block.block_id: block for block in ledger.blocks}
    if not confirmed_repeat:
        for job in ledger.jobs:
            parent = blocks_by_id[job.block_id]
            if (
                parent.lane_id == lane_id
                and job.area_id == binding.area_id
                and job.mode is mode
                and job.state not in _TERMINAL_JOB_STATES
            ):
                return EnqueueResult(EnqueueStatus.DUPLICATE, ledger, parent, job)

    block_id = id_factory()
    job_id = id_factory()
    existing_ids = set(blocks_by_id) | {job.job_id for job in ledger.jobs}
    if block_id == job_id or block_id in existing_ids or job_id in existing_ids:
        raise DuplicateIdentityError("generated queue identities must be globally unique")
    job = QueueJob(
        job_id=job_id,
        block_id=block_id,
        area_id=binding.area_id,
        area_name_snapshot=binding.area_name,
        adapter_target_snapshot=binding.adapter_target,
        mode=mode,
        position=0,
        state=JobState.PENDING,
        attempt=0,
        planned_at=now,
    )
    block = QueueBlock(
        block_id=block_id,
        kind=BlockKind.ADHOC,
        lane_id=lane_id,
        plan_revision=anchor.plan_revision,
        idempotency_key=f"adhoc:{job_id}",
        created_at=now,
        sealed_at=now,
        state=BlockState.SEALED,
        job_ids=(job_id,),
        dispatch_strategy=DispatchStrategy.PLANNER_SEQUENTIAL,
        guarantee=BlockGuarantee.PLANNER_ATOMIC,
    )
    updated = replace(
        ledger,
        revision=ledger.revision + 1,
        blocks=(*ledger.blocks, block),
        jobs=(*ledger.jobs, job),
    )
    return EnqueueResult(EnqueueStatus.CREATED, updated, block, job)


def resolve_uncertain_job(
    ledger: QueueLedger,
    job_id: str,
    resolution: UncertainResolution,
    resolved_at: datetime,
) -> QueueLedger:
    """Resolve uncertainty only after an explicit safe-to-retry decision."""
    if resolution is not UncertainResolution.RETRY_SAFE:
        raise ValueError("unsupported uncertain resolution")
    job = next((item for item in ledger.jobs if item.job_id == job_id), None)
    if job is None:
        raise KeyError(job_id)
    if job.state is not JobState.UNCERTAIN:
        raise ValueError("job is not uncertain")
    block = next(item for item in ledger.blocks if item.block_id == job.block_id)
    if block.state is not BlockState.UNCERTAIN:
        raise ValueError("uncertain job requires an uncertain parent block")

    resolved_job = replace(
        job,
        state=JobState.FAILED,
        finished_at=resolved_at,
        error_code="recovery_retry_safe",
        error_detail=None,
    )
    jobs = tuple(resolved_job if item.job_id == job_id else item for item in ledger.jobs)
    has_remaining_uncertainty = any(
        item.block_id == block.block_id
        and (item.state is JobState.UNCERTAIN or _is_uncorrelated_active(item))
        for item in jobs
    )
    resumed_state = (
        BlockState.UNCERTAIN
        if has_remaining_uncertainty
        else BlockState.RUNNING if block.committed_at is not None else BlockState.COMMITTING
    )
    resumed_block = replace(block, state=resumed_state)
    return replace(
        ledger,
        revision=ledger.revision + 1,
        blocks=tuple(
            resumed_block if item.block_id == block.block_id else item
            for item in ledger.blocks
        ),
        jobs=jobs,
    )


def resolve_uncertain_block(
    ledger: QueueLedger,
    block_id: str,
    resolution: UncertainResolution,
) -> QueueLedger:
    """Release a quarantined block with no ambiguous child after an explicit decision."""
    if resolution is not UncertainResolution.RETRY_SAFE:
        raise ValueError("unsupported uncertain resolution")
    block = next((item for item in ledger.blocks if item.block_id == block_id), None)
    if block is None:
        raise KeyError(block_id)
    if block.state is not BlockState.UNCERTAIN:
        raise ValueError("block is not uncertain")
    if any(
        job.block_id == block_id and job.state is JobState.UNCERTAIN
        for job in ledger.jobs
    ):
        raise ValueError("uncertain child jobs must be resolved first")
    if any(
        job.block_id == block_id
        and _is_uncorrelated_active(job)
        for job in ledger.jobs
    ):
        raise ValueError("uncorrelated active child prevents block release")
    resumed_state = (
        BlockState.RUNNING if block.committed_at is not None else BlockState.COMMITTING
    )
    resumed_block = replace(block, state=resumed_state)
    return replace(
        ledger,
        revision=ledger.revision + 1,
        blocks=tuple(
            resumed_block if item.block_id == block_id else item
            for item in ledger.blocks
        ),
    )


def quarantine_ambiguous_dispatches(
    ledger: QueueLedger, reconciled_at: datetime
) -> QueueLedger:
    """Quarantine every active external state that lacks restart correlation."""
    active_block_states = {
        BlockState.COMMITTING,
        BlockState.COMMITTED,
        BlockState.RUNNING,
    }
    ambiguous_block_ids = {
        block.block_id
        for block in ledger.blocks
        if block.state in active_block_states
        and not _has_external_correlation(block.adapter_run_id)
    }
    ambiguous_block_ids.update(
        job.block_id
        for job in ledger.jobs
        if _is_uncorrelated_active(job)
    )
    blocks = tuple(
        replace(block, state=BlockState.UNCERTAIN)
        if block.block_id in ambiguous_block_ids and block.state in active_block_states
        else block
        for block in ledger.blocks
    )
    jobs = tuple(
        replace(job, state=JobState.UNCERTAIN)
        if _is_uncorrelated_active(job)
        else job
        for job in ledger.jobs
    )
    return replace(
        ledger,
        revision=ledger.revision + 1,
        blocks=blocks,
        jobs=jobs,
        last_reconciled_at=reconciled_at,
    )
