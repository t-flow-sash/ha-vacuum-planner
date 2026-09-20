from dataclasses import replace
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
    UncertainResolution,
    quarantine_ambiguous_dispatches,
    resolve_uncertain_job,
    start_due_block,
)

NOW = datetime(2026, 9, 17, 8, tzinfo=UTC)
RESTARTED_AT = datetime(2026, 9, 17, 9, tzinfo=UTC)


class IDs:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"id-{self.index}"


def test_restart_quarantines_ambiguous_dispatch_without_marking_success() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
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
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTED, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.RUNNING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)

    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    assert recovered.blocks[0].state is BlockState.UNCERTAIN
    assert recovered.blocks[0].completed_at is None
    assert recovered.jobs[0].state is JobState.UNCERTAIN
    assert recovered.jobs[0].finished_at is None
    assert recovered.last_reconciled_at == RESTARTED_AT
    assert recovered.revision == ledger.revision + 1


def test_safe_retry_after_uncertain_dispatch_resumes_run_without_claiming_completion() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
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
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTED, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.RUNNING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    resolved = resolve_uncertain_job(
        recovered, "id-2", UncertainResolution.RETRY_SAFE, RESTARTED_AT
    )

    assert resolved.blocks[0].state is BlockState.RUNNING
    assert resolved.jobs[0].state is JobState.FAILED
    assert resolved.jobs[0].finished_at == RESTARTED_AT
    retried = resolved.replace_job_state("id-2", JobState.DISPATCHING, RESTARTED_AT)
    assert retried.jobs[0].attempt == 2


def test_uncertain_parent_blocks_pending_job_dispatch() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
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
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTED, NOW)
    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    with pytest.raises(ValueError, match="uncertain parent block"):
        recovered.replace_job_state("id-2", JobState.DISPATCHING, RESTARTED_AT)


def test_explicit_safe_resolution_releases_pending_jobs_after_uncertain_restart() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
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
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTED, NOW)
    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    resolved = queue_commands.resolve_uncertain_block(
        recovered, "id-1", UncertainResolution.RETRY_SAFE
    )

    assert resolved.blocks[0].state is BlockState.RUNNING
    dispatchable = resolved.replace_job_state("id-2", JobState.DISPATCHING, RESTARTED_AT)
    assert dispatchable.jobs[0].state is JobState.DISPATCHING


def test_uncertain_block_release_rejects_uncorrelated_active_child() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
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
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.UNCERTAIN, RESTARTED_AT)

    with pytest.raises(ValueError, match="uncorrelated active child"):
        queue_commands.resolve_uncertain_block(ledger, "id-1", UncertainResolution.RETRY_SAFE)


def test_job_resolution_keeps_block_uncertain_for_uncorrelated_active_sibling() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        tuple(
            SnapshotJob(f"area-{index}", f"Area {index}", index, Mode.VACUUM, 0, NOW)
            for index in range(2)
        ),
    )
    ledger = start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    for job_id in ("id-2", "id-3"):
        ledger = ledger.replace_job_state(job_id, JobState.DISPATCHING, NOW)
        ledger = ledger.replace_job_state(job_id, JobState.ACCEPTED, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.UNCERTAIN, RESTARTED_AT)
    ledger = ledger.replace_block_state("id-1", BlockState.UNCERTAIN, RESTARTED_AT)

    resolved = resolve_uncertain_job(ledger, "id-2", UncertainResolution.RETRY_SAFE, RESTARTED_AT)

    assert resolved.blocks[0].state is BlockState.UNCERTAIN
    assert resolved.jobs[1].state is JobState.ACCEPTED


@pytest.mark.parametrize("ambiguous_state", [JobState.ACCEPTED, JobState.RUNNING])
def test_restart_quarantines_all_active_states_without_external_correlation(
    ambiguous_state: JobState,
) -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
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
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW)
    if ambiguous_state is JobState.RUNNING:
        ledger = ledger.replace_job_state("id-2", JobState.RUNNING, NOW)

    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    assert recovered.blocks[0].state is BlockState.UNCERTAIN
    assert recovered.jobs[0].state is JobState.UNCERTAIN
    assert recovered.jobs[0].finished_at is None


@pytest.mark.parametrize("invalid_token", ["", "   "])
def test_restart_rejects_blank_job_correlation(invalid_token: str) -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
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
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW, adapter_token="temporary")
    ledger = replace(
        ledger,
        jobs=(replace(ledger.jobs[0], adapter_token=invalid_token),),
    )

    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    assert recovered.blocks[0].state is BlockState.UNCERTAIN
    assert recovered.jobs[0].state is JobState.UNCERTAIN


@pytest.mark.parametrize("invalid_run_id", ["", "   "])
def test_restart_rejects_blank_block_correlation(invalid_run_id: str) -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("kitchen", "Kitchen", 4, Mode.VACUUM, 0, NOW),),
    )
    ledger = start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTED, NOW)
    ledger = replace(
        ledger,
        blocks=(replace(ledger.blocks[0], adapter_run_id=invalid_run_id),),
    )

    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    assert recovered.blocks[0].state is BlockState.UNCERTAIN


def test_recovery_preserves_correlated_job_when_sibling_dispatch_is_ambiguous() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        tuple(
            SnapshotJob(f"area-{index}", f"Area {index}", index, Mode.VACUUM, 0, NOW)
            for index in range(2)
        ),
    )
    ledger = start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    ledger = ledger.replace_block_state("id-1", BlockState.COMMITTING, NOW)
    ledger = ledger.replace_block_state(
        "id-1", BlockState.COMMITTED, NOW, adapter_run_id="correlated-run"
    )
    ledger = ledger.replace_block_state("id-1", BlockState.RUNNING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state(
        "id-2", JobState.ACCEPTED, NOW, adapter_token="correlated-job"
    )
    ledger = ledger.replace_job_state("id-3", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-3", JobState.ACCEPTED, NOW)

    recovered = quarantine_ambiguous_dispatches(ledger, RESTARTED_AT)

    assert recovered.blocks[0].state is BlockState.UNCERTAIN
    assert [job.state for job in recovered.jobs] == [
        JobState.ACCEPTED,
        JobState.UNCERTAIN,
    ]

    resolved = resolve_uncertain_job(
        recovered, "id-3", UncertainResolution.RETRY_SAFE, RESTARTED_AT
    )
    assert resolved.blocks[0].state is BlockState.RUNNING
    assert resolved.jobs[0].adapter_token == ledger.jobs[0].adapter_token
