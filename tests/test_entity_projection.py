from datetime import UTC, datetime

from custom_components.vacuum_planner.const import VacuumPlannerRuntimeData
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockKind,
    BlockState,
    DispatchStrategy,
    PlannerState,
    PlanRevision,
    QueueBlock,
    QueueLedger,
)
from custom_components.vacuum_planner.entity import planner_status

NOW = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


class NullStore:
    async def async_save(self, _state: PlannerState) -> None:
        pass


def empty_state() -> PlannerState:
    return PlannerState(
        plan_revision=PlanRevision(
            revision_id="revision-1",
            created_at=NOW,
            room_plans=(),
        ),
        ledger=QueueLedger.empty(),
    )


def state_with_block(block_state: BlockState) -> PlannerState:
    state = empty_state()
    block = QueueBlock(
        block_id="block-1",
        kind=BlockKind.SCHEDULED,
        lane_id="lane-1",
        plan_revision=state.plan_revision.revision_id,
        idempotency_key="key-1",
        created_at=NOW,
        sealed_at=NOW,
        state=block_state,
        job_ids=(),
        dispatch_strategy=DispatchStrategy.NATIVE_BATCH,
        guarantee=BlockGuarantee.PLANNER_ATOMIC,
        committed_at=NOW if block_state in {BlockState.COMMITTED, BlockState.RUNNING} else None,
    )
    return PlannerState(
        plan_revision=state.plan_revision,
        ledger=QueueLedger(schema_version=1, revision=1, blocks=(block,), jobs=()),
    )


def test_planner_status_is_idle_when_queue_is_empty() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(empty_state(), NullStore()),
    )

    assert planner_status(runtime_data) == "idle"


def test_planner_status_is_paused_when_planning_is_disabled() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        planning_enabled=False,
        coordinator=PlannerCoordinator(empty_state(), NullStore()),
    )

    assert planner_status(runtime_data) == "paused"


def test_planner_status_requires_attention_for_uncertain_run() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(state_with_block(BlockState.UNCERTAIN), NullStore()),
    )

    assert planner_status(runtime_data) == "attention"


def test_planner_status_requires_attention_for_rejected_block() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(state_with_block(BlockState.REJECTED), NullStore()),
    )

    assert planner_status(runtime_data) == "attention"


def test_planner_status_is_committing_during_external_commit() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(state_with_block(BlockState.COMMITTING), NullStore()),
    )

    assert planner_status(runtime_data) == "committing"


def test_planner_status_is_running_after_device_acceptance() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(state_with_block(BlockState.COMMITTED), NullStore()),
    )

    assert planner_status(runtime_data) == "running"


def test_planner_status_remains_running_during_observed_execution() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(state_with_block(BlockState.RUNNING), NullStore()),
    )

    assert planner_status(runtime_data) == "running"


def test_planner_status_is_ready_when_a_dry_run_block_is_sealed() -> None:
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(state_with_block(BlockState.SEALED), NullStore()),
    )

    assert planner_status(runtime_data) == "ready"
