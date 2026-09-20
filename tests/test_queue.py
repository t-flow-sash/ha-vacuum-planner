from datetime import UTC, datetime

import pytest

from custom_components.vacuum_planner.domain import queue as queue_commands
from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockState,
    DispatchStrategy,
    JobState,
    Mode,
    PlanSnapshot,
    QueueLedger,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import (
    DuplicateIdentityError,
    LaneAlreadyOpenError,
    RevisionConflictError,
    StartStatus,
    start_due_block,
)

NOW = datetime(2026, 9, 17, 8, tzinfo=UTC)


class IDs:
    def __init__(self, *values: str) -> None:
        self.values = iter(values)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return next(self.values)


def snapshot(*areas: str) -> PlanSnapshot:
    return PlanSnapshot(
        "rev-1",
        "lane",
        NOW,
        tuple(
            SnapshotJob(area, area.title(), {"segment": area}, Mode.VACUUM, 0, NOW)
            for area in areas
        ),
    )


def test_empty_snapshot_returns_no_work_without_mutating_ledger_or_allocating_ids() -> None:
    ledger = QueueLedger.empty()
    ids = IDs("unused")

    result = start_due_block(
        ledger,
        snapshot(),
        "lane",
        "2026-09-17",
        NOW,
        ids,
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    )

    assert result.status is StartStatus.NO_WORK
    assert result.ledger is ledger
    assert ids.calls == 0


def test_start_rejects_a_snapshot_bound_to_a_different_lane() -> None:
    ledger = QueueLedger.empty()
    bound_snapshot = snapshot("kitchen")

    with pytest.raises(ValueError, match="snapshot lane does not match"):
        start_due_block(
            ledger,
            bound_snapshot,
            "other-lane",
            "today",
            NOW,
            IDs("unused"),
            DispatchStrategy.PLANNER_SEQUENTIAL,
            BlockGuarantee.PLANNER_ATOMIC,
        )

    assert ledger == QueueLedger.empty()


def test_start_rejects_stale_revision_before_allocating_ids() -> None:
    ledger = QueueLedger(schema_version=1, revision=1, blocks=(), jobs=())
    ids = IDs("must-not-be-used")

    with pytest.raises(RevisionConflictError, match="expected revision 0, found 1"):
        start_due_block(
            ledger,
            snapshot("kitchen"),
            "lane",
            "today",
            NOW,
            ids,
            DispatchStrategy.PLANNER_SEQUENTIAL,
            BlockGuarantee.PLANNER_ATOMIC,
            expected_revision=0,
        )

    assert ids.calls == 0
    assert ledger.blocks == ()


def test_start_atomically_seals_the_complete_ordered_snapshot() -> None:
    ledger = QueueLedger.empty()
    ids = IDs("block-1", "job-1", "job-2")

    result = start_due_block(
        ledger,
        snapshot("kitchen", "hall"),
        "lane",
        "2026-09-17",
        NOW,
        ids,
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    )

    assert result.status is StartStatus.CREATED
    assert result.block is not None
    assert result.block.state is BlockState.SEALED
    assert result.block.job_ids == ("job-1", "job-2")
    assert [job.area_id for job in result.jobs] == ["kitchen", "hall"]
    assert [job.position for job in result.jobs] == [0, 1]
    assert result.ledger.revision == 1
    assert result.ledger.blocks == (result.block,)
    assert result.ledger.jobs == result.jobs


def test_robot_atomic_start_requires_explicit_atomic_device_commit_proof() -> None:
    with pytest.raises(ValueError, match="robot_atomic requires atomic device commit proof"):
        start_due_block(
            QueueLedger.empty(),
            snapshot("kitchen"),
            "lane",
            "today",
            NOW,
            IDs("unused"),
            DispatchStrategy.DEVICE_QUEUE,
            BlockGuarantee.ROBOT_ATOMIC,
        )

    result = start_due_block(
        QueueLedger.empty(),
        snapshot("kitchen"),
        "lane",
        "today",
        NOW,
        IDs("block-1", "job-1"),
        DispatchStrategy.DEVICE_QUEUE,
        BlockGuarantee.ROBOT_ATOMIC,
        atomic_device_commit=True,
    )

    assert result.block is not None
    assert result.block.guarantee is BlockGuarantee.ROBOT_ATOMIC


def test_robot_atomic_still_requires_device_queue_with_commit_proof() -> None:
    with pytest.raises(ValueError, match="robot_atomic requires device_queue"):
        start_due_block(
            QueueLedger.empty(),
            snapshot("kitchen"),
            "lane",
            "today",
            NOW,
            IDs("block-1", "job-1"),
            DispatchStrategy.NATIVE_BATCH,
            BlockGuarantee.ROBOT_ATOMIC,
            atomic_device_commit=True,
        )


def test_failed_adapter_commit_atomically_fails_block_and_unsent_jobs() -> None:
    started = start_due_block(
        QueueLedger.empty(),
        snapshot("kitchen", "hall"),
        "lane",
        "today",
        NOW,
        IDs("block-1", "job-1", "job-2"),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    committing = started.replace_block_state("block-1", BlockState.COMMITTING, NOW)

    failed = queue_commands.fail_block_commit(
        committing, "block-1", NOW, error_code="adapter_rejected"
    )

    assert failed.blocks[0].state is BlockState.FAILED
    assert [job.state for job in failed.jobs] == [JobState.FAILED, JobState.FAILED]
    assert failed.revision == committing.revision + 1


def test_native_batch_commit_rejects_a_sequential_dispatch_strategy() -> None:
    started = start_due_block(
        QueueLedger.empty(),
        snapshot("kitchen"),
        "lane",
        "today",
        NOW,
        IDs("block-1", "job-1"),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger

    with pytest.raises(ValueError, match="native batch strategy"):
        queue_commands.begin_native_batch_commit(started, "block-1", NOW)


def test_dispatch_quarantine_changes_only_the_target_block() -> None:
    first_snapshot = PlanSnapshot(
        "rev-1",
        "lane-1",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", (), Mode.VACUUM, 0, NOW),),
    )
    first = start_due_block(
        QueueLedger.empty(),
        first_snapshot,
        "lane-1",
        "first",
        NOW,
        IDs("block-1", "job-1"),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    second_snapshot = PlanSnapshot(
        "rev-1",
        "lane-2",
        NOW,
        (SnapshotJob("hall", "Hall", (), Mode.VACUUM, 0, NOW),),
    )
    second = start_due_block(
        first,
        second_snapshot,
        "lane-2",
        "second",
        NOW,
        IDs("block-2", "job-2"),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    committing = queue_commands.begin_native_batch_commit(second, "block-1", NOW)
    committing = queue_commands.begin_native_batch_commit(committing, "block-2", NOW)

    quarantined = queue_commands.quarantine_block_dispatch(committing, "block-1", NOW)

    assert [block.state for block in quarantined.blocks] == [
        BlockState.UNCERTAIN,
        BlockState.COMMITTING,
    ]
    assert [job.state for job in quarantined.jobs] == [
        JobState.UNCERTAIN,
        JobState.DISPATCHING,
    ]


def test_repeated_start_returns_same_open_block_despite_stale_revision() -> None:
    first_ids = IDs("block-1", "job-1")
    first = start_due_block(
        QueueLedger.empty(),
        snapshot("kitchen"),
        "lane",
        "today",
        NOW,
        first_ids,
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
        expected_revision=0,
    )
    second_ids = IDs("must-not-be-used")

    invalid_retry_snapshot = PlanSnapshot(
        "different-revision",
        "other-lane",
        NOW,
        (),
    )
    second = start_due_block(
        first.ledger,
        invalid_retry_snapshot,
        "lane",
        "today",
        NOW,
        second_ids,
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
        expected_revision=0,
    )

    assert second.status is StartStatus.EXISTING
    assert second.block is first.block
    assert second.jobs == first.jobs
    assert second.ledger is first.ledger
    assert second_ids.calls == 0


def test_start_rejects_second_open_block_in_lane_with_different_idempotency_key() -> None:
    first = start_due_block(
        QueueLedger.empty(),
        snapshot("kitchen"),
        "lane",
        "today",
        NOW,
        IDs("block-1", "job-1"),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    unused_ids = IDs("must-not-be-used")

    with pytest.raises(LaneAlreadyOpenError, match="lane already has an open block"):
        start_due_block(
            first.ledger,
            snapshot("hall"),
            "lane",
            "tomorrow",
            NOW,
            unused_ids,
            DispatchStrategy.NATIVE_BATCH,
            BlockGuarantee.PLANNER_ATOMIC,
        )

    assert unused_ids.calls == 0


def test_id_collision_aborts_without_a_partially_visible_block() -> None:
    ids = IDs("same", "same")
    ledger = QueueLedger.empty()

    with pytest.raises(DuplicateIdentityError):
        start_due_block(
            ledger,
            snapshot("kitchen"),
            "lane",
            "today",
            NOW,
            ids,
            DispatchStrategy.NATIVE_BATCH,
            BlockGuarantee.PLANNER_ATOMIC,
        )

    assert ledger.blocks == ()
    assert ledger.jobs == ()
