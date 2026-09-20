"""In-memory entity projections for Vacuum Planner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict

from .domain.models import BlockState, JobState
from .domain.planning import AreaBinding, PlanningValidationError, build_due_snapshot

if TYPE_CHECKING:
    from .const import VacuumPlannerRuntimeData

MAX_QUEUE_PROJECTION_ITEMS = 20
MAX_QUEUE_AREA_NAME_LENGTH = 80


class QueueProjectionItem(TypedDict):
    """Small public queue row safe for Home Assistant state attributes."""

    area_name: str
    mode: str
    position: int
    status: str


class QueueProjection(TypedDict):
    """Bounded public projection of the authoritative queue."""

    items: list[QueueProjectionItem]
    projected_count: int
    revision: int
    total_count: int
    truncated: bool


def _safe_area_name(value: str) -> str:
    """Bound an operator-facing name and remove unsafe control characters."""
    printable = "".join(character for character in value if character.isprintable()).strip()
    return printable[:MAX_QUEUE_AREA_NAME_LENGTH] or "—"


def queue_projection(runtime_data: VacuumPlannerRuntimeData) -> QueueProjection:
    """Return an ordered, bounded queue without IDs, targets, tokens, or error details."""
    state = runtime_data.state
    if state is None:
        return {
            "items": [],
            "projected_count": 0,
            "revision": 0,
            "total_count": 0,
            "truncated": False,
        }
    jobs = state.ledger.jobs
    terminal_states = {
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.SKIPPED,
        JobState.CANCELLED,
    }
    active_jobs = [job for job in jobs if job.state not in terminal_states]
    recent_history = [job for job in reversed(jobs) if job.state in terminal_states]
    projected_jobs = (active_jobs + recent_history)[:MAX_QUEUE_PROJECTION_ITEMS]
    items: list[QueueProjectionItem] = [
        {
            "area_name": _safe_area_name(job.area_name_snapshot),
            "mode": job.mode.value,
            "position": job.position,
            "status": job.state.value,
        }
        for job in projected_jobs
    ]
    return {
        "items": items,
        "projected_count": len(items),
        "revision": state.ledger.revision,
        "total_count": len(jobs),
        "truncated": len(jobs) > len(items),
    }


def planner_status(runtime_data: VacuumPlannerRuntimeData) -> str:
    """Return the public planner status without performing I/O."""
    status = "idle"
    state = runtime_data.state
    if not runtime_data.topology_ready:
        status = "attention"
    elif not runtime_data.planning_enabled:
        status = "paused"
    elif state is not None and any(
        block.state in {BlockState.REJECTED, BlockState.UNCERTAIN} for block in state.ledger.blocks
    ):
        status = "attention"
    elif state is not None and any(
        block.state is BlockState.COMMITTING for block in state.ledger.blocks
    ):
        status = "committing"
    elif state is not None and any(
        block.state in {BlockState.COMMITTED, BlockState.RUNNING} for block in state.ledger.blocks
    ):
        status = "running"
    elif state is not None and any(
        block.state is BlockState.SEALED for block in state.ledger.blocks
    ):
        status = "ready"
    return status


def pending_count(runtime_data: VacuumPlannerRuntimeData) -> int:
    """Return the count of nonterminal queue jobs from memory."""
    state = runtime_data.state
    if state is None:
        return 0
    terminal = {JobState.COMPLETED, JobState.FAILED, JobState.SKIPPED, JobState.CANCELLED}
    return sum(job.state not in terminal for job in state.ledger.jobs)


def current_phase(runtime_data: VacuumPlannerRuntimeData) -> str:
    """Return the latest nonterminal block phase, or idle."""
    state = runtime_data.state
    if state is None:
        return "idle"
    terminal = {
        BlockState.COMPLETED,
        BlockState.REJECTED,
        BlockState.CANCELLED,
        BlockState.FAILED,
        BlockState.PARTIAL,
    }
    block = next(
        (item for item in reversed(state.ledger.blocks) if item.state not in terminal),
        None,
    )
    return "idle" if block is None else block.state.value


def capability_tier(runtime_data: VacuumPlannerRuntimeData) -> str:
    """Return the setup-time capability summary without probing hardware."""
    return runtime_data.capability_tier


def attention_required(runtime_data: VacuumPlannerRuntimeData) -> bool:
    """Return whether persisted state or setup readiness needs operator attention."""
    state = runtime_data.state
    return not runtime_data.topology_ready or (
        state is not None
        and any(
            block.state in {BlockState.REJECTED, BlockState.UNCERTAIN}
            for block in state.ledger.blocks
        )
    )


def planner_ready(runtime_data: VacuumPlannerRuntimeData) -> bool:
    """Return whether public planner commands are safe to attempt."""
    return (
        runtime_data.planning_enabled
        and runtime_data.state is not None
        and not attention_required(runtime_data)
    )


def next_action(
    runtime_data: VacuumPlannerRuntimeData,
    evaluated_at: datetime | None = None,
) -> dict[str, str] | None:
    """Project the next due plan item using only coordinator-owned memory."""
    if not runtime_data.topology_ready:
        return {
            "status": "blocked",
            "remediation": "Repair topology issue and reload config entry",
        }
    state = runtime_data.state
    if state is None or not runtime_data.planning_enabled:
        return None
    now = evaluated_at or datetime.now(UTC)
    names = runtime_data.area_names or {}
    bindings = {
        plan.area_id: AreaBinding(
            plan.area_id,
            names.get(plan.area_id, plan.area_id),
            (),
            plan.vacuum_and_mop_interval_days is not None,
        )
        for plan in state.plan_revision.room_plans
    }
    try:
        snapshot = build_due_snapshot(state.plan_revision, bindings, now)
    except PlanningValidationError:
        return None
    if not snapshot.jobs:
        return None
    job = snapshot.jobs[0]
    return {
        "area_id": job.area_id,
        "area_name": job.area_name_snapshot,
        "mode": job.mode.value,
        "due_at": job.due_at.isoformat(),
    }
