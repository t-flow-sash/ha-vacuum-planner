from datetime import UTC, datetime, timedelta

import pytest

from custom_components.vacuum_planner.domain.models import (
    Mode,
    PlanRevision,
    PreferredMode,
    RoomPlan,
)
from custom_components.vacuum_planner.domain.planning import (
    AreaBinding,
    PlanningValidationError,
    build_due_snapshot,
)

NOW = datetime(2026, 9, 17, 8, tzinfo=UTC)


def plan(area_id: str, **overrides: object) -> RoomPlan:
    values: dict[str, object] = {
        "area_id": area_id,
        "lane_id": "lane",
        "enabled": True,
        "vacuum_interval_days": 2,
        "vacuum_and_mop_interval_days": 7,
        "preferred_mode": PreferredMode.AUTOMATIC,
        "priority": 0,
        "last_completed_vacuum_at": NOW - timedelta(days=1),
        "last_completed_vacuum_and_mop_at": NOW - timedelta(days=1),
    }
    values.update(overrides)
    return RoomPlan(**values)  # type: ignore[arg-type]


def bindings(*areas: str, mop: bool = True) -> dict[str, AreaBinding]:
    return {
        area: AreaBinding(area, area.title(), {"segment": area}, supports_vacuum_and_mop=mop)
        for area in areas
    }


def test_automatic_selects_mop_when_mop_is_due() -> None:
    revision = PlanRevision(
        "rev", NOW,
        (plan("kitchen", last_completed_vacuum_and_mop_at=NOW - timedelta(days=7)),),
    )

    snapshot = build_due_snapshot(revision, bindings("kitchen"), NOW)

    assert len(snapshot.jobs) == 1
    assert snapshot.jobs[0].mode is Mode.VACUUM_AND_MOP
    assert snapshot.jobs[0].due_at == NOW


def test_successful_mop_timestamp_also_satisfies_vacuum_due_date() -> None:
    revision = PlanRevision(
        "rev", NOW,
        (
            plan(
                "kitchen",
                vacuum_interval_days=2,
                vacuum_and_mop_interval_days=30,
                last_completed_vacuum_at=NOW - timedelta(days=10),
                last_completed_vacuum_and_mop_at=NOW - timedelta(days=1),
            ),
        ),
    )

    snapshot = build_due_snapshot(revision, bindings("kitchen"), NOW)

    assert snapshot.jobs == ()


def test_missing_completion_is_immediately_due_at_evaluation_time() -> None:
    revision = PlanRevision(
        "rev", NOW,
        (
            plan(
                "new-room",
                preferred_mode=PreferredMode.VACUUM,
                last_completed_vacuum_at=None,
                last_completed_vacuum_and_mop_at=None,
            ),
        ),
    )

    snapshot = build_due_snapshot(revision, bindings("new-room"), NOW)

    assert snapshot.jobs[0].due_at == NOW
    assert snapshot.jobs[0].mode is Mode.VACUUM


def test_disabled_and_currently_skipped_rooms_are_excluded() -> None:
    revision = PlanRevision(
        "rev", NOW,
        (
            plan("disabled", enabled=False, last_completed_vacuum_at=None),
            plan("skipped", skip_until=NOW + timedelta(seconds=1), last_completed_vacuum_at=None),
        ),
    )

    assert build_due_snapshot(revision, bindings("disabled", "skipped"), NOW).jobs == ()


def test_priority_is_descending_then_due_time_then_area_id_for_stable_order() -> None:
    revision = PlanRevision(
        "rev", NOW,
        (
            plan(
                "zeta", priority=5, last_completed_vacuum_at=None,
                last_completed_vacuum_and_mop_at=None,
            ),
            plan(
                "alpha", priority=5, last_completed_vacuum_at=None,
                last_completed_vacuum_and_mop_at=None,
            ),
            plan(
                "older", priority=5,
                last_completed_vacuum_at=NOW - timedelta(days=4),
                last_completed_vacuum_and_mop_at=NOW - timedelta(days=4),
            ),
            plan(
                "urgent", priority=10, last_completed_vacuum_at=None,
                last_completed_vacuum_and_mop_at=None,
            ),
        ),
    )

    snapshot = build_due_snapshot(revision, bindings("zeta", "alpha", "older", "urgent"), NOW)

    assert [job.area_id for job in snapshot.jobs] == ["urgent", "older", "alpha", "zeta"]


def test_all_due_jobs_are_rejected_together_when_any_binding_is_invalid() -> None:
    revision = PlanRevision(
        "rev", NOW,
        (
            plan(
                "valid", last_completed_vacuum_at=None,
                last_completed_vacuum_and_mop_at=None,
            ),
            plan(
                "missing", last_completed_vacuum_at=None,
                last_completed_vacuum_and_mop_at=None,
            ),
        ),
    )

    with pytest.raises(PlanningValidationError) as error:
        build_due_snapshot(revision, bindings("valid"), NOW)

    assert error.value.errors == ("missing: missing area binding",)


def test_mop_never_silently_degrades_when_binding_lacks_capability() -> None:
    revision = PlanRevision(
        "rev", NOW,
        (
            plan(
                "kitchen",
                preferred_mode=PreferredMode.VACUUM_AND_MOP,
                last_completed_vacuum_and_mop_at=None,
            ),
        ),
    )

    with pytest.raises(PlanningValidationError, match="vacuum_and_mop"):
        build_due_snapshot(revision, bindings("kitchen", mop=False), NOW)
