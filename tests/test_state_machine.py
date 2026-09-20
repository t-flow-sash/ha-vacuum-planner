from dataclasses import replace
from datetime import UTC, datetime

import pytest

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
    begin_native_batch_commit,
    quarantine_block_dispatch,
    resolve_uncertain_job,
    start_due_block,
)

NOW = datetime(2026, 9, 17, 8, tzinfo=UTC)


class IDs:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"id-{self.index}"


def ledger_with_jobs(count: int = 1) -> QueueLedger:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        tuple(
            SnapshotJob(f"area-{index}", f"Area {index}", index, Mode.VACUUM, 0, NOW)
            for index in range(count)
        ),
    )
    return start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger


def running_ledger_with_jobs(count: int = 1) -> QueueLedger:
    ledger = ledger_with_jobs(count)
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    return ledger


def test_block_state_machine_accepts_documented_happy_path() -> None:
    ledger = ledger_with_jobs()
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.RUNNING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.COMPLETED, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.COMPLETED, NOW)

    assert ledger.blocks[0].state is BlockState.COMPLETED
    assert ledger.blocks[0].completed_at == NOW
    assert ledger.jobs[0].state is JobState.COMPLETED
    assert ledger.jobs[0].attempt == 1
    assert ledger.jobs[0].sent_at == NOW
    assert ledger.jobs[0].started_at == NOW
    assert ledger.jobs[0].finished_at == NOW


def test_commit_persists_external_run_correlation_with_the_revision() -> None:
    ledger = ledger_with_jobs().replace_block_state("id-1", BlockState.COMMITTING, NOW)

    committed = ledger.replace_block_state(
        "id-1", BlockState.COMMITTED, NOW, adapter_run_id="run-42"
    )

    assert committed.blocks[0].adapter_run_id == "run-42"
    assert committed.revision == ledger.revision + 1


def test_commit_rejects_blank_external_run_correlation() -> None:
    ledger = ledger_with_jobs().replace_block_state("id-1", BlockState.COMMITTING, NOW)

    with pytest.raises(ValueError, match="adapter_run_id must not be empty"):
        ledger.replace_block_state("id-1", BlockState.COMMITTED, NOW, adapter_run_id="   ")


def test_invalid_block_and_job_transitions_are_rejected() -> None:
    ledger = ledger_with_jobs()
    with pytest.raises(ValueError, match="invalid block transition"):
        ledger.replace_block_state("id-1", BlockState.COMPLETED, NOW)
    with pytest.raises(ValueError, match="invalid job transition"):
        ledger.replace_job_state("id-2", JobState.COMPLETED, NOW)


@pytest.mark.parametrize("parent_state", [BlockState.SEALED, BlockState.COMMITTING])
def test_dispatch_requires_successfully_committed_parent(parent_state: BlockState) -> None:
    ledger = ledger_with_jobs()
    if parent_state is BlockState.COMMITTING:
        ledger = ledger.replace_block_state("id-1", parent_state, NOW)

    with pytest.raises(ValueError, match="committed parent block"):
        ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)


def test_committing_dispatching_jobs_require_native_batch_strategy() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("area", "Area", (), Mode.VACUUM, 0, NOW),),
    )
    sealed = start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    committing = begin_native_batch_commit(sealed, "id-1", NOW)
    sequential_block = replace(
        committing.blocks[0],
        dispatch_strategy=DispatchStrategy.PLANNER_SEQUENTIAL,
    )

    with pytest.raises(ValueError, match="incompatible with parent block"):
        replace(committing, blocks=(sequential_block,))


def test_sequential_dispatch_waits_for_the_previous_job_to_complete() -> None:
    ledger = running_ledger_with_jobs(2)

    with pytest.raises(ValueError, match="previous sequential job"):
        ledger.replace_job_state("id-3", JobState.DISPATCHING, NOW)


def test_sequential_retry_cannot_jump_behind_a_later_active_job() -> None:
    ledger = running_ledger_with_jobs(2)
    for state in (
        JobState.DISPATCHING,
        JobState.ACCEPTED,
        JobState.RUNNING,
        JobState.FAILED,
    ):
        ledger = ledger.replace_job_state("id-2", state, NOW)
    ledger = ledger.replace_job_state("id-3", JobState.DISPATCHING, NOW)

    with pytest.raises(ValueError, match="later sequential job"):
        ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)


def test_retry_keeps_identity_and_resets_previous_attempt_lifecycle() -> None:
    ledger = running_ledger_with_jobs()
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state(
        "id-2", JobState.ACCEPTED, NOW, adapter_token="previous-attempt"
    )
    ledger = ledger.replace_job_state("id-2", JobState.RUNNING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.FAILED, NOW, error_code="adapter_error")

    retried = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)

    assert retried.jobs[0].job_id == "id-2"
    assert retried.jobs[0].attempt == 2
    assert retried.jobs[0].sent_at == NOW
    assert retried.jobs[0].adapter_token is None
    assert retried.jobs[0].started_at is None
    assert retried.jobs[0].finished_at is None
    assert retried.jobs[0].error_code is None


def test_cancel_of_accepted_or_running_job_requires_adapter_confirmation() -> None:
    ledger = running_ledger_with_jobs().replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW)

    with pytest.raises(ValueError, match="confirmation"):
        ledger.replace_job_state("id-2", JobState.CANCELLED, NOW)
    cancelled = ledger.replace_job_state("id-2", JobState.CANCELLED, NOW, adapter_confirmed=True)

    assert cancelled.jobs[0].state is JobState.CANCELLED


def test_partial_requires_mixed_terminal_job_results() -> None:
    ledger = ledger_with_jobs(2)
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    with pytest.raises(ValueError, match="mixed terminal"):
        ledger.replace_block_state("id-1", BlockState.PARTIAL, NOW)

    first = ledger.replace_job_state("id-2", JobState.CANCELLED, NOW)
    first = first.replace_job_state("id-3", JobState.CANCELLED, NOW)
    with pytest.raises(ValueError, match="mixed terminal"):
        first.replace_block_state("id-1", BlockState.PARTIAL, NOW)

    mixed = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    mixed = mixed.replace_job_state("id-2", JobState.ACCEPTED, NOW)
    mixed = mixed.replace_job_state("id-2", JobState.RUNNING, NOW)
    mixed = mixed.replace_job_state("id-2", JobState.COMPLETED, NOW)
    mixed = mixed.replace_job_state("id-3", JobState.CANCELLED, NOW)

    assert (
        mixed.replace_block_state("id-1", BlockState.PARTIAL, NOW).blocks[0].state
        is BlockState.PARTIAL
    )


def test_uncertain_is_not_a_success_and_has_no_finished_timestamp() -> None:
    ledger = running_ledger_with_jobs().replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW)
    uncertain = ledger.replace_job_state("id-2", JobState.UNCERTAIN, NOW)

    assert uncertain.jobs[0].state is JobState.UNCERTAIN
    assert uncertain.jobs[0].finished_at is None


def test_uncertain_job_can_only_continue_after_explicit_safe_retry_resolution() -> None:
    ledger = ledger_with_jobs()
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.UNCERTAIN, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.UNCERTAIN, NOW)

    resolved = resolve_uncertain_job(ledger, "id-2", UncertainResolution.RETRY_SAFE, NOW)

    assert resolved.jobs[0].state is JobState.FAILED
    assert resolved.jobs[0].finished_at == NOW
    assert resolved.blocks[0].state is BlockState.RUNNING
    retried = resolved.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    assert retried.jobs[0].attempt == 2


def test_precommit_native_batch_resolution_terminally_fails_the_block() -> None:
    snapshot = PlanSnapshot(
        "rev",
        "lane",
        NOW,
        (SnapshotJob("area", "Area", (), Mode.VACUUM, 0, NOW),),
    )
    sealed = start_due_block(
        QueueLedger.empty(),
        snapshot,
        "lane",
        "today",
        NOW,
        IDs(),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    committing = begin_native_batch_commit(sealed, "id-1", NOW)
    uncertain = quarantine_block_dispatch(committing, "id-1", NOW)

    resolved = resolve_uncertain_job(uncertain, "id-2", UncertainResolution.RETRY_SAFE, NOW)

    assert resolved.jobs[0].state is JobState.FAILED
    assert resolved.blocks[0].state is BlockState.FAILED


def test_terminal_block_transition_rejects_nonterminal_children() -> None:
    ledger = ledger_with_jobs()
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)

    with pytest.raises(ValueError, match="terminal block requires terminal jobs"):
        ledger.replace_block_state("id-1", BlockState.FAILED, NOW)


def test_failed_block_requires_at_least_one_failed_job() -> None:
    ledger = ledger_with_jobs()
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.ACCEPTED, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.RUNNING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.COMPLETED, NOW)

    with pytest.raises(ValueError, match="failed block requires a failed job"):
        ledger.replace_block_state("id-1", BlockState.FAILED, NOW)


def test_retry_is_rejected_under_a_terminal_parent_block() -> None:
    ledger = ledger_with_jobs()
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("id-1", state, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
    ledger = ledger.replace_job_state("id-2", JobState.FAILED, NOW)
    ledger = ledger.replace_block_state("id-1", BlockState.FAILED, NOW)

    with pytest.raises(ValueError, match="terminal parent block"):
        ledger.replace_job_state("id-2", JobState.DISPATCHING, NOW)
