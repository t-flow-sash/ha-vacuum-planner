from datetime import UTC, datetime
from inspect import signature

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
from custom_components.vacuum_planner.domain.planning import AreaBinding
from custom_components.vacuum_planner.domain.queue import (
    DuplicateIdentityError,
    EnqueueStatus,
    LaneAlreadyOpenError,
    QueueBusyError,
    RevisionConflictError,
    StartStatus,
    enqueue_area,
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
        ledger, snapshot(), "lane", "2026-09-17", NOW, ids,
        DispatchStrategy.PLANNER_SEQUENTIAL, BlockGuarantee.PLANNER_ATOMIC,
    )

    assert result.status is StartStatus.NO_WORK
    assert result.ledger is ledger
    assert ids.calls == 0


def test_start_rejects_a_snapshot_bound_to_a_different_lane() -> None:
    ledger = QueueLedger.empty()
    bound_snapshot = snapshot("kitchen")

    with pytest.raises(ValueError, match="snapshot lane does not match"):
        start_due_block(
            ledger, bound_snapshot, "other-lane", "today", NOW, IDs("unused"),
            DispatchStrategy.PLANNER_SEQUENTIAL, BlockGuarantee.PLANNER_ATOMIC,
        )

    assert ledger == QueueLedger.empty()


def test_start_rejects_stale_revision_before_allocating_ids() -> None:
    ledger = QueueLedger(schema_version=1, revision=1, blocks=(), jobs=())
    ids = IDs("must-not-be-used")

    with pytest.raises(RevisionConflictError, match="expected revision 0, found 1"):
        start_due_block(
            ledger, snapshot("kitchen"), "lane", "today", NOW, ids,
            DispatchStrategy.PLANNER_SEQUENTIAL, BlockGuarantee.PLANNER_ATOMIC,
            expected_revision=0,
        )

    assert ids.calls == 0
    assert ledger.blocks == ()


def test_start_atomically_seals_the_complete_ordered_snapshot() -> None:
    ledger = QueueLedger.empty()
    ids = IDs("block-1", "job-1", "job-2")

    result = start_due_block(
        ledger, snapshot("kitchen", "hall"), "lane", "2026-09-17", NOW, ids,
        DispatchStrategy.PLANNER_SEQUENTIAL, BlockGuarantee.PLANNER_ATOMIC,
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
            QueueLedger.empty(), snapshot("kitchen"), "lane", "today", NOW,
            IDs("unused"), DispatchStrategy.DEVICE_QUEUE, BlockGuarantee.ROBOT_ATOMIC,
        )

    result = start_due_block(
        QueueLedger.empty(), snapshot("kitchen"), "lane", "today", NOW,
        IDs("block-1", "job-1"), DispatchStrategy.DEVICE_QUEUE,
        BlockGuarantee.ROBOT_ATOMIC, atomic_device_commit=True,
    )

    assert result.block is not None
    assert result.block.guarantee is BlockGuarantee.ROBOT_ATOMIC


def test_robot_atomic_still_requires_device_queue_with_commit_proof() -> None:
    with pytest.raises(ValueError, match="robot_atomic requires device_queue"):
        start_due_block(
            QueueLedger.empty(), snapshot("kitchen"), "lane", "today", NOW,
            IDs("block-1", "job-1"), DispatchStrategy.NATIVE_BATCH,
            BlockGuarantee.ROBOT_ATOMIC, atomic_device_commit=True,
        )


def test_failed_adapter_commit_atomically_fails_block_and_unsent_jobs() -> None:
    started = start_due_block(
        QueueLedger.empty(), snapshot("kitchen", "hall"), "lane", "today", NOW,
        IDs("block-1", "job-1", "job-2"), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    committing = started.replace_block_state("block-1", BlockState.COMMITTING, NOW)

    failed = queue_commands.fail_block_commit(
        committing, "block-1", NOW, error_code="adapter_rejected"
    )

    assert failed.blocks[0].state is BlockState.FAILED
    assert [job.state for job in failed.jobs] == [JobState.FAILED, JobState.FAILED]
    assert failed.revision == committing.revision + 1


def test_repeated_start_returns_same_open_block_despite_stale_revision() -> None:
    first_ids = IDs("block-1", "job-1")
    first = start_due_block(
        QueueLedger.empty(), snapshot("kitchen"), "lane", "today", NOW, first_ids,
        DispatchStrategy.NATIVE_BATCH, BlockGuarantee.PLANNER_ATOMIC,
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
        first.ledger, invalid_retry_snapshot, "lane", "today", NOW, second_ids,
        DispatchStrategy.NATIVE_BATCH, BlockGuarantee.PLANNER_ATOMIC,
        expected_revision=0,
    )

    assert second.status is StartStatus.EXISTING
    assert second.block is first.block
    assert second.jobs == first.jobs
    assert second.ledger is first.ledger
    assert second_ids.calls == 0


def test_start_rejects_second_open_block_in_lane_with_different_idempotency_key() -> None:
    first = start_due_block(
        QueueLedger.empty(), snapshot("kitchen"), "lane", "today", NOW,
        IDs("block-1", "job-1"), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    unused_ids = IDs("must-not-be-used")

    with pytest.raises(LaneAlreadyOpenError, match="lane already has an open block"):
        start_due_block(
            first.ledger, snapshot("hall"), "lane", "tomorrow", NOW, unused_ids,
            DispatchStrategy.NATIVE_BATCH, BlockGuarantee.PLANNER_ATOMIC,
        )

    assert unused_ids.calls == 0


def test_id_collision_aborts_without_a_partially_visible_block() -> None:
    ids = IDs("same", "same")
    ledger = QueueLedger.empty()

    with pytest.raises(DuplicateIdentityError):
        start_due_block(
            ledger, snapshot("kitchen"), "lane", "today", NOW, ids,
            DispatchStrategy.NATIVE_BATCH, BlockGuarantee.PLANNER_ATOMIC,
        )

    assert ledger.blocks == ()
    assert ledger.jobs == ()


def committed_ledger() -> QueueLedger:
    started = start_due_block(
        QueueLedger.empty(), snapshot("kitchen"), "lane", "today", NOW,
        IDs("block-1", "job-1"), DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    committing = started.ledger.replace_block_state("block-1", BlockState.COMMITTING, NOW)
    return committing.replace_block_state("block-1", BlockState.COMMITTED, NOW)


def test_adhoc_job_is_appended_as_own_block_after_sealed_scheduled_block() -> None:
    result = enqueue_area(
        committed_ledger(), "lane", AreaBinding("hall", "Hall", "segment-2", True),
        Mode.VACUUM_AND_MOP, NOW, IDs("adhoc-block", "adhoc-job"),
    )

    assert result.status is EnqueueStatus.CREATED
    assert [block.block_id for block in result.ledger.blocks] == ["block-1", "adhoc-block"]
    assert result.block is result.ledger.blocks[-1]
    assert result.block.job_ids == ("adhoc-job",)
    assert result.job is result.ledger.jobs[-1]
    assert result.job.position == 0


def test_unconfirmed_adhoc_enqueue_is_sealed_but_not_committed() -> None:
    result = enqueue_area(
        committed_ledger(), "lane", AreaBinding("hall", "Hall", "segment-2", True),
        Mode.VACUUM, NOW, IDs("adhoc-block", "adhoc-job"),
    )

    assert result.block.state is BlockState.SEALED
    assert result.block.committed_at is None


def test_later_block_cannot_dispatch_before_earlier_lane_block_is_terminal() -> None:
    result = enqueue_area(
        committed_ledger(), "lane", AreaBinding("hall", "Hall", "segment-2", True),
        Mode.VACUUM, NOW, IDs("adhoc-block", "adhoc-job"),
    )
    ledger = result.ledger.replace_block_state("adhoc-block", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("adhoc-block", BlockState.COMMITTED, NOW)

    with pytest.raises(ValueError, match="earlier lane block"):
        ledger.replace_job_state("adhoc-job", JobState.DISPATCHING, NOW)


def test_enqueue_has_no_adapter_confirmation_commit_shortcut() -> None:
    assert "adapter_confirmed" not in signature(enqueue_area).parameters


def test_identical_open_adhoc_job_is_deduplicated_by_default() -> None:
    first = enqueue_area(
        committed_ledger(), "lane", AreaBinding("hall", "Hall", "segment-2", True),
        Mode.VACUUM, NOW, IDs("adhoc-1", "job-2"),
    )
    ledger = first.ledger.replace_block_state("adhoc-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("adhoc-1", BlockState.COMMITTED, NOW)
    unused_ids = IDs("unused")

    second = enqueue_area(
        ledger, "lane", AreaBinding("hall", "Renamed Hall", "new-target", True),
        Mode.VACUUM, NOW, unused_ids,
    )

    assert second.status is EnqueueStatus.DUPLICATE
    assert second.job is first.job
    assert second.ledger is ledger
    assert unused_ids.calls == 0


def test_confirmed_repeat_may_append_an_identical_open_job() -> None:
    first = enqueue_area(
        committed_ledger(), "lane", AreaBinding("hall", "Hall", "target", True),
        Mode.VACUUM, NOW, IDs("adhoc-1", "job-2"),
    )
    ledger = first.ledger.replace_block_state("adhoc-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("adhoc-1", BlockState.COMMITTED, NOW)

    second = enqueue_area(
        ledger, "lane", AreaBinding("hall", "Hall", "target", True),
        Mode.VACUUM, NOW, IDs("adhoc-2", "job-3"), confirmed_repeat=True,
    )

    assert second.status is EnqueueStatus.CREATED
    assert second.job is not first.job
    assert [block.block_id for block in second.ledger.blocks] == [
        "block-1", "adhoc-1", "adhoc-2",
    ]


@pytest.mark.parametrize("state", [BlockState.SEALED, BlockState.COMMITTING])
def test_append_gate_is_closed_during_sealing_and_commit(state: BlockState) -> None:
    started = start_due_block(
        QueueLedger.empty(), snapshot("kitchen"), "lane", "today", NOW,
        IDs("block", "job"), DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    ledger = started.ledger
    if state is BlockState.COMMITTING:
        ledger = ledger.replace_block_state("block", state, NOW)

    with pytest.raises(QueueBusyError, match="busy_committing"):
        enqueue_area(
            ledger, "lane", AreaBinding("hall", "Hall", "target", True),
            Mode.VACUUM, NOW, IDs("adhoc", "job-2"),
        )
