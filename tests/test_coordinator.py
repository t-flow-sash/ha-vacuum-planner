import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from custom_components.vacuum_planner.const import VacuumPlannerRuntimeData
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import PlannerState, PlanRevision, QueueLedger

NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


class RecordingStore:
    def __init__(self) -> None:
        self.saved: list[PlannerState] = []
        self.coordinator: PlannerCoordinator | None = None
        self.state_during_save: PlannerState | None = None

    async def async_save(self, state: PlannerState) -> None:
        if self.coordinator is not None:
            self.state_during_save = self.coordinator.state
        self.saved.append(state)


def planner_state() -> PlannerState:
    return PlannerState(
        plan_revision=PlanRevision(
            revision_id="revision-1",
            created_at=NOW,
            room_plans=(),
        ),
        ledger=QueueLedger.empty(),
    )


def test_command_persists_before_publishing_new_state() -> None:
    async def exercise() -> tuple[PlannerState, RecordingStore, PlannerCoordinator]:
        initial = planner_state()
        store = RecordingStore()
        coordinator = PlannerCoordinator(initial, store)
        store.coordinator = coordinator

        updated = await coordinator.async_command(
            lambda state: replace(
                state,
                ledger=replace(state.ledger, revision=state.ledger.revision + 1),
            )
        )
        assert store.state_during_save is initial
        return updated, store, coordinator

    updated, store, coordinator = asyncio.run(exercise())

    assert updated.ledger.revision == 1
    assert store.saved == [updated]
    assert coordinator.state is updated


def test_runtime_data_state_tracks_coordinator_command() -> None:
    initial = planner_state()
    coordinator = PlannerCoordinator(initial, RecordingStore())
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=coordinator,
    )

    updated = asyncio.run(
        coordinator.async_command(
            lambda state: replace(
                state,
                ledger=replace(state.ledger, revision=state.ledger.revision + 1),
            )
        )
    )

    assert runtime_data.state is updated


def test_command_notifies_listener_after_publishing_persisted_state() -> None:
    async def exercise() -> list[PlannerState]:
        initial = planner_state()
        store = RecordingStore()
        coordinator = PlannerCoordinator(initial, store)
        observed: list[PlannerState] = []
        coordinator.async_add_listener(lambda: observed.append(coordinator.state))

        updated = await coordinator.async_command(
            lambda state: replace(
                state,
                ledger=replace(state.ledger, revision=state.ledger.revision + 1),
            )
        )

        assert updated is coordinator.state
        return observed

    observed = asyncio.run(exercise())

    assert len(observed) == 1
    assert observed[0].ledger.revision == 1
