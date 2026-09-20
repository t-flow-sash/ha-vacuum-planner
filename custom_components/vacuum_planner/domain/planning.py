"""Deterministic due-date evaluation and snapshot materialization.

Phase-1 time semantics are explicit: intervals are exact 24-hour periods, a missing
completion is due immediately, and ``skip_until`` suppresses work while it is strictly
later than the evaluation instant. Priority sorts descending, then oldest due time,
then stable ``area_id``.
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003 - public API exposes this type
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import (
    JsonValue,
    Mode,
    PlanRevision,
    PlanSnapshot,
    PreferredMode,
    RoomPlan,
    SnapshotJob,
    freeze_json,
)


@dataclass(frozen=True, slots=True)
class AreaBinding:
    """Resolved, vendor-neutral area data injected by an outer adapter layer."""

    area_id: str
    area_name: str
    adapter_target: JsonValue
    supports_vacuum_and_mop: bool

    def __post_init__(self) -> None:
        if not self.area_id.strip():
            raise ValueError("area_id must not be empty")
        if not self.area_name.strip():
            raise ValueError("area_name must not be empty")
        object.__setattr__(self, "adapter_target", freeze_json(self.adapter_target))


class PlanningValidationError(ValueError):
    """All validation failures that prevented complete snapshot creation."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _due_at(last_completed: datetime | None, interval_days: int, now: datetime) -> datetime:
    return now if last_completed is None else last_completed + timedelta(days=interval_days)


def _max_optional(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _select_due(plan: RoomPlan, now: datetime) -> tuple[Mode, datetime] | None:
    effective_vacuum = _max_optional(
        plan.last_completed_vacuum_at, plan.last_completed_vacuum_and_mop_at
    )
    vacuum_due = _due_at(effective_vacuum, plan.vacuum_interval_days, now)
    mop_due = (
        _due_at(plan.last_completed_vacuum_and_mop_at, plan.vacuum_and_mop_interval_days, now)
        if plan.vacuum_and_mop_interval_days is not None
        else None
    )

    if plan.preferred_mode is PreferredMode.VACUUM:
        return (Mode.VACUUM, vacuum_due) if vacuum_due <= now else None
    if plan.preferred_mode is PreferredMode.VACUUM_AND_MOP:
        return (Mode.VACUUM_AND_MOP, mop_due) if mop_due is not None and mop_due <= now else None
    raise ValueError("unsupported preferred mode")


def build_due_snapshot(
    revision: PlanRevision,
    area_bindings: Mapping[str, AreaBinding],
    evaluated_at: datetime,
) -> PlanSnapshot:
    """Evaluate and completely validate all due work for one revision."""
    if not revision.room_plans:
        raise PlanningValidationError(("plan revision has no lane-bound room plans",))
    candidates: list[tuple[RoomPlan, Mode, datetime]] = []
    errors: list[str] = []
    for plan in revision.room_plans:
        if not plan.enabled or (plan.skip_until is not None and plan.skip_until > evaluated_at):
            continue
        selected = _select_due(plan, evaluated_at)
        if selected is None:
            continue
        mode, due_at = selected
        candidates.append((plan, mode, due_at))
        binding = area_bindings.get(plan.area_id)
        if binding is None:
            errors.append(f"{plan.area_id}: missing area binding")
        elif binding.area_id != plan.area_id:
            errors.append(f"{plan.area_id}: mismatched area binding")
        elif mode is Mode.VACUUM_AND_MOP and not binding.supports_vacuum_and_mop:
            errors.append(f"{plan.area_id}: vacuum_and_mop is not supported")

    if errors:
        raise PlanningValidationError(tuple(errors))

    candidates.sort(key=lambda item: (-item[0].priority, item[2], item[0].area_id))
    jobs = tuple(
        SnapshotJob(
            area_id=plan.area_id,
            area_name_snapshot=area_bindings[plan.area_id].area_name,
            adapter_target_snapshot=area_bindings[plan.area_id].adapter_target,
            mode=mode,
            priority=plan.priority,
            due_at=due_at,
        )
        for plan, mode, due_at in candidates
    )
    return PlanSnapshot(revision.revision_id, revision.room_plans[0].lane_id, evaluated_at, jobs)
