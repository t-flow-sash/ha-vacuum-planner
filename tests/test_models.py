from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockKind,
    BlockState,
    DispatchStrategy,
    JobState,
    JsonValue,
    Mode,
    PlanRevision,
    PlanSnapshot,
    PreferredMode,
    QueueBlock,
    QueueJob,
    QueueLedger,
    RoomPlan,
    SnapshotJob,
)

NOW = datetime(2026, 9, 17, 8, tzinfo=UTC)


def room(**overrides: object) -> RoomPlan:
    values: dict[str, object] = {
        "area_id": "kitchen",
        "lane_id": "robot-1",
        "enabled": True,
        "vacuum_interval_days": 2,
        "vacuum_and_mop_interval_days": 7,
        "preferred_mode": PreferredMode.AUTOMATIC,
        "priority": 10,
    }
    values.update(overrides)
    return RoomPlan(**values)  # type: ignore[arg-type]


def test_modes_are_limited_to_the_two_domain_modes() -> None:
    assert {mode.value for mode in Mode} == {"vacuum", "vacuum_and_mop"}
    with pytest.raises(ValueError, match="mop_only"):
        Mode("mop_only")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SnapshotJob(
            "area", "Area", "target", cast("Mode", "mop_only"), 0, NOW
        ),
        lambda: QueueJob(
            "job", "block", "area", "Area", "target", cast("Mode", "mop_only"), 0,
            JobState.PENDING, 0, NOW,
        ),
    ],
)
def test_job_models_reject_modes_outside_the_domain_enum(factory: object) -> None:
    with pytest.raises(ValueError, match="unsupported cleaning mode"):
        cast("Callable[[], object]", factory)()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: room(preferred_mode=cast("PreferredMode", "mop_only")),
        lambda: QueueBlock(
            "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW, NOW,
            BlockState.SEALED, (), cast("DispatchStrategy", "planner_sequential"),
            BlockGuarantee.PLANNER_ATOMIC,
        ),
        lambda: QueueBlock(
            "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW, NOW,
            BlockState.SEALED, (), DispatchStrategy.DEVICE_QUEUE,
            cast("BlockGuarantee", "robot_atomic"),
        ),
    ],
)
def test_domain_models_reject_enum_impostors(factory: object) -> None:
    with pytest.raises(ValueError, match="unsupported domain enum"):
        cast("Callable[[], object]", factory)()


def test_domain_models_are_immutable_and_normalize_sequences_to_tuples() -> None:
    plan = room()
    revision = PlanRevision("rev-1", NOW, [plan])  # type: ignore[arg-type]
    snapshot_job = SnapshotJob("kitchen", "Kitchen", "segment-4", Mode.VACUUM, 10, NOW)
    snapshot = PlanSnapshot("rev-1", "robot-1", NOW, [snapshot_job])  # type: ignore[arg-type]
    job = QueueJob(
        "job-1", "block-1", "kitchen", "Kitchen", "segment-4", Mode.VACUUM, 0,
        JobState.PENDING, 0, NOW,
    )
    block = QueueBlock(
        "block-1", BlockKind.SCHEDULED, "robot-1", "rev-1", "today", NOW, NOW,
        BlockState.SEALED, ["job-1"], DispatchStrategy.PLANNER_SEQUENTIAL,  # type: ignore[arg-type]
        BlockGuarantee.PLANNER_ATOMIC,
    )

    assert revision.room_plans == (plan,)
    assert snapshot.jobs == (snapshot_job,)
    assert block.job_ids == ("job-1",)
    nested = SnapshotJob(
        "nested",
        "Nested",
        {"segments": [1, 2]},  # type: ignore[dict-item]
        Mode.VACUUM,
        0,
        NOW,
    )
    frozen = cast("Mapping[str, JsonValue]", nested.adapter_target_snapshot)
    segments = cast("tuple[JsonValue, ...]", frozen["segments"])
    with pytest.raises(TypeError):
        frozen["segments"] = (3,)  # type: ignore[index]
    with pytest.raises(TypeError):
        segments[0] = 3  # type: ignore[index]
    for instance in (plan, revision, snapshot_job, snapshot, job, block):
        field_name = fields(instance)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(instance, field_name, "changed")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"area_id": ""}, "area_id"),
        ({"lane_id": ""}, "lane_id"),
        ({"vacuum_interval_days": 0}, "vacuum_interval_days"),
        ({"vacuum_and_mop_interval_days": -1}, "vacuum_and_mop_interval_days"),
        ({"skip_until": datetime(2026, 1, 1)}, "timezone-aware"),  # noqa: DTZ001
    ],
)
def test_room_plan_rejects_invalid_values(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        room(**overrides)


def test_revision_rejects_duplicate_areas_and_mixed_lanes() -> None:
    with pytest.raises(ValueError, match="duplicate area_id"):
        PlanRevision("rev-1", NOW, (room(), room()))
    with pytest.raises(ValueError, match="same lane"):
        PlanRevision("rev-1", NOW, (room(), room(area_id="hall", lane_id="robot-2")))


def test_queue_models_validate_identity_positions_and_state_timestamps() -> None:
    with pytest.raises(ValueError, match="position"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, -1,
            JobState.PENDING, 0, NOW,
        )
    with pytest.raises(ValueError, match="sealed_at"):
        QueueBlock(
            "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW, None,
            BlockState.SEALED, (), DispatchStrategy.NATIVE_BATCH,
            BlockGuarantee.PLANNER_ATOMIC,
        )


def test_block_lifecycle_timestamps_must_be_chronological() -> None:
    before_creation = NOW - timedelta(seconds=1)

    with pytest.raises(ValueError, match="block lifecycle timestamps"):
        QueueBlock(
            "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW,
            before_creation, BlockState.SEALED, (), DispatchStrategy.NATIVE_BATCH,
            BlockGuarantee.PLANNER_ATOMIC,
        )


def test_dispatched_job_requires_attempt_and_sent_timestamp() -> None:
    with pytest.raises(ValueError, match="dispatched job requires attempt and sent_at"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
            JobState.DISPATCHING, 0, NOW,
        )


def test_pending_job_rejects_dispatch_lifecycle_data() -> None:
    with pytest.raises(ValueError, match="pending job cannot contain dispatch data"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
            JobState.PENDING, 0, NOW, sent_at=NOW,
        )


def test_failed_dispatched_attempt_requires_sent_timestamp() -> None:
    with pytest.raises(ValueError, match="dispatched failure requires sent_at"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
            JobState.FAILED, 1, NOW, finished_at=NOW,
        )


def test_running_job_requires_started_timestamp() -> None:
    with pytest.raises(ValueError, match="started_at is required"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
            JobState.RUNNING, 1, NOW, sent_at=NOW,
        )


def test_nonterminal_job_rejects_finished_timestamp() -> None:
    with pytest.raises(ValueError, match="nonterminal job cannot have finished_at"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
            JobState.UNCERTAIN, 1, NOW, sent_at=NOW, finished_at=NOW,
        )


@pytest.mark.parametrize(
    "state", [JobState.COMPLETED, JobState.FAILED, JobState.SKIPPED, JobState.CANCELLED]
)
def test_terminal_job_requires_finished_timestamp(state: JobState) -> None:
    with pytest.raises(ValueError, match="finished_at is required"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
            state, 1, NOW, sent_at=NOW, started_at=NOW,
        )


def test_job_lifecycle_timestamps_must_be_chronological() -> None:
    before_planning = NOW - timedelta(seconds=1)

    with pytest.raises(ValueError, match="lifecycle timestamps"):
        QueueJob(
            "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
            JobState.COMPLETED, 1, NOW, sent_at=before_planning,
            started_at=NOW, finished_at=NOW,
        )


def test_robot_atomic_is_only_valid_for_a_device_queue() -> None:
    with pytest.raises(ValueError, match="robot_atomic requires device_queue"):
        QueueBlock(
            "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW, NOW,
            BlockState.SEALED, (), DispatchStrategy.NATIVE_BATCH,
            BlockGuarantee.ROBOT_ATOMIC,
        )


def test_ledger_rejects_active_job_under_uncommitted_parent() -> None:
    job = QueueJob(
        "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
        JobState.DISPATCHING, 1, NOW, sent_at=NOW,
    )
    block = QueueBlock(
        "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW, NOW,
        BlockState.SEALED, ("job",), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )

    with pytest.raises(ValueError, match="job state is incompatible with parent block"):
        QueueLedger(1, 0, (block,), (job,))


def test_ledger_rejects_reordered_lane_blocks() -> None:
    later = NOW + timedelta(seconds=1)
    older = QueueBlock(
        "older", BlockKind.SCHEDULED, "lane", "rev", "old", NOW, NOW,
        BlockState.SEALED, (), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    newer = QueueBlock(
        "newer", BlockKind.ADHOC, "lane", "rev", "new", later, later,
        BlockState.SEALED, (), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )

    with pytest.raises(ValueError, match="lane blocks must remain append ordered"):
        QueueLedger(1, 0, (newer, older), ())


def test_ledger_rejects_orphan_jobs_unknown_parents_and_global_id_collisions() -> None:
    orphan = QueueJob(
        "job", "missing", "area", "Area", "target", Mode.VACUUM, 0,
        JobState.PENDING, 0, NOW,
    )
    with pytest.raises(ValueError, match="unknown parent block"):
        QueueLedger(1, 0, (), (orphan,))

    block = QueueBlock(
        "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW, NOW,
        BlockState.SEALED, (), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    unlisted = QueueJob(
        "job", "block", "area", "Area", "target", Mode.VACUUM, 0,
        JobState.PENDING, 0, NOW,
    )
    with pytest.raises(ValueError, match="orphan job"):
        QueueLedger(1, 0, (block,), (unlisted,))

    colliding_job = QueueJob(
        "block", "block", "area", "Area", "target", Mode.VACUUM, 0,
        JobState.PENDING, 0, NOW,
    )
    colliding_block = QueueBlock(
        "block", BlockKind.SCHEDULED, "lane", "rev", "key", NOW, NOW,
        BlockState.SEALED, ("block",), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    with pytest.raises(ValueError, match="globally unique"):
        QueueLedger(1, 0, (colliding_block,), (colliding_job,))
