import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.vacuum_planner.domain import queue as queue_commands
from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockState,
    DispatchStrategy,
    JobState,
    Mode,
    PlannerState,
    PlanRevision,
    PreferredMode,
    QueueLedger,
    RoomPlan,
)
from custom_components.vacuum_planner.domain.planning import AreaBinding, build_due_snapshot
from custom_components.vacuum_planner.domain.queue import start_due_block
from custom_components.vacuum_planner.domain.serialization import (
    deserialize_planner_state,
    serialize_planner_state,
)

NOW = datetime(2026, 9, 17, 8, tzinfo=UTC)


class IDs:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"id-{self.index}"


def running_job(
    mode: Mode, *, parent_running: bool = True
) -> tuple[QueueLedger, PlanRevision]:
    preferred_mode = (
        PreferredMode.VACUUM if mode is Mode.VACUUM else PreferredMode.VACUUM_AND_MOP
    )
    revision = PlanRevision(
        "rev-1",
        NOW - timedelta(days=1),
        (
            RoomPlan(
                area_id="kitchen",
                lane_id="lane",
                enabled=True,
                vacuum_interval_days=2,
                vacuum_and_mop_interval_days=7,
                preferred_mode=preferred_mode,
                priority=0,
                last_completed_vacuum_at=NOW - timedelta(days=3),
                last_completed_vacuum_and_mop_at=NOW - timedelta(days=8),
            ),
        ),
    )
    snapshot = build_due_snapshot(
        revision,
        {"kitchen": AreaBinding("kitchen", "Kitchen", 4, True)},
        NOW,
    )
    ledger = start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    for block_state in (BlockState.COMMITTING, BlockState.COMMITTED):
        ledger = ledger.replace_block_state("id-1", block_state, NOW)
    if parent_running:
        ledger = ledger.replace_block_state("id-1", BlockState.RUNNING, NOW)
    for job_state in (JobState.DISPATCHING, JobState.ACCEPTED, JobState.RUNNING):
        ledger = ledger.replace_job_state("id-2", job_state, NOW)
    return ledger, revision


def test_completed_vacuum_advances_plan_and_clears_immediate_due_work() -> None:
    ledger, revision = running_job(Mode.VACUUM)
    previous_mop_completion = revision.room_plans[0].last_completed_vacuum_and_mop_at

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        revision,
        "id-2",
        NOW,
        "rev-2",
    )

    assert result.ledger.jobs[0].state is JobState.COMPLETED
    assert result.ledger.jobs[0].finished_at == NOW
    assert result.plan_revision.revision_id == "rev-2"
    assert result.plan_revision.created_at == NOW
    assert result.plan_revision.room_plans[0].last_completed_vacuum_at == NOW
    assert (
        result.plan_revision.room_plans[0].last_completed_vacuum_and_mop_at
        == previous_mop_completion
    )
    assert (
        build_due_snapshot(
            result.plan_revision,
            {"kitchen": AreaBinding("kitchen", "Kitchen", 4, True)},
            NOW,
        ).jobs
        == ()
    )


def test_completed_job_and_advanced_plan_survive_one_restart_roundtrip() -> None:
    ledger, revision = running_job(Mode.VACUUM_AND_MOP)
    completed = queue_commands.complete_job_and_advance_plan(
        ledger,
        revision,
        "id-2",
        NOW,
        "rev-2",
    )

    restored = deserialize_planner_state(
        json.loads(
            json.dumps(
                serialize_planner_state(
                    PlannerState(completed.plan_revision, completed.ledger)
                )
            )
        )
    )

    assert restored.ledger.jobs[0].state is JobState.COMPLETED
    assert restored.ledger.blocks[0].state is BlockState.COMPLETED
    assert restored.plan_revision.room_plans[0].last_completed_vacuum_at == NOW
    assert restored.plan_revision.room_plans[0].last_completed_vacuum_and_mop_at == NOW
    assert (
        build_due_snapshot(
            restored.plan_revision,
            {"kitchen": AreaBinding("kitchen", "Kitchen", 4, True)},
            NOW,
        ).jobs
        == ()
    )


def test_completing_final_job_atomically_completes_parent_block() -> None:
    ledger, revision = running_job(Mode.VACUUM)

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        revision,
        "id-2",
        NOW,
        "rev-2",
    )

    assert result.ledger.blocks[0].state is BlockState.COMPLETED
    assert result.ledger.blocks[0].completed_at == NOW


def test_completing_job_finalizes_parent_that_has_not_observed_running() -> None:
    ledger, revision = running_job(Mode.VACUUM, parent_running=False)

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        revision,
        "id-2",
        NOW,
        "rev-2",
    )

    assert result.ledger.blocks[0].state is BlockState.COMPLETED


def test_completing_last_active_job_marks_mixed_outcomes_partial() -> None:
    rooms = tuple(
        RoomPlan(
            area_id=area_id,
            lane_id="lane",
            enabled=True,
            vacuum_interval_days=2,
            vacuum_and_mop_interval_days=None,
            preferred_mode=PreferredMode.VACUUM,
            priority=0,
        )
        for area_id in ("kitchen", "hall")
    )
    revision = PlanRevision("rev-1", NOW - timedelta(days=1), rooms)
    snapshot = build_due_snapshot(
        revision,
        {
            area_id: AreaBinding(area_id, area_id.title(), index, False)
            for index, area_id in enumerate(("kitchen", "hall"), start=1)
        },
        NOW,
    )
    ledger = start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    for block_state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", block_state, NOW)
    for job_state in (JobState.DISPATCHING, JobState.ACCEPTED, JobState.RUNNING):
        ledger = ledger.replace_job_state("id-2", job_state, NOW)
    later_failure = NOW + timedelta(hours=1)
    ledger = ledger.replace_job_state("id-2", JobState.FAILED, later_failure)
    for job_state in (JobState.DISPATCHING, JobState.ACCEPTED, JobState.RUNNING):
        ledger = ledger.replace_job_state("id-3", job_state, NOW)

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        revision,
        "id-3",
        NOW,
        "rev-2",
    )

    assert result.ledger.blocks[0].state is BlockState.PARTIAL
    assert result.ledger.blocks[0].completed_at == later_failure


def test_completed_vacuum_and_mop_advances_both_completion_timestamps() -> None:
    ledger, revision = running_job(Mode.VACUUM_AND_MOP)

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        revision,
        "id-2",
        NOW,
        "rev-2",
    )

    room = result.plan_revision.room_plans[0]
    assert room.last_completed_vacuum_at == NOW
    assert room.last_completed_vacuum_and_mop_at == NOW


def test_delayed_completion_never_moves_plan_timestamp_backwards() -> None:
    ledger, revision = running_job(Mode.VACUUM)
    newer_completion = NOW + timedelta(hours=1)
    current_room = replace(
        revision.room_plans[0],
        last_completed_vacuum_at=newer_completion,
    )
    current_plan = replace(revision, room_plans=(current_room,))

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        current_plan,
        "id-2",
        NOW,
        "rev-2",
    )

    assert result.ledger.jobs[0].finished_at == NOW
    assert result.plan_revision.room_plans[0].last_completed_vacuum_at == newer_completion


def test_delayed_completion_never_moves_revision_creation_backwards() -> None:
    ledger, revision = running_job(Mode.VACUUM)
    current_plan = replace(revision, created_at=NOW + timedelta(hours=1))

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        current_plan,
        "id-2",
        NOW,
        "rev-2",
    )

    assert result.plan_revision.created_at == current_plan.created_at


def test_completion_rejects_reusing_revision_id_when_room_plan_changes() -> None:
    ledger, current_plan = running_job(Mode.VACUUM)

    with pytest.raises(
        ValueError,
        match="next revision ID must differ when room plan changes",
    ):
        queue_commands.complete_job_and_advance_plan(
            ledger,
            current_plan,
            "id-2",
            NOW,
            current_plan.revision_id,
        )


def test_completion_succeeds_without_recreating_area_removed_from_current_plan() -> None:
    ledger, revision = running_job(Mode.VACUUM)
    hall = replace(revision.room_plans[0], area_id="hall")
    current_plan = replace(revision, revision_id="rev-current", room_plans=(hall,))

    result = queue_commands.complete_job_and_advance_plan(
        ledger,
        current_plan,
        "id-2",
        NOW,
        "rev-unused",
    )

    assert result.ledger.jobs[0].state is JobState.COMPLETED
    assert result.plan_revision is current_plan
    assert [room.area_id for room in result.plan_revision.room_plans] == ["hall"]


def test_completion_rejects_plan_from_another_robot_lane() -> None:
    ledger, revision = running_job(Mode.VACUUM)
    other_lane_room = replace(revision.room_plans[0], lane_id="other-lane")
    other_lane_plan = replace(revision, room_plans=(other_lane_room,))

    with pytest.raises(ValueError, match="plan lane does not match job lane"):
        queue_commands.complete_job_and_advance_plan(
            ledger,
            other_lane_plan,
            "id-2",
            NOW,
            "rev-2",
        )

    assert ledger.jobs[0].state is JobState.RUNNING
