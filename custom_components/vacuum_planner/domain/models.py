"""Immutable domain models and their construction invariants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime  # noqa: TC003 - field introspection needs runtime types
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def freeze_json(value: object) -> JsonValue:
    """Validate and deeply freeze a JSON-compatible adapter target."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return MappingProxyType(
            {key: freeze_json(value[key]) for key in sorted(value)}
        )
    raise ValueError("adapter target must be JSON-compatible")


def thaw_json(value: JsonValue) -> JsonScalar | list[object] | dict[str, object]:
    """Convert an immutable JSON value to standard serialization containers."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


class Mode(StrEnum):
    """Supported cleaning modes."""

    VACUUM = "vacuum"
    VACUUM_AND_MOP = "vacuum_and_mop"


class PreferredMode(StrEnum):
    """Room-plan mode selection policy."""

    AUTOMATIC = "automatic"
    VACUUM = "vacuum"
    VACUUM_AND_MOP = "vacuum_and_mop"


class BlockKind(StrEnum):
    """Queue block origin."""

    SCHEDULED = "scheduled"
    ADHOC = "adhoc"


class DispatchStrategy(StrEnum):
    """How a block is dispatched by an adapter."""

    NATIVE_BATCH = "native_batch"
    PLANNER_SEQUENTIAL = "planner_sequential"
    DEVICE_QUEUE = "device_queue"


class BlockGuarantee(StrEnum):
    """Atomicity promised by a block."""

    PLANNER_ATOMIC = "planner_atomic"
    ROBOT_ATOMIC = "robot_atomic"


class BlockState(StrEnum):
    """Lifecycle state of a queue block."""

    DRAFT = "draft"
    VALIDATING = "validating"
    SEALED = "sealed"
    COMMITTING = "committing"
    COMMITTED = "committed"
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    PARTIAL = "partial"


class JobState(StrEnum):
    """Lifecycle state of a queue job."""

    PENDING = "pending"
    DISPATCHING = "dispatching"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        msg = f"{name} must not be empty"
        raise ValueError(msg)


def _require_aware(name: str, value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        msg = f"{name} must be timezone-aware"
        raise ValueError(msg)


def _require_mode(value: object) -> None:
    if not isinstance(value, Mode):
        raise ValueError("unsupported cleaning mode")


def _require_enum(value: object, enum_type: type[StrEnum]) -> None:
    if not isinstance(value, enum_type):
        raise ValueError("unsupported domain enum")


@dataclass(frozen=True, slots=True)
class RoomPlan:
    """Persistent cleaning rules for one HA area."""

    area_id: str
    lane_id: str
    enabled: bool
    vacuum_interval_days: int
    vacuum_and_mop_interval_days: int | None
    preferred_mode: PreferredMode
    priority: int
    skip_until: datetime | None = None
    last_completed_vacuum_at: datetime | None = None
    last_completed_vacuum_and_mop_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("area_id", self.area_id)
        _require_text("lane_id", self.lane_id)
        _require_enum(self.preferred_mode, PreferredMode)
        if self.vacuum_interval_days <= 0:
            raise ValueError("vacuum_interval_days must be positive")
        if (
            self.vacuum_and_mop_interval_days is not None
            and self.vacuum_and_mop_interval_days <= 0
        ):
            raise ValueError("vacuum_and_mop_interval_days must be positive")
        _require_aware("skip_until", self.skip_until)
        _require_aware("last_completed_vacuum_at", self.last_completed_vacuum_at)
        _require_aware(
            "last_completed_vacuum_and_mop_at", self.last_completed_vacuum_and_mop_at
        )
        if (
            self.preferred_mode is PreferredMode.VACUUM_AND_MOP
            and self.vacuum_and_mop_interval_days is None
        ):
            raise ValueError("vacuum_and_mop preferred mode requires its interval")


@dataclass(frozen=True, slots=True)
class PlanRevision:
    """Immutable revision of room planning rules for one lane."""

    revision_id: str
    created_at: datetime
    room_plans: tuple[RoomPlan, ...]

    def __post_init__(self) -> None:
        _require_text("revision_id", self.revision_id)
        _require_aware("created_at", self.created_at)
        object.__setattr__(self, "room_plans", tuple(self.room_plans))
        area_ids = [plan.area_id for plan in self.room_plans]
        if len(area_ids) != len(set(area_ids)):
            raise ValueError("duplicate area_id in plan revision")
        if len({plan.lane_id for plan in self.room_plans}) > 1:
            raise ValueError("all room plans in a revision must use the same lane")


@dataclass(frozen=True, slots=True)
class SnapshotJob:
    """Resolved, ordered job candidate in a plan snapshot."""

    area_id: str
    area_name_snapshot: str
    adapter_target_snapshot: JsonValue
    mode: Mode
    priority: int
    due_at: datetime

    def __post_init__(self) -> None:
        _require_text("area_id", self.area_id)
        _require_text("area_name_snapshot", self.area_name_snapshot)
        _require_mode(self.mode)
        object.__setattr__(
            self, "adapter_target_snapshot", freeze_json(self.adapter_target_snapshot)
        )
        _require_aware("due_at", self.due_at)


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    """Immutable result of evaluating a plan revision."""

    plan_revision: str
    lane_id: str
    evaluated_at: datetime
    jobs: tuple[SnapshotJob, ...]

    def __post_init__(self) -> None:
        _require_text("plan_revision", self.plan_revision)
        _require_text("lane_id", self.lane_id)
        _require_aware("evaluated_at", self.evaluated_at)
        object.__setattr__(self, "jobs", tuple(self.jobs))
        area_ids = [job.area_id for job in self.jobs]
        if len(area_ids) != len(set(area_ids)):
            raise ValueError("duplicate area_id in snapshot")


def _validate_job_lifecycle(job: QueueJob) -> None:
    """Validate persisted state/timestamp combinations for restart safety."""
    if job.attempt < 0:
        raise ValueError("attempt must not be negative")
    for name in ("planned_at", "sent_at", "started_at", "finished_at"):
        _require_aware(name, getattr(job, name))
    if job.state is JobState.PENDING and (
        job.attempt != 0
        or job.adapter_token is not None
        or any(value is not None for value in (job.sent_at, job.started_at, job.finished_at))
    ):
        raise ValueError("pending job cannot contain dispatch data")
    if job.state in {
        JobState.DISPATCHING,
        JobState.ACCEPTED,
        JobState.RUNNING,
        JobState.COMPLETED,
        JobState.UNCERTAIN,
    } and (job.attempt == 0 or job.sent_at is None):
        raise ValueError("dispatched job requires attempt and sent_at")
    if (
        job.state in {JobState.FAILED, JobState.CANCELLED}
        and job.attempt > 0
        and job.sent_at is None
    ):
        raise ValueError("dispatched failure requires sent_at")
    if job.state in {JobState.RUNNING, JobState.COMPLETED} and job.started_at is None:
        raise ValueError("started_at is required for running jobs")
    if job.state not in _JOB_TERMINAL_STATES and job.finished_at is not None:
        raise ValueError("nonterminal job cannot have finished_at")
    if job.state in _JOB_TERMINAL_STATES and job.finished_at is None:
        raise ValueError("finished_at is required for terminal jobs")
    timestamps = tuple(
        value
        for value in (job.planned_at, job.sent_at, job.started_at, job.finished_at)
        if value is not None
    )
    if timestamps != tuple(sorted(timestamps)):
        raise ValueError("job lifecycle timestamps must be chronological")


@dataclass(frozen=True, slots=True)
class QueueJob:
    """Persisted execution state for one resolved area task."""

    job_id: str
    block_id: str
    area_id: str
    area_name_snapshot: str
    adapter_target_snapshot: JsonValue
    mode: Mode
    position: int
    state: JobState
    attempt: int
    planned_at: datetime
    adapter_token: str | None = None
    sent_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_detail: str | None = None

    def __post_init__(self) -> None:
        for name in ("job_id", "block_id", "area_id", "area_name_snapshot"):
            _require_text(name, getattr(self, name))
        _require_mode(self.mode)
        _require_enum(self.state, JobState)
        object.__setattr__(
            self, "adapter_target_snapshot", freeze_json(self.adapter_target_snapshot)
        )
        if self.position < 0:
            raise ValueError("position must not be negative")
        _validate_job_lifecycle(self)


@dataclass(frozen=True, slots=True)
class QueueBlock:
    """Persisted immutable block metadata and ordered job identities."""

    block_id: str
    kind: BlockKind
    lane_id: str
    plan_revision: str
    idempotency_key: str
    created_at: datetime
    sealed_at: datetime | None
    state: BlockState
    job_ids: tuple[str, ...]
    dispatch_strategy: DispatchStrategy
    guarantee: BlockGuarantee
    committed_at: datetime | None = None
    completed_at: datetime | None = None
    adapter_run_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("block_id", "lane_id", "plan_revision", "idempotency_key"):
            _require_text(name, getattr(self, name))
        for value, enum_type in (
            (self.kind, BlockKind),
            (self.state, BlockState),
            (self.dispatch_strategy, DispatchStrategy),
            (self.guarantee, BlockGuarantee),
        ):
            _require_enum(value, enum_type)
        object.__setattr__(self, "job_ids", tuple(self.job_ids))
        if len(self.job_ids) != len(set(self.job_ids)):
            raise ValueError("duplicate job_id in block")
        if (
            self.guarantee is BlockGuarantee.ROBOT_ATOMIC
            and self.dispatch_strategy is not DispatchStrategy.DEVICE_QUEUE
        ):
            raise ValueError("robot_atomic requires device_queue")
        for name in ("created_at", "sealed_at", "committed_at", "completed_at"):
            _require_aware(name, getattr(self, name))
        timestamps = tuple(
            value
            for value in (
                self.created_at,
                self.sealed_at,
                self.committed_at,
                self.completed_at,
            )
            if value is not None
        )
        if timestamps != tuple(sorted(timestamps)):
            raise ValueError("block lifecycle timestamps must be chronological")
        if self.state not in {BlockState.DRAFT, BlockState.VALIDATING} and self.sealed_at is None:
            raise ValueError("sealed_at is required after validation")
        if (
            self.state in {BlockState.COMMITTED, BlockState.RUNNING, BlockState.COMPLETED}
            and self.committed_at is None
        ):
            raise ValueError("committed_at is required for committed blocks")
        if self.state is BlockState.COMPLETED and self.completed_at is None:
            raise ValueError("completed_at is required for completed blocks")


_BLOCK_TRANSITIONS: dict[BlockState, frozenset[BlockState]] = {
    BlockState.DRAFT: frozenset({BlockState.VALIDATING}),
    BlockState.VALIDATING: frozenset({BlockState.SEALED, BlockState.REJECTED}),
    BlockState.SEALED: frozenset({BlockState.COMMITTING, BlockState.CANCELLED}),
    BlockState.COMMITTING: frozenset(
        {BlockState.COMMITTED, BlockState.FAILED, BlockState.UNCERTAIN}
    ),
    BlockState.COMMITTED: frozenset(
        {BlockState.RUNNING, BlockState.CANCELLED, BlockState.UNCERTAIN}
    ),
    BlockState.RUNNING: frozenset(
        {
            BlockState.COMPLETED,
            BlockState.PARTIAL,
            BlockState.FAILED,
            BlockState.CANCELLED,
            BlockState.UNCERTAIN,
        }
    ),
}


_JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset(
        {JobState.DISPATCHING, JobState.SKIPPED, JobState.CANCELLED}
    ),
    JobState.DISPATCHING: frozenset({JobState.ACCEPTED, JobState.FAILED}),
    JobState.ACCEPTED: frozenset(
        {JobState.RUNNING, JobState.UNCERTAIN, JobState.CANCELLED}
    ),
    JobState.RUNNING: frozenset(
        {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.UNCERTAIN}
    ),
    JobState.FAILED: frozenset({JobState.DISPATCHING}),
}
_JOB_TERMINAL_STATES = frozenset(
    {JobState.COMPLETED, JobState.FAILED, JobState.SKIPPED, JobState.CANCELLED}
)
_BLOCK_TERMINAL_STATES = frozenset(
    {
        BlockState.COMPLETED,
        BlockState.REJECTED,
        BlockState.CANCELLED,
        BlockState.FAILED,
        BlockState.PARTIAL,
    }
)


def _validate_job_dispatch(
    parent: QueueBlock,
    current: QueueJob,
    blocks: tuple[QueueBlock, ...],
    jobs: tuple[QueueJob, ...],
) -> None:
    """Prevent dispatch before commit or ahead of the lane's stable order."""
    if parent.state not in {BlockState.COMMITTED, BlockState.RUNNING}:
        raise ValueError("dispatch requires a committed parent block")
    parent_index = blocks.index(parent)
    if any(
        block.lane_id == parent.lane_id and block.state not in _BLOCK_TERMINAL_STATES
        for block in blocks[:parent_index]
    ):
        raise ValueError("earlier lane block is not terminal")
    if parent.dispatch_strategy is DispatchStrategy.PLANNER_SEQUENTIAL and any(
        job.block_id == parent.block_id
        and job.position < current.position
        and job.state not in _JOB_TERMINAL_STATES
        for job in jobs
    ):
        raise ValueError("previous sequential job is not terminal")
    if parent.dispatch_strategy is DispatchStrategy.PLANNER_SEQUENTIAL and any(
        job.block_id == parent.block_id
        and job.position > current.position
        and job.state is not JobState.PENDING
        for job in jobs
    ):
        raise ValueError("later sequential job has already advanced")


def _validate_terminal_block_result(
    block_state: BlockState, block_jobs: list[QueueJob]
) -> None:
    """Require a terminal block outcome to agree with all child outcomes."""
    states = {job.state for job in block_jobs}
    if block_state is BlockState.COMPLETED and states != {JobState.COMPLETED}:
        raise ValueError("completed block requires all jobs completed")
    if block_state is BlockState.PARTIAL and (
        not states
        or not states.issubset(_JOB_TERMINAL_STATES)
        or len(states) < 2  # noqa: PLR2004 - two distinct outcomes define partial
        or JobState.COMPLETED not in states
    ):
        raise ValueError("partial block requires mixed terminal job results")
    if (
        block_state is BlockState.FAILED
        and states.issubset(_JOB_TERMINAL_STATES)
        and JobState.FAILED not in states
    ):
        raise ValueError("failed block requires a failed job")


def _validate_unique_queue_ids(
    blocks: tuple[QueueBlock, ...], jobs: tuple[QueueJob, ...]
) -> tuple[set[str], dict[str, QueueJob]]:
    """Validate queue identities and return indexed identities."""
    block_ids = [block.block_id for block in blocks]
    job_ids = [job.job_id for job in jobs]
    if len(block_ids) != len(set(block_ids)):
        raise ValueError("duplicate block_id in ledger")
    if len(job_ids) != len(set(job_ids)):
        raise ValueError("duplicate job_id in ledger")
    if set(block_ids).intersection(job_ids):
        raise ValueError("block and job identities must be globally unique")
    return set(block_ids), {job.job_id: job for job in jobs}


def _validate_ledger_references(
    blocks: tuple[QueueBlock, ...], jobs: tuple[QueueJob, ...]
) -> None:
    """Validate the complete block/job ownership graph."""
    known_block_ids, jobs_by_id = _validate_unique_queue_ids(blocks, jobs)
    if any(job.block_id not in known_block_ids for job in jobs):
        raise ValueError("job references unknown parent block")
    listed_job_ids: set[str] = set()
    last_created_by_lane: dict[str, datetime] = {}
    for block in blocks:
        previous_created_at = last_created_by_lane.get(block.lane_id)
        if previous_created_at is not None and block.created_at < previous_created_at:
            raise ValueError("lane blocks must remain append ordered")
        last_created_by_lane[block.lane_id] = block.created_at
        if any(job_id not in jobs_by_id for job_id in block.job_ids):
            raise ValueError("block references unknown job_id")
        listed_job_ids.update(block.job_ids)
        block_jobs = [jobs_by_id[job_id] for job_id in block.job_ids]
        if any(job.block_id != block.block_id for job in block_jobs):
            raise ValueError("job references wrong block_id")
        if [job.position for job in block_jobs] != list(range(len(block_jobs))):
            raise ValueError("job positions must be contiguous and ordered")
        if block.state in {
            BlockState.DRAFT,
            BlockState.VALIDATING,
            BlockState.SEALED,
            BlockState.COMMITTING,
        } and any(
            job.state
            in {
                JobState.DISPATCHING,
                JobState.ACCEPTED,
                JobState.RUNNING,
                JobState.UNCERTAIN,
            }
            for job in block_jobs
        ):
            raise ValueError("job state is incompatible with parent block")
        _validate_terminal_block_result(block.state, block_jobs)
        if block.state in _BLOCK_TERMINAL_STATES and any(
            job.state not in _JOB_TERMINAL_STATES for job in block_jobs
        ):
            raise ValueError("terminal block requires terminal jobs")
    if listed_job_ids != set(jobs_by_id):
        raise ValueError("ledger contains an orphan job not listed by its parent block")


@dataclass(frozen=True, slots=True)
class QueueLedger:
    """Immutable, authoritative ordered planner queue."""

    schema_version: int
    revision: int
    blocks: tuple[QueueBlock, ...]
    jobs: tuple[QueueJob, ...]
    active_block_id: str | None = None
    last_reconciled_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported schema_version")
        if self.revision < 0:
            raise ValueError("revision must not be negative")
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "jobs", tuple(self.jobs))
        _require_aware("last_reconciled_at", self.last_reconciled_at)
        _validate_ledger_references(self.blocks, self.jobs)
        if self.active_block_id is not None and self.active_block_id not in {
            block.block_id for block in self.blocks
        }:
            raise ValueError("active_block_id references unknown block")

    @classmethod
    def empty(cls) -> QueueLedger:
        """Create an empty ledger at schema version one."""
        return cls(schema_version=1, revision=0, blocks=(), jobs=())

    def replace_block_state(
        self,
        block_id: str,
        new_state: BlockState,
        changed_at: datetime,
        *,
        adapter_run_id: str | None = None,
    ) -> QueueLedger:
        """Return a ledger with one validated block transition."""
        _require_aware("changed_at", changed_at)
        if adapter_run_id is not None:
            _require_text("adapter_run_id", adapter_run_id)
        matching = [block for block in self.blocks if block.block_id == block_id]
        if not matching:
            raise KeyError(block_id)
        current = matching[0]
        if new_state not in _BLOCK_TRANSITIONS.get(current.state, frozenset()):
            msg = f"invalid block transition: {current.state} -> {new_state}"
            raise ValueError(msg)
        block_jobs = [job for job in self.jobs if job.block_id == block_id]
        _validate_terminal_block_result(new_state, block_jobs)
        if new_state in _BLOCK_TERMINAL_STATES and any(
            job.state not in _JOB_TERMINAL_STATES for job in block_jobs
        ):
            raise ValueError("terminal block requires terminal jobs")
        if new_state is BlockState.COMMITTED:
            changed = replace(
                current,
                state=new_state,
                committed_at=changed_at,
                adapter_run_id=adapter_run_id or current.adapter_run_id,
            )
        elif new_state in {BlockState.COMPLETED, BlockState.PARTIAL}:
            changed = replace(current, state=new_state, completed_at=changed_at)
        else:
            changed = replace(current, state=new_state)
        blocks = tuple(changed if block.block_id == block_id else block for block in self.blocks)
        return replace(self, revision=self.revision + 1, blocks=blocks)

    def replace_job_state(
        self,
        job_id: str,
        new_state: JobState,
        changed_at: datetime,
        *,
        adapter_confirmed: bool = False,
        adapter_token: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> QueueLedger:
        """Return a ledger with one validated job transition."""
        _require_aware("changed_at", changed_at)
        matching = [job for job in self.jobs if job.job_id == job_id]
        if not matching:
            raise KeyError(job_id)
        current = matching[0]
        parent = next(block for block in self.blocks if block.block_id == current.block_id)
        if parent.state in _BLOCK_TERMINAL_STATES:
            raise ValueError("job transition is forbidden under a terminal parent block")
        if parent.state is BlockState.UNCERTAIN:
            raise ValueError("job transition is forbidden under an uncertain parent block")
        if new_state is JobState.DISPATCHING:
            _validate_job_dispatch(parent, current, self.blocks, self.jobs)
        if new_state not in _JOB_TRANSITIONS.get(current.state, frozenset()):
            msg = f"invalid job transition: {current.state} -> {new_state}"
            raise ValueError(msg)
        if (
            new_state is JobState.CANCELLED
            and current.state in {JobState.ACCEPTED, JobState.RUNNING}
            and not adapter_confirmed
        ):
            raise ValueError("adapter confirmation is required for cancellation")

        if new_state is JobState.DISPATCHING:
            changed = replace(
                current,
                state=new_state,
                attempt=current.attempt + 1,
                adapter_token=None,
                sent_at=changed_at,
                started_at=None,
                finished_at=None,
                error_code=error_code,
                error_detail=error_detail,
            )
        elif new_state is JobState.RUNNING:
            changed = replace(
                current,
                state=new_state,
                adapter_token=adapter_token or current.adapter_token,
                started_at=changed_at,
                error_code=error_code,
                error_detail=error_detail,
            )
        elif new_state in _JOB_TERMINAL_STATES:
            changed = replace(
                current,
                state=new_state,
                adapter_token=adapter_token or current.adapter_token,
                finished_at=changed_at,
                error_code=error_code,
                error_detail=error_detail,
            )
        else:
            changed = replace(
                current,
                state=new_state,
                adapter_token=adapter_token or current.adapter_token,
                error_code=error_code,
                error_detail=error_detail,
            )
        jobs = tuple(changed if job.job_id == job_id else job for job in self.jobs)
        return replace(self, revision=self.revision + 1, jobs=jobs)
