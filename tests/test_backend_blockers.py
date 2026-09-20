import asyncio
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from enum import IntFlag
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from custom_components import vacuum_planner as integration
from custom_components.vacuum_planner import integration_observer, topology
from custom_components.vacuum_planner.adapters.native_area import NativeAreaAdapter
from custom_components.vacuum_planner.const import (
    DOMAIN,
    RuntimeInactiveError,
    VacuumPlannerRuntimeData,
    invalidate_commands,
    shutdown_runtime,
)
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockState,
    DispatchStrategy,
    JobState,
    Mode,
    PlannerState,
    PlanRevision,
    PlanSnapshot,
    PreferredMode,
    QueueLedger,
    RoomPlan,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import (
    StartResult,
    StartStatus,
    UncertainResolution,
    begin_native_batch_commit,
    resolve_uncertain_job,
    start_due_block,
)

AT = datetime(2026, 9, 19, 10, tzinfo=UTC)


class NativeVacuumEntityFeature(IntFlag):
    CLEAN_AREA = 16384


def _install_valid_topology_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    const_module = ModuleType("homeassistant.const")
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=16384)
    vars(const_module)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)


@pytest.mark.parametrize("vacuum_state", ["unknown", "unavailable"])
def test_shared_topology_validator_rejects_unavailable_vacuum_with_stale_clean_area(
    monkeypatch: pytest.MonkeyPatch,
    vacuum_state: str,
) -> None:
    """Probe A: stale CLEAN_AREA attributes cannot make an unavailable vacuum valid."""
    _install_valid_topology_modules(monkeypatch)
    registry_entry = SimpleNamespace(id="registry-1", entity_id="vacuum.robot", options={})
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda _registry_id: registry_entry
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state=vacuum_state,
                attributes={"supported_features": 16384},
            )
        )
    )

    valid_entry, validation_error = topology.async_get_valid_vacuum(hass, "registry-1")

    assert valid_entry is None
    assert validation_error == "entity_not_found"


def _started_state(*, area_ids: tuple[str, ...] = ("kitchen",)) -> PlannerState:
    plan = PlanRevision(
        "revision-1",
        AT,
        tuple(
            RoomPlan(
                area_id=area_id,
                lane_id="registry-old",
                enabled=True,
                vacuum_interval_days=7,
                vacuum_and_mop_interval_days=14,
                preferred_mode=PreferredMode.VACUUM,
                priority=index,
            )
            for index, area_id in enumerate(area_ids)
        ),
    )
    ids = iter(("block-1", *(f"job-{index}" for index in range(len(area_ids)))))
    started = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot(
            plan.revision_id,
            "registry-old",
            AT,
            tuple(
                SnapshotJob(area_id, area_id.title(), (str(index),), Mode.VACUUM, index, AT)
                for index, area_id in enumerate(area_ids)
            ),
        ),
        "registry-old",
        "key",
        AT,
        lambda: next(ids),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    return PlannerState(plan, started.ledger)


def _accepted_state(*, area_ids: tuple[str, ...] = ("kitchen",)) -> PlannerState:
    state = _started_state(area_ids=area_ids)
    ledger = begin_native_batch_commit(state.ledger, "block-1", AT)
    ledger = ledger.replace_block_state("block-1", BlockState.COMMITTED, AT)
    for job in ledger.jobs:
        ledger = ledger.replace_job_state(job.job_id, JobState.ACCEPTED, AT)
    return replace(state, ledger=ledger)


def _dispatching_state() -> PlannerState:
    state = _started_state()
    return replace(state, ledger=begin_native_batch_commit(state.ledger, "block-1", AT))


def _terminal_state() -> PlannerState:
    state = _accepted_state()
    ledger = state.ledger.replace_block_state("block-1", BlockState.RUNNING, AT)
    ledger = ledger.replace_job_state("job-0", JobState.RUNNING, AT)
    ledger = ledger.replace_job_state("job-0", JobState.COMPLETED, AT)
    ledger = ledger.replace_block_state("block-1", BlockState.COMPLETED, AT)
    return replace(state, ledger=ledger)


def test_queued_command_captured_from_detached_runtime_cannot_save_or_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[str, Callable[[object], Any]] = {}
    saved: list[PlannerState] = []
    published: list[PlannerState] = []

    class StubServiceValidationError(Exception):
        pass

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[[object], Any],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    core_module = ModuleType("homeassistant.core")
    exceptions_module = ModuleType("homeassistant.exceptions")
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = StubServiceValidationError
    monkeypatch.setitem(sys.modules, "homeassistant.core", core_module)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)

    coordinator = PlannerCoordinator(_terminal_state(), Store())
    coordinator.async_add_listener(lambda: published.append(coordinator.state))
    old_runtime = VacuumPlannerRuntimeData("vacuum.old", coordinator=coordinator)
    hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="UTC"),
        data={"vacuum_planner": {"planner-entry-1": old_runtime}},
        services=Services(),
    )
    integration._register_queue_mutation_actions(hass)  # noqa: SLF001
    handler = registered["vacuum_planner.postpone_area"]
    entry = SimpleNamespace(entry_id="planner-entry-1", runtime_data=old_runtime)

    async def exercise() -> None:
        await coordinator._command_lock.acquire()  # noqa: SLF001 - deterministic stale queue
        queued = asyncio.create_task(
            handler(
                SimpleNamespace(
                    data={
                        "config_entry_id": "planner-entry-1",
                        "area_id": "kitchen",
                        "days": 1,
                    }
                )
            )
        )
        await asyncio.sleep(0)
        assert await integration.async_unload_entry(hass, entry) is True
        coordinator._command_lock.release()  # noqa: SLF001
        with pytest.raises(StubServiceValidationError, match="no longer active"):
            await queued

    asyncio.run(exercise())

    assert saved == []
    assert published == []
    assert "planner-entry-1" not in hass.data["vacuum_planner"]
    assert entry.runtime_data is None


def test_runtime_replacement_invalidates_command_waiting_on_old_runtime_lock() -> None:
    saved: list[PlannerState] = []
    published: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    old_coordinator = PlannerCoordinator(_terminal_state(), Store())
    old_coordinator.async_add_listener(lambda: published.append(old_coordinator.state))
    old_runtime = VacuumPlannerRuntimeData("vacuum.old", coordinator=old_coordinator)
    generation = old_runtime.capture_command_generation()
    replacement = VacuumPlannerRuntimeData(
        "vacuum.new", coordinator=PlannerCoordinator(_terminal_state(), Store())
    )
    routed = {"entry": old_runtime}

    async def exercise() -> None:
        await old_coordinator._command_lock.acquire()  # noqa: SLF001
        queued = asyncio.create_task(
            old_coordinator.async_command(
                lambda state: replace(state, ledger=replace(state.ledger, revision=99)),
                guard=lambda: old_runtime.require_command_generation(generation),
            )
        )
        await asyncio.sleep(0)
        invalidate_commands(old_runtime)
        routed["entry"] = replacement
        old_coordinator._command_lock.release()  # noqa: SLF001
        with pytest.raises(RuntimeInactiveError, match="no longer active"):
            await queued

    asyncio.run(exercise())

    assert saved == []
    assert published == []
    assert routed["entry"] is replacement


def test_runtime_invalidation_between_external_calls_blocks_second_side_effect() -> None:
    calls: list[tuple[str, str]] = []
    runtime = VacuumPlannerRuntimeData("vacuum.old")
    generation = runtime.capture_command_generation()

    class Services:
        async def async_call(
            self, domain: str, service: str, *_args: object, **_kwargs: object
        ) -> None:
            calls.append((domain, service))
            if domain == "select":
                invalidate_commands(runtime)

    adapter = NativeAreaAdapter(
        SimpleNamespace(services=Services()),
        "vacuum.old",
        cleaning_mode_entity_id="select.cleaning_mode",
        before_side_effect=lambda: runtime.require_command_generation(generation),
    )

    with pytest.raises(RuntimeInactiveError, match="no longer active"):
        asyncio.run(
            adapter.async_dispatch_after_preflight(
                ("kitchen",), object(), mode_option="Sweeping and mopping"
            )
        )

    assert calls == [("select", "select_option")]


def test_topology_latch_during_external_dispatch_durably_quarantines_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.old")
    exceptions_module = ModuleType("homeassistant.exceptions")
    vacuum_module = ModuleType("homeassistant.components.vacuum")

    class StubServiceValidationError(Exception):
        pass

    vars(exceptions_module)["ServiceValidationError"] = StubServiceValidationError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=16384)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)

    initial = _started_state()
    block = initial.ledger.blocks[0]
    jobs = tuple(job for job in initial.ledger.jobs if job.block_id == block.block_id)
    result = StartResult(StartStatus.CREATED, initial.ledger, block, jobs)
    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData("vacuum.old", dry_run=False, coordinator=coordinator)

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            runtime.topology_ready = False

    with pytest.raises(
        StubServiceValidationError,
        match="Native area dispatch acceptance could not be persisted",
    ):
        asyncio.run(
            integration._async_dispatch_created_block(  # noqa: SLF001
                SimpleNamespace(
                    services=Services(),
                    states=SimpleNamespace(
                        get=lambda _entity_id: SimpleNamespace(
                            state="idle", attributes={"supported_features": 16384}
                        )
                    ),
                ),
                runtime,
                result,
                object(),
                clock=lambda: AT,
            )
        )

    assert [state.ledger.blocks[0].state for state in saved] == [
        BlockState.COMMITTING,
        BlockState.UNCERTAIN,
    ]
    assert coordinator.state == saved[-1]
    assert coordinator.state.ledger.jobs[0].state is JobState.UNCERTAIN


def test_dispatch_rejects_compatible_replacement_for_bound_cleaning_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe E: dispatch must not adopt a different compatible selector registry ID."""
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.old")
    monkeypatch.setattr(
        integration,
        "find_dreame_mova_cleaning_mode_entity",
        lambda *_args: "select.replacement_cleaning_mode",
    )
    exceptions_module = ModuleType("homeassistant.exceptions")
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    replacement_entry = SimpleNamespace(
        id="mode-registry-2",
        entity_id="select.replacement_cleaning_mode",
        domain="select",
        unique_id="replacement_cleaning_mode",
        disabled=False,
        disabled_by=None,
    )
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda identity: (
            replacement_entry
            if identity in {"mode-registry-2", "select.replacement_cleaning_mode"}
            else None
        )
    )
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=16384)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)

    state = _started_state()
    mop_job = replace(state.ledger.jobs[0], mode=Mode.VACUUM_AND_MOP)
    ledger = replace(state.ledger, jobs=(mop_job,))
    state = replace(state, ledger=ledger)
    result = StartResult(StartStatus.CREATED, ledger, ledger.blocks[0], (mop_job,))
    service_calls: list[tuple[str, str]] = []

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    class Services:
        async def async_call(
            self, domain: str, service: str, *_args: object, **_kwargs: object
        ) -> None:
            service_calls.append((domain, service))

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        dry_run=False,
        coordinator=PlannerCoordinator(state, Store()),
        vacuum_registry_id="vacuum-registry-1",
        cleaning_mode_entity_id="select.original_cleaning_mode",
        cleaning_mode_registry_id="mode-registry-1",
        requires_vacuum_and_mop=True,
        config_entry_id="planner-entry-1",
    )
    states = {
        "vacuum.old": SimpleNamespace(state="idle", attributes={"supported_features": 16384}),
        "select.replacement_cleaning_mode": SimpleNamespace(
            state="Vacuum", attributes={"options": ["Vacuum", "Vacuum and Mop"]}
        ),
    }
    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(get=lambda entity_id: states.get(entity_id)),
    )

    with pytest.raises(ValueError, match="cleaning mode"):
        asyncio.run(integration._async_dispatch_created_block(hass, runtime, result, object()))  # noqa: SLF001

    assert runtime.topology_ready is False
    assert service_calls == []


def test_bound_cleaning_mode_registry_rename_resolves_current_entity_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mode_entry = SimpleNamespace(
        id="mode-registry-1",
        entity_id="select.renamed_cleaning_mode",
        domain="select",
        unique_id="device_cleaning_mode",
        disabled=False,
        disabled_by=None,
    )
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda identity: mode_entry if identity == "mode-registry-1" else None
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda entity_id: (
                SimpleNamespace(
                    state="Vacuum",
                    attributes={"options": ["Vacuum", "Vacuum and Mop"]},
                )
                if entity_id == "select.renamed_cleaning_mode"
                else None
            )
        )
    )
    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        cleaning_mode_entity_id="select.old_cleaning_mode",
        cleaning_mode_registry_id="mode-registry-1",
        requires_vacuum_and_mop=True,
    )

    assert (
        integration._resolve_command_cleaning_mode(hass, runtime)  # noqa: SLF001
        == "select.renamed_cleaning_mode"
    )
    assert runtime.topology_ready is True


@pytest.mark.parametrize("transition", ["removal", "disable", "replacement"])
def test_bound_cleaning_mode_identity_loss_latches_without_adoption(
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    original = SimpleNamespace(
        id="mode-registry-1",
        entity_id="select.original_cleaning_mode",
        domain="select",
        unique_id="device_cleaning_mode",
        disabled=transition == "disable",
        disabled_by="user" if transition == "disable" else None,
    )
    replacement = SimpleNamespace(
        id="mode-registry-2",
        entity_id="select.replacement_cleaning_mode",
        domain="select",
        unique_id="replacement_cleaning_mode",
        disabled=False,
        disabled_by=None,
    )
    entries = [original] if transition == "disable" else []
    if transition == "replacement":
        entries.append(replacement)
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda identity: next(
            (entry for entry in entries if identity in {entry.id, entry.entity_id}),
            None,
        )
    )
    exceptions_module = ModuleType("homeassistant.exceptions")
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)
    states = {
        entry.entity_id: SimpleNamespace(
            state="Vacuum",
            attributes={"options": ["Vacuum", "Vacuum and Mop"]},
        )
        for entry in entries
    }
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: states.get(entity_id)))
    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        cleaning_mode_entity_id="select.original_cleaning_mode",
        cleaning_mode_registry_id="mode-registry-1",
        requires_vacuum_and_mop=True,
    )

    with pytest.raises(ValueError, match="cleaning mode"):
        integration._resolve_command_cleaning_mode(hass, runtime)  # noqa: SLF001

    assert runtime.topology_ready is False


@pytest.mark.parametrize("transition", ["removal", "disable", "mismatch"])
def test_command_time_vacuum_identity_loss_latches_and_blocks_sealed_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    """Command-time registry loss must latch before a sealed block can be dispatched."""
    bound_entry = SimpleNamespace(
        id="vacuum-registry-1",
        entity_id="vacuum.original",
        domain="vacuum",
        disabled=transition == "disable",
        disabled_by="user" if transition == "disable" else None,
    )
    mismatched_entry = SimpleNamespace(
        id="vacuum-registry-2",
        entity_id="vacuum.replacement",
        domain="vacuum",
        disabled=False,
        disabled_by=None,
    )
    current_entry: object | None = {
        "removal": None,
        "disable": bound_entry,
        "mismatch": mismatched_entry,
    }[transition]
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    event_module = ModuleType("homeassistant.helpers.event")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda identity: current_entry if identity == "vacuum-registry-1" else None
    )
    vars(event_module)["async_track_state_change_event"] = lambda *_args, **_kwargs: lambda: None
    repairs: list[str] = []
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: repairs.append(issue_id),
        async_delete_issue=lambda *_args: None,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)
    exceptions_module = ModuleType("homeassistant.exceptions")
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=16384)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)

    service_calls: list[tuple[str, str]] = []

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    class Services:
        async def async_call(
            self, domain: str, service: str, *_args: object, **_kwargs: object
        ) -> None:
            service_calls.append((domain, service))

    state = _started_state()
    result = StartResult(
        StartStatus.CREATED,
        state.ledger,
        state.ledger.blocks[0],
        state.ledger.jobs,
    )
    runtime = VacuumPlannerRuntimeData(
        "vacuum.original",
        dry_run=False,
        coordinator=PlannerCoordinator(state, Store()),
        vacuum_registry_id="vacuum-registry-1",
        config_entry_id="planner-entry-1",
    )
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_listen=lambda *_args: lambda: None),
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 16384}
            )
        ),
    )
    integration._subscribe_observer(hass, runtime)  # noqa: SLF001

    with pytest.raises(ValueError, match="vacuum"):
        asyncio.run(integration._async_dispatch_created_block(hass, runtime, result, object()))  # noqa: SLF001

    assert runtime.topology_ready is False
    assert runtime.observation_active is False
    assert repairs == ["planner-entry-1_missing_registry"]
    assert service_calls == []
    assert runtime.state is not None
    assert runtime.state.ledger.blocks[0].state is BlockState.SEALED
    assert runtime.state.ledger.jobs[0].state is JobState.PENDING

    current_entry = SimpleNamespace(
        id="vacuum-registry-1",
        entity_id="vacuum.original",
        domain="vacuum",
        disabled=False,
        disabled_by=None,
    )
    with pytest.raises(RuntimeInactiveError, match="topology is not ready"):
        asyncio.run(integration._async_dispatch_created_block(hass, runtime, result, object()))  # noqa: SLF001

    assert repairs == ["planner-entry-1_missing_registry"]
    assert service_calls == []
    assert runtime.state.ledger.blocks[0].state is BlockState.SEALED
    assert runtime.state.ledger.jobs[0].state is JobState.PENDING


def test_command_time_vacuum_registry_rename_keeps_bound_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_entry = SimpleNamespace(
        id="vacuum-registry-1",
        entity_id="vacuum.renamed",
        domain="vacuum",
        disabled=False,
        disabled_by=None,
    )
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda identity: registry_entry if identity == "vacuum-registry-1" else None
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    runtime = VacuumPlannerRuntimeData(
        "vacuum.original",
        vacuum_registry_id="vacuum-registry-1",
    )

    assert integration._resolve_command_vacuum(SimpleNamespace(), runtime) == "vacuum.renamed"  # noqa: SLF001
    assert runtime.topology_ready is True


def test_observer_running_then_completed_advances_every_plan_and_saves() -> None:
    initial = _accepted_state(area_ids=("kitchen", "hallway"))
    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData("vacuum.old", coordinator=coordinator)

    asyncio.run(integration_observer.async_apply_observation(runtime, "cleaning", {}, AT))
    asyncio.run(integration_observer.async_apply_observation(runtime, "idle", {}, AT))

    assert len(saved) == 2
    assert saved[-1].ledger.blocks[0].state is BlockState.COMPLETED
    assert {job.state for job in saved[-1].ledger.jobs} == {JobState.COMPLETED}
    assert all(plan.last_completed_vacuum_at == AT for plan in saved[-1].plan_revision.room_plans)


@pytest.mark.parametrize(
    ("vacuum_state", "expected_block", "expected_job"),
    [
        ("cleaning", BlockState.RUNNING, JobState.RUNNING),
        ("error", BlockState.FAILED, JobState.FAILED),
        ("unavailable", BlockState.UNCERTAIN, JobState.UNCERTAIN),
    ],
)
def test_dispatch_observation_survives_later_acceptance(
    vacuum_state: str,
    expected_block: BlockState,
    expected_job: JobState,
) -> None:
    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    coordinator = PlannerCoordinator(_dispatching_state(), Store())
    runtime = VacuumPlannerRuntimeData("vacuum.old", coordinator=coordinator)

    asyncio.run(integration_observer.async_apply_observation(runtime, vacuum_state, {}, AT))
    observed = coordinator.state
    accepted = integration._record_dispatch_acceptance(  # noqa: SLF001
        observed,
        "block-1",
        observed.ledger.jobs,
        AT,
    )

    assert accepted.ledger.blocks[0].state is expected_block
    assert accepted.ledger.jobs[0].state is expected_job


def test_running_observed_during_dispatch_is_a_positive_completion_witness() -> None:
    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    coordinator = PlannerCoordinator(_dispatching_state(), Store())
    runtime = VacuumPlannerRuntimeData("vacuum.old", coordinator=coordinator)

    asyncio.run(integration_observer.async_apply_observation(runtime, "cleaning", {}, AT))
    asyncio.run(integration_observer.async_apply_observation(runtime, "docked", {}, AT))

    assert coordinator.state.ledger.blocks[0].state is BlockState.COMPLETED
    assert coordinator.state.ledger.jobs[0].state is JobState.COMPLETED
    assert len(saved) == 2


@pytest.mark.parametrize("detail", ["washing", "drying", "returning", "docking"])
def test_observer_intermediate_states_never_complete(detail: str) -> None:
    initial = _accepted_state()
    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old", coordinator=PlannerCoordinator(initial, Store())
    )
    asyncio.run(
        integration_observer.async_apply_observation(runtime, "idle", {"status": detail}, AT)
    )

    assert saved == []
    assert runtime.state is initial


def test_observer_idle_without_witnessed_running_does_not_complete() -> None:
    initial = _accepted_state()
    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old", coordinator=PlannerCoordinator(initial, Store())
    )
    asyncio.run(integration_observer.async_apply_observation(runtime, "idle", {}, AT))

    assert saved == []
    assert runtime.state is initial


@pytest.mark.parametrize("state", ["paused", "returning"])
def test_observer_paused_or_returning_after_running_never_completes(state: str) -> None:
    initial = _accepted_state()
    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, candidate: PlannerState) -> None:
            saved.append(candidate)

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old", coordinator=PlannerCoordinator(initial, Store())
    )
    asyncio.run(integration_observer.async_apply_observation(runtime, "cleaning", {}, AT))
    asyncio.run(integration_observer.async_apply_observation(runtime, state, {}, AT))

    assert runtime.state is not None
    assert runtime.state.ledger.jobs[0].state is JobState.RUNNING
    assert runtime.state.ledger.blocks[0].state is BlockState.RUNNING
    assert runtime.state.ledger.jobs[0].finished_at is None


def test_observer_unknown_after_running_quarantines_instead_of_completing() -> None:
    initial = _accepted_state()

    class Store:
        async def async_save(self, _candidate: PlannerState) -> None:
            pass

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old", coordinator=PlannerCoordinator(initial, Store())
    )
    asyncio.run(integration_observer.async_apply_observation(runtime, "cleaning", {}, AT))
    asyncio.run(integration_observer.async_apply_observation(runtime, "new_vendor_state", {}, AT))

    assert runtime.state is not None
    assert runtime.state.ledger.jobs[0].state is JobState.UNCERTAIN
    assert runtime.state.ledger.blocks[0].state is BlockState.UNCERTAIN
    assert runtime.state.ledger.jobs[0].finished_at is None


def test_listener_subscription_is_removed_on_successful_unload() -> None:
    unsubscribed: list[bool] = []
    runtime = VacuumPlannerRuntimeData(
        "vacuum.old", observer_unsubscribe=lambda: unsubscribed.append(True)
    )
    entry = SimpleNamespace(entry_id=None, runtime_data=runtime)

    assert asyncio.run(integration.async_unload_entry(SimpleNamespace(), entry)) is True
    assert unsubscribed == [True]


@pytest.mark.parametrize(
    "supported_features",
    [NativeVacuumEntityFeature(31676), NativeVacuumEntityFeature(30524)],
)
def test_observer_subscribes_to_the_runtime_entity_and_schedules_state_events(
    monkeypatch: pytest.MonkeyPatch,
    supported_features: NativeVacuumEntityFeature,
) -> None:
    callbacks: list[tuple[tuple[str, ...], object]] = []
    removed: list[bool] = []

    def track(_hass: object, entity_ids: list[str], callback: object) -> object:
        callbacks.append((tuple(entity_ids), callback))
        return lambda: removed.append(True)

    event_module = __import__("types").ModuleType("homeassistant.helpers.event")
    vars(event_module)["async_track_state_change_event"] = track
    monkeypatch.setitem(__import__("sys").modules, "homeassistant.helpers.event", event_module)
    tasks: list[Any] = []
    runtime = VacuumPlannerRuntimeData("vacuum.current")
    hass = SimpleNamespace(async_create_task=lambda task: tasks.append(task))

    integration._subscribe_observer(hass, runtime)  # noqa: SLF001

    assert callbacks[0][0] == ("vacuum.current",)
    event_callback = callbacks[0][1]
    assert callable(event_callback)
    event_callback(
        SimpleNamespace(
            data={
                "new_state": SimpleNamespace(
                    state="cleaning",
                    attributes={"supported_features": supported_features},
                ),
            },
            time_fired=AT,
        )
    )
    assert runtime.topology_ready is True
    assert len(tasks) == 1
    tasks[0].close()
    assert runtime.observer_unsubscribe is not None
    runtime.observer_unsubscribe()
    assert removed == [True]


def test_observer_subscription_partial_failure_removes_state_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[str] = []
    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    vars(event_module)["async_track_state_change_event"] = (
        lambda *_args, **_kwargs: lambda: removed.append("state")
    )
    vars(registry_module)["EVENT_ENTITY_REGISTRY_UPDATED"] = "entity_registry_updated"
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    runtime = VacuumPlannerRuntimeData("vacuum.old", vacuum_registry_id="registry-1")
    hass = SimpleNamespace(
        bus=SimpleNamespace(
            async_listen=lambda *_args: (_ for _ in ()).throw(RuntimeError("listen failed"))
        )
    )

    with pytest.raises(RuntimeError, match="listen failed"):
        integration._subscribe_observer(hass, runtime)  # noqa: SLF001

    assert removed == ["state"]
    assert runtime.observer_unsubscribe is None
    assert runtime.observation_active is False


def test_observer_unsubscribe_aggregates_nested_listener_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")

    def failing_unsubscribe(name: str) -> Callable[[], None]:
        def unsubscribe() -> None:
            calls.append(name)
            raise RuntimeError(f"{name} cleanup failed")

        return unsubscribe

    vars(event_module)["async_track_state_change_event"] = (
        lambda *_args, **_kwargs: failing_unsubscribe("state")
    )
    vars(registry_module)["EVENT_ENTITY_REGISTRY_UPDATED"] = "entity_registry_updated"
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    runtime = VacuumPlannerRuntimeData("vacuum.old", vacuum_registry_id="registry-1")
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_listen=lambda *_args: failing_unsubscribe("registry"))
    )

    integration._subscribe_observer(hass, runtime)  # noqa: SLF001
    assert runtime.observer_unsubscribe is not None
    with pytest.raises(ExceptionGroup) as raised:
        runtime.observer_unsubscribe()

    assert calls == ["state", "registry"]
    assert [str(error) for error in raised.value.exceptions] == [
        "state cleanup failed",
        "registry cleanup failed",
    ]
    assert runtime.observer_unsubscribe is not None
    runtime.observer_unsubscribe()
    assert calls == ["state", "registry"]


def test_shutdown_runtime_attempts_all_cleanup_and_clears_handles_after_failure() -> None:
    calls: list[str] = []

    def observer_unsubscribe() -> None:
        calls.append("observer")
        raise RuntimeError("observer cleanup failed")

    runtime = VacuumPlannerRuntimeData("vacuum.old")
    runtime.observation_active = True
    runtime.observer_unsubscribe = observer_unsubscribe
    runtime.repair_unsubscribe = lambda: calls.append("repair")

    with pytest.raises(RuntimeError, match="observer cleanup failed"):
        shutdown_runtime(runtime)

    assert calls == ["observer", "repair"]
    assert runtime.observer_unsubscribe is None
    assert runtime.repair_unsubscribe is None
    assert runtime.command_active is False
    assert runtime.observation_active is False

    shutdown_runtime(runtime)
    assert calls == ["observer", "repair"]


def test_shutdown_runtime_aggregates_multiple_cleanup_failures() -> None:
    calls: list[str] = []

    def fail(name: str) -> Callable[[], None]:
        def unsubscribe() -> None:
            calls.append(name)
            raise RuntimeError(f"{name} cleanup failed")

        return unsubscribe

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        observer_unsubscribe=fail("observer"),
        repair_unsubscribe=fail("repair"),
    )

    with pytest.raises(ExceptionGroup) as raised:
        shutdown_runtime(runtime)

    assert calls == ["observer", "repair"]
    assert [str(error) for error in raised.value.exceptions] == [
        "observer cleanup failed",
        "repair cleanup failed",
    ]


def test_setup_rollback_unpublishes_runtime_after_unsubscribe_failure() -> None:
    calls: list[str] = []

    def observer_unsubscribe() -> None:
        calls.append("observer")
        raise RuntimeError("observer cleanup failed")

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        observer_unsubscribe=observer_unsubscribe,
        repair_unsubscribe=lambda: calls.append("repair"),
    )
    entry = SimpleNamespace(entry_id="planner-entry-1", runtime_data=runtime)
    hass = SimpleNamespace(data={DOMAIN: {entry.entry_id: runtime}})

    with pytest.raises(RuntimeError, match="observer cleanup failed"):
        integration._rollback_setup_runtime(hass, entry, runtime)  # noqa: SLF001

    assert calls == ["observer", "repair"]
    assert entry.entry_id not in hass.data[DOMAIN]
    assert entry.runtime_data is None


def test_successful_platform_unload_unpublishes_runtime_after_unsubscribe_failure() -> None:
    calls: list[str] = []

    class ConfigEntries:
        async def async_unload_platforms(self, _entry: object, _platforms: tuple[str, ...]) -> bool:
            calls.append("platforms")
            return True

    def observer_unsubscribe() -> None:
        calls.append("observer")
        raise RuntimeError("observer cleanup failed")

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        observer_unsubscribe=observer_unsubscribe,
        repair_unsubscribe=lambda: calls.append("repair"),
    )
    entry = SimpleNamespace(entry_id="planner-entry-1", runtime_data=runtime)
    hass = SimpleNamespace(
        config_entries=ConfigEntries(),
        data={DOMAIN: {entry.entry_id: runtime}},
    )

    with pytest.raises(RuntimeError, match="observer cleanup failed"):
        asyncio.run(integration.async_unload_entry(hass, entry))

    assert calls == ["platforms", "observer", "repair"]
    assert entry.entry_id not in hass.data[DOMAIN]
    assert entry.runtime_data is None


def test_setup_failure_aggregates_original_and_rollback_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            del state

    async def initialize(*_args: object) -> tuple[object, PlannerCoordinator]:
        return object(), PlannerCoordinator(_terminal_state(), Store())

    monkeypatch.setattr(integration, "_resolve_configured_vacuum", lambda *_args: "vacuum.old")
    monkeypatch.setattr(integration, "_async_initialize_planner", initialize)
    monkeypatch.setattr(integration, "_optional_area_names", lambda *_args: None)

    def subscribe_repairs(_hass: object, runtime: VacuumPlannerRuntimeData) -> None:
        runtime.repair_unsubscribe = lambda: calls.append("repair")

    def subscribe_observer(_hass: object, runtime: VacuumPlannerRuntimeData) -> None:
        def unsubscribe() -> None:
            calls.append("observer")
            raise RuntimeError("observer cleanup failed")

        runtime.observer_unsubscribe = unsubscribe

    monkeypatch.setattr(integration, "_subscribe_repairs", subscribe_repairs)
    monkeypatch.setattr(integration, "_subscribe_observer", subscribe_observer)

    class ConfigEntries:
        async def async_forward_entry_setups(self, *_args: object) -> None:
            raise RuntimeError("platform setup failed")

    hass = SimpleNamespace(
        data={DOMAIN: {}},
        services=object(),
        config_entries=ConfigEntries(),
        async_create_task=lambda task: task,
    )
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={"vacuum_entity_id": "vacuum.old", "area_ids": []},
        options={},
        unique_id="registry-1",
        runtime_data=None,
    )

    with pytest.raises(ExceptionGroup) as raised:
        asyncio.run(integration.async_setup_entry(hass, entry))

    assert [str(error) for error in raised.value.exceptions] == [
        "platform setup failed",
        "observer cleanup failed",
    ]
    assert calls == ["observer", "repair"]
    assert entry.entry_id not in hass.data[DOMAIN]
    assert entry.runtime_data is None


@pytest.mark.parametrize("failure", ["observer", "platform"])
def test_setup_failure_rolls_back_all_published_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    removed: list[str] = []
    runtimes: list[VacuumPlannerRuntimeData] = []

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    coordinator = PlannerCoordinator(_terminal_state(), Store())

    async def initialize(*_args: object) -> tuple[object, PlannerCoordinator]:
        return object(), coordinator

    monkeypatch.setattr(integration, "_resolve_configured_vacuum", lambda *_args: "vacuum.old")
    monkeypatch.setattr(integration, "_async_initialize_planner", initialize)
    monkeypatch.setattr(integration, "_optional_area_names", lambda *_args: None)

    def subscribe_repairs(_hass: object, runtime: VacuumPlannerRuntimeData) -> None:
        runtimes.append(runtime)
        runtime.repair_unsubscribe = lambda: removed.append("repair")

    def subscribe_observer(_hass: object, runtime: VacuumPlannerRuntimeData) -> None:
        runtime.observer_unsubscribe = lambda: removed.append("observer")
        runtime.observation_active = True
        if failure == "observer":
            raise RuntimeError("observer failed")

    monkeypatch.setattr(integration, "_subscribe_repairs", subscribe_repairs)
    monkeypatch.setattr(integration, "_subscribe_observer", subscribe_observer)

    class ConfigEntries:
        async def async_forward_entry_setups(self, *_args: object) -> None:
            if failure == "platform":
                raise RuntimeError("platform failed")

    hass = SimpleNamespace(
        data={DOMAIN: {}},
        services=object(),
        config_entries=ConfigEntries(),
        async_create_task=lambda task: task,
    )
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={"vacuum_entity_id": "vacuum.old", "area_ids": []},
        options={},
        unique_id="registry-1",
        runtime_data=None,
    )

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        asyncio.run(integration.async_setup_entry(hass, entry))

    runtime = runtimes[0]
    assert entry.runtime_data is None
    assert "planner-entry-1" not in hass.data[DOMAIN]
    assert set(removed) == {"repair", "observer"}
    assert runtime.command_active is False
    assert runtime.observation_active is False


def test_registry_rename_latches_observer_fail_closed_until_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    tracked: list[tuple[tuple[str, ...], object]] = []
    removed: list[tuple[str, ...]] = []
    registry_listeners: list[Callable[[object], None]] = []
    registry_listener_removed: list[bool] = []
    registry_entry = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )

    def track(_hass: object, entity_ids: list[str], callback: object) -> object:
        key = tuple(entity_ids)
        tracked.append((key, callback))
        return lambda: removed.append(key)

    event_module = __import__("types").ModuleType("homeassistant.helpers.event")
    registry_module = __import__("types").ModuleType("homeassistant.helpers.entity_registry")
    vars(event_module)["async_track_state_change_event"] = track
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda registry_id: registry_entry if registry_id == "registry-1" else None
    )
    monkeypatch.setitem(__import__("sys").modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(
        __import__("sys").modules, "homeassistant.helpers.entity_registry", registry_module
    )

    def listen(_event_type: str, callback: Callable[[object], None]) -> object:
        registry_listeners.append(callback)
        return lambda: registry_listener_removed.append(True)

    tasks: list[asyncio.Task[object]] = []
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_listen=listen),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 16384}
            )
        ),
        async_create_task=lambda coroutine: tasks.append(asyncio.create_task(coroutine)),
    )

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        coordinator=PlannerCoordinator(_accepted_state(), Store()),
        vacuum_registry_id="registry-1",
        configured_area_ids=("kitchen",),
    )
    publications: list[bool] = []
    assert runtime.coordinator is not None
    runtime.coordinator.async_add_listener(lambda: publications.append(runtime.topology_ready))

    async def exercise() -> None:
        integration._subscribe_observer(hass, runtime)  # noqa: SLF001
        registry_entry.entity_id = "vacuum.renamed"
        registry_listeners[0](SimpleNamespace(data={"action": "update"}))
        await asyncio.gather(*tasks)

    asyncio.run(exercise())

    assert [item[0] for item in tracked] == [("vacuum.old",)]
    assert removed == [("vacuum.old",)]
    assert runtime.vacuum_entity_id == "vacuum.old"
    assert runtime.topology_ready is False
    assert runtime.observation_active is False
    assert publications == [False, False]

    assert runtime.observer_unsubscribe is not None
    runtime.observer_unsubscribe()
    runtime.observer_unsubscribe()

    assert removed == [("vacuum.old",)]
    assert registry_listener_removed == [True]


@pytest.mark.parametrize("transition", ["rename", "removal", "unload"])
def test_queued_observation_is_discarded_after_binding_invalidation(
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    tracked: list[tuple[tuple[str, ...], Callable[[object], None]]] = []
    registry_listeners: list[Callable[[object], None]] = []
    registry_entry: object | None = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )

    def track(
        _hass: object, entity_ids: list[str], callback: Callable[[object], None]
    ) -> Callable[[], None]:
        tracked.append((tuple(entity_ids), callback))
        return lambda: None

    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    vars(event_module)["async_track_state_change_event"] = track
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda registry_id: registry_entry if registry_id == "registry-1" else None
    )
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda *_args, **_kwargs: None,
        async_delete_issue=lambda *_args: None,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    def listen(_event_type: str, callback: Callable[[object], None]) -> Callable[[], None]:
        registry_listeners.append(callback)
        return lambda: None

    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    async def exercise() -> None:
        nonlocal registry_entry
        runtime = VacuumPlannerRuntimeData(
            "vacuum.old",
            coordinator=PlannerCoordinator(_accepted_state(), Store()),
            vacuum_registry_id="registry-1",
            config_entry_id="planner-entry-1",
        )
        tasks: list[asyncio.Task[object]] = []
        hass = SimpleNamespace(
            bus=SimpleNamespace(async_listen=listen),
            states=SimpleNamespace(
                get=lambda _entity_id: SimpleNamespace(
                    state="idle", attributes={"supported_features": 16384}
                )
            ),
            async_create_task=lambda coroutine: tasks.append(asyncio.create_task(coroutine)),
        )
        integration._subscribe_observer(hass, runtime)  # noqa: SLF001
        coordinator = runtime.coordinator
        assert coordinator is not None
        await coordinator._command_lock.acquire()  # noqa: SLF001 - deterministic queue ordering
        tracked[0][1](
            SimpleNamespace(
                data={"new_state": SimpleNamespace(state="cleaning", attributes={})},
                time_fired=AT,
            )
        )
        await asyncio.sleep(0)

        if transition == "rename":
            assert registry_entry is not None
            cast("Any", registry_entry).entity_id = "vacuum.renamed"
            registry_listeners[0](SimpleNamespace(data={"action": "update"}))
        elif transition == "removal":
            registry_entry = None
            registry_listeners[0](SimpleNamespace(data={"action": "remove"}))
        else:
            assert runtime.observer_unsubscribe is not None
            runtime.observer_unsubscribe()

        coordinator._command_lock.release()  # noqa: SLF001
        await asyncio.gather(*tasks)
        assert runtime.state is not None
        expected_state = JobState.ACCEPTED if transition == "unload" else JobState.UNCERTAIN
        assert runtime.state.ledger.jobs[0].state is expected_state

    asyncio.run(exercise())
    expected_saves = 0 if transition == "unload" else 1
    assert len(saved) == expected_saves


def test_registry_restoration_does_not_recover_latched_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    order: list[str] = []
    tracked: list[tuple[str, Callable[[object], None]]] = []
    registry_listeners: list[Callable[[object], None]] = []
    registry_entry: object | None = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )

    def track(
        _hass: object, entity_ids: list[str], callback: Callable[[object], None]
    ) -> Callable[[], None]:
        order.append(f"bind:{entity_ids[0]}")
        tracked.append((entity_ids[0], callback))
        return lambda: order.append(f"unbind:{entity_ids[0]}")

    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    vars(event_module)["async_track_state_change_event"] = track
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda registry_id: registry_entry if registry_id == "registry-1" else None
    )
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda *_args, **_kwargs: order.append("repair:create"),
        async_delete_issue=lambda *_args: order.append("repair:delete"),
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    def listen(_event_type: str, callback: Callable[[object], None]) -> Callable[[], None]:
        registry_listeners.append(callback)
        return lambda: None

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        vacuum_registry_id="registry-1",
        config_entry_id="planner-entry-1",
        configured_area_ids=("kitchen",),
    )
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_listen=listen),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 16384}
            )
        ),
        async_create_task=lambda coroutine: coroutine.close(),
    )
    integration._subscribe_observer(hass, runtime)  # noqa: SLF001
    registry_entry = None
    registry_listeners[0](SimpleNamespace(data={"action": "remove"}))
    registry_entry = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )
    registry_listeners[0](SimpleNamespace(data={"action": "create"}))

    assert [entity_id for entity_id, _callback in tracked] == ["vacuum.old"]
    assert runtime.topology_ready is False
    assert "repair:create" in order
    assert "repair:delete" not in order


@pytest.mark.parametrize("vacuum_state", ["unknown", "unavailable"])
def test_active_run_vacuum_loss_latches_then_durably_marks_uncertain(
    monkeypatch: pytest.MonkeyPatch,
    vacuum_state: str,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    tracked: list[Callable[[object], None]] = []
    events: list[str] = []
    tasks: list[asyncio.Task[object]] = []

    event_module = ModuleType("homeassistant.helpers.event")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")

    def track(
        _hass: object, _entity_ids: list[str], callback: Callable[[object], None]
    ) -> Callable[[], None]:
        tracked.append(callback)
        return lambda: None

    vars(event_module)["async_track_state_change_event"] = track
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: events.append(
            f"repair:{issue_id}"
        ),
        async_delete_issue=lambda *_args: None,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            assert state.ledger.jobs[0].state is JobState.UNCERTAIN
            events.append("save:uncertain")

    async def exercise() -> VacuumPlannerRuntimeData:
        runtime = VacuumPlannerRuntimeData(
            "vacuum.old",
            coordinator=PlannerCoordinator(_accepted_state(), Store()),
            vacuum_registry_id="registry-1",
            config_entry_id="planner-entry-1",
            configured_area_ids=("kitchen",),
        )
        hass = SimpleNamespace(
            states=SimpleNamespace(
                get=lambda _entity_id: SimpleNamespace(
                    state="idle", attributes={"supported_features": 16384}
                )
            ),
            async_create_task=lambda coroutine: tasks.append(asyncio.create_task(coroutine)),
        )
        integration._subscribe_repairs(hass, runtime)  # noqa: SLF001
        integration._subscribe_observer(hass, runtime)  # noqa: SLF001
        tracked[0](
            SimpleNamespace(
                data={"new_state": SimpleNamespace(state=vacuum_state, attributes={})},
                time_fired=AT,
            )
        )
        await asyncio.gather(*tasks)
        return runtime

    runtime = asyncio.run(exercise())

    assert runtime.state is not None
    assert runtime.state.ledger.blocks[0].state is BlockState.UNCERTAIN
    assert runtime.state.ledger.jobs[0].state is JobState.UNCERTAIN
    assert runtime.topology_ready is False
    assert runtime.observation_active is False
    assert events == [
        "repair:planner-entry-1_missing_registry",
        "save:uncertain",
        "repair:planner-entry-1_unresolved_external_run",
    ]


@pytest.mark.parametrize("vacuum_state", ["unknown", "unavailable"])
def test_vacuum_loss_save_failure_still_latches_runtime_without_durable_repair(
    monkeypatch: pytest.MonkeyPatch,
    vacuum_state: str,
) -> None:
    tracked: list[Callable[[object], None]] = []
    removed: list[bool] = []
    issues: set[str] = set()
    tasks: list[asyncio.Task[object]] = []

    event_module = ModuleType("homeassistant.helpers.event")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")

    def track(
        _hass: object, _entity_ids: list[str], callback: Callable[[object], None]
    ) -> Callable[[], None]:
        tracked.append(callback)
        return lambda: removed.append(True)

    vars(event_module)["async_track_state_change_event"] = track
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: issues.add(issue_id),
        async_delete_issue=lambda _hass, _domain, issue_id: issues.discard(issue_id),
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            raise OSError("durability failed")

    async def exercise() -> VacuumPlannerRuntimeData:
        runtime = VacuumPlannerRuntimeData(
            "vacuum.old",
            coordinator=PlannerCoordinator(_accepted_state(), Store()),
            config_entry_id="planner-entry-1",
        )
        hass = SimpleNamespace(
            async_create_task=lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        )
        integration._subscribe_repairs(hass, runtime)  # noqa: SLF001
        integration._subscribe_observer(hass, runtime)  # noqa: SLF001
        tracked[0](
            SimpleNamespace(
                data={"new_state": SimpleNamespace(state=vacuum_state, attributes={})},
                time_fired=AT,
            )
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert len(results) == 1
        assert isinstance(results[0], OSError)
        return runtime

    runtime = asyncio.run(exercise())

    assert runtime.topology_ready is False
    assert runtime.observation_active is False
    assert removed == [True]
    with pytest.raises(RuntimeInactiveError, match="reload"):
        runtime.capture_command_generation()
    assert runtime.state is not None
    assert runtime.state.ledger.blocks[0].state is BlockState.COMMITTED
    assert runtime.state.ledger.jobs[0].state is JobState.ACCEPTED
    assert issues == {"planner-entry-1_missing_registry"}


def test_configured_vacuum_and_mop_requires_live_mode_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    vacuum_entry = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        platform="mova",
        device_id="device-1",
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )
    mode_entry = SimpleNamespace(
        id="mode-registry-1",
        entity_id="select.cleaning_mode",
        domain="select",
        unique_id="device_cleaning_mode",
        disabled=False,
        disabled_by=None,
    )
    entries = [mode_entry]
    states = {
        "vacuum.old": SimpleNamespace(state="idle", attributes={"supported_features": 16384}),
        "select.cleaning_mode": SimpleNamespace(
            state="Vacuum", attributes={"options": ["Vacuum", "Vacuum and Mop"]}
        ),
    }
    registry = SimpleNamespace(
        async_get=lambda identity: (
            vacuum_entry
            if identity in {"registry-1", "vacuum.old"}
            else mode_entry
            if identity in {"mode-registry-1", "select.cleaning_mode"}
            else None
        )
    )
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    vars(registry_module)["async_get"] = lambda _hass: registry
    vars(registry_module)["async_entries_for_device"] = lambda _registry, _device_id: entries
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: states.get(entity_id)))

    assert (
        integration._configured_topology_issues(  # noqa: SLF001
            hass, "registry-1", ("kitchen",), requires_vacuum_and_mop=True
        )
        == set()
    )

    states["select.cleaning_mode"].attributes["options"] = ["Vacuum"]
    assert integration._configured_topology_issues(  # noqa: SLF001
        hass, "registry-1", ("kitchen",), requires_vacuum_and_mop=True
    ) == {"lost_capability"}

    states["select.cleaning_mode"].attributes["options"] = ["Vacuum", "Vacuum and Mop"]
    states["select.cleaning_mode"].state = "unavailable"
    assert integration._configured_topology_issues(  # noqa: SLF001
        hass, "registry-1", ("kitchen",), requires_vacuum_and_mop=True
    ) == {"lost_capability"}

    states["select.cleaning_mode"].state = "Vacuum"
    mode_entry.disabled_by = "user"
    assert integration._configured_topology_issues(  # noqa: SLF001
        hass, "registry-1", ("kitchen",), requires_vacuum_and_mop=True
    ) == {"lost_capability"}


def test_cleaning_mode_registry_loss_latches_and_reappearance_cannot_recover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    tracked: dict[str, Callable[[object], None]] = {}
    registry_listeners: list[Callable[[object], None]] = []
    created: list[str] = []
    vacuum_entry = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        platform="mova",
        device_id="device-1",
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )
    mode_entry = SimpleNamespace(
        id="mode-registry-1",
        entity_id="select.cleaning_mode",
        domain="select",
        unique_id="device_cleaning_mode",
        disabled=False,
        disabled_by=None,
    )
    replacement_mode_entry = SimpleNamespace(
        id="mode-registry-2",
        entity_id="select.replacement_cleaning_mode",
        domain="select",
        unique_id="replacement_cleaning_mode",
        disabled=False,
        disabled_by=None,
    )
    entries = [mode_entry]

    def registry_get(identity: str) -> object | None:
        if identity in {"registry-1", "vacuum.old"}:
            return vacuum_entry
        return next(
            (entry for entry in entries if identity in {entry.id, entry.entity_id}),
            None,
        )

    registry = SimpleNamespace(async_get=registry_get)
    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")

    def track(
        _hass: object, entity_ids: list[str], callback: Callable[[object], None]
    ) -> Callable[[], None]:
        tracked[entity_ids[0]] = callback
        return lambda: None

    vars(event_module)["async_track_state_change_event"] = track
    vars(registry_module).update(
        async_get=lambda _hass: registry,
        async_entries_for_device=lambda _registry, _device_id: entries,
        EVENT_ENTITY_REGISTRY_UPDATED="entity_registry_updated",
    )
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: created.append(issue_id),
        async_delete_issue=lambda *_args: None,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)
    states = {
        "vacuum.old": SimpleNamespace(state="idle", attributes={"supported_features": 16384}),
        "select.cleaning_mode": SimpleNamespace(
            state="Vacuum", attributes={"options": ["Vacuum", "Vacuum and Mop"]}
        ),
        "select.replacement_cleaning_mode": SimpleNamespace(
            state="Vacuum", attributes={"options": ["Vacuum", "Vacuum and Mop"]}
        ),
    }

    def listen(_event_type: str, callback: Callable[[object], None]) -> Callable[[], None]:
        registry_listeners.append(callback)
        return lambda: None

    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: states.get(entity_id)),
        bus=SimpleNamespace(async_listen=listen),
        async_create_task=lambda coroutine: coroutine.close(),
    )
    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        vacuum_registry_id="registry-1",
        cleaning_mode_entity_id="select.cleaning_mode",
        cleaning_mode_registry_id="mode-registry-1",
        requires_vacuum_and_mop=True,
        configured_area_ids=("kitchen",),
        config_entry_id="planner-entry-1",
    )
    integration._subscribe_observer(hass, runtime)  # noqa: SLF001

    mode_entry.entity_id = "select.renamed_cleaning_mode"
    states["select.renamed_cleaning_mode"] = states["select.cleaning_mode"]
    registry_listeners[0](SimpleNamespace(data={"action": "update"}))
    assert runtime.topology_ready is True
    assert runtime.cleaning_mode_entity_id == "select.renamed_cleaning_mode"
    assert "select.renamed_cleaning_mode" in tracked

    entries[:] = [replacement_mode_entry]
    registry_listeners[0](SimpleNamespace(data={"action": "remove"}))
    assert runtime.topology_ready is False
    assert created == ["planner-entry-1_lost_capability"]

    entries.append(mode_entry)
    registry_listeners[0](SimpleNamespace(data={"action": "create"}))
    tracked["select.cleaning_mode"](
        SimpleNamespace(data={"new_state": states["select.cleaning_mode"]})
    )
    assert runtime.topology_ready is False
    with pytest.raises(RuntimeError, match="reload"):
        runtime.capture_command_generation()


@pytest.mark.parametrize(
    ("supported_features", "mapping", "expected_issue"),
    [
        (0, {"kitchen": ["7"]}, "lost_capability"),
        (16384, {}, "missing_mapping"),
        (16384, {"hallway": ["4"]}, "removed_areas"),
    ],
)
def test_registry_update_latches_topology_failure_and_keeps_repair(
    monkeypatch: pytest.MonkeyPatch,
    supported_features: int,
    mapping: dict[str, list[str]],
    expected_issue: str,
) -> None:
    registry_listeners: list[Callable[[object], None]] = []
    created: list[str] = []
    deleted: list[str] = []
    registry_entry = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        options={"vacuum": {"area_mapping": mapping}},
    )
    state = SimpleNamespace(state="idle", attributes={"supported_features": supported_features})

    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    const_module = ModuleType("homeassistant.const")
    vars(event_module)["async_track_state_change_event"] = lambda *_args: lambda: None
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda registry_id: registry_entry if registry_id == "registry-1" else None
    )
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: created.append(issue_id),
        async_delete_issue=lambda _hass, _domain, issue_id: deleted.append(issue_id),
    )
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=16384)
    vars(const_module)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        coordinator=PlannerCoordinator(_started_state(), Store()),
        vacuum_registry_id="registry-1",
        config_entry_id="planner-entry-1",
    )

    def listen(_event_type: str, callback: Callable[[object], None]) -> Callable[[], None]:
        registry_listeners.append(callback)
        return lambda: None

    hass = SimpleNamespace(
        bus=SimpleNamespace(async_listen=listen),
        states=SimpleNamespace(get=lambda _entity_id: state),
        async_create_task=lambda coroutine: coroutine.close(),
    )
    integration._subscribe_observer(hass, runtime)  # noqa: SLF001

    registry_listeners[0](SimpleNamespace(data={"action": "update"}))

    assert runtime.topology_ready is False
    assert created == [f"planner-entry-1_{expected_issue}"]

    state.attributes["supported_features"] = 16384
    registry_entry.options = {"vacuum": {"area_mapping": {"kitchen": ["7"]}}}
    registry_listeners[0](SimpleNamespace(data={"action": "update"}))

    assert runtime.topology_ready is False
    assert f"planner-entry-1_{expected_issue}" not in deleted


@pytest.mark.parametrize(
    ("state", "attributes", "expected_issue"),
    [
        ("unavailable", {"supported_features": 16384}, "missing_registry"),
        ("idle", {"supported_features": 0}, "lost_capability"),
    ],
)
def test_state_or_capability_loss_stays_fail_closed_after_valid_state_returns(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    attributes: dict[str, int],
    expected_issue: str,
) -> None:
    tracked: list[Callable[[object], None]] = []
    removed: list[bool] = []
    created: list[str] = []
    tasks: list[asyncio.Task[object]] = []
    event_module = ModuleType("homeassistant.helpers.event")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")

    def track(
        _hass: object, _entity_ids: list[str], callback: Callable[[object], None]
    ) -> Callable[[], None]:
        tracked.append(callback)
        return lambda: removed.append(True)

    vars(event_module)["async_track_state_change_event"] = track
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: created.append(issue_id),
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            del state

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        coordinator=PlannerCoordinator(_accepted_state(), Store()),
        config_entry_id="planner-entry-1",
    )

    async def exercise() -> None:
        hass = SimpleNamespace(
            async_create_task=lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        )
        integration._subscribe_observer(hass, runtime)  # noqa: SLF001
        tracked[0](
            SimpleNamespace(
                data={"new_state": SimpleNamespace(state=state, attributes=attributes)},
                time_fired=AT,
            )
        )
        await asyncio.gather(*tasks)
        tasks.clear()
        tracked[0](
            SimpleNamespace(
                data={
                    "new_state": SimpleNamespace(
                        state="idle", attributes={"supported_features": 16384}
                    )
                },
                time_fired=AT,
            )
        )

    asyncio.run(exercise())

    assert runtime.topology_ready is False
    assert runtime.observation_active is False
    assert removed == [True]
    assert created == [f"planner-entry-1_{expected_issue}"]
    assert tasks == []


def test_area_registry_loss_stays_fail_closed_after_area_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    listeners: dict[str, Callable[[object], None]] = {}
    created: list[str] = []
    deleted: list[str] = []
    area_exists = True
    registry_entry = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.old",
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )
    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    area_registry_module = ModuleType("homeassistant.helpers.area_registry")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    vars(event_module)["async_track_state_change_event"] = lambda *_args: lambda: None
    vars(registry_module).update(
        EVENT_ENTITY_REGISTRY_UPDATED="entity_registry_updated",
        async_get=lambda _hass: SimpleNamespace(async_get=lambda _registry_id: registry_entry),
    )
    vars(area_registry_module).update(
        EVENT_AREA_REGISTRY_UPDATED="area_registry_updated",
        async_get=lambda _hass: SimpleNamespace(
            async_get_area=lambda area_id: SimpleNamespace(id=area_id) if area_exists else None
        ),
    )
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: created.append(issue_id),
        async_delete_issue=lambda _hass, _domain, issue_id: deleted.append(issue_id),
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.area_registry", area_registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    def listen(event_type: str, callback: Callable[[object], None]) -> Callable[[], None]:
        listeners[event_type] = callback
        return lambda: None

    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        vacuum_registry_id="registry-1",
        config_entry_id="planner-entry-1",
        configured_area_ids=("kitchen",),
    )
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_listen=listen),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 16384}
            )
        ),
        async_create_task=lambda coroutine: coroutine.close(),
    )
    integration._subscribe_observer(hass, runtime)  # noqa: SLF001

    area_exists = False
    listeners["area_registry_updated"](SimpleNamespace(data={"action": "remove"}))
    area_exists = True
    listeners["area_registry_updated"](SimpleNamespace(data={"action": "create"}))

    assert runtime.topology_ready is False
    assert created == ["planner-entry-1_removed_areas"]
    assert deleted == []


def test_observer_unsubscribe_attempts_every_nested_listener_after_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_valid_topology_modules(monkeypatch)
    calls: list[str] = []
    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    area_registry_module = ModuleType("homeassistant.helpers.area_registry")
    vars(event_module)["async_track_state_change_event"] = lambda *_args: _failing_unsubscribe(
        calls, "state"
    )
    vars(registry_module).update(
        EVENT_ENTITY_REGISTRY_UPDATED="entity_registry_updated",
        async_get=lambda _hass: SimpleNamespace(async_get=lambda _registry_id: None),
    )
    vars(area_registry_module).update(EVENT_AREA_REGISTRY_UPDATED="area_registry_updated")
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.area_registry", area_registry_module)

    def listen(event_type: str, _callback: Callable[[object], None]) -> Callable[[], None]:
        if event_type == "entity_registry_updated":
            return _failing_unsubscribe(calls, "entity_registry")
        return lambda: calls.append("area_registry")

    runtime = VacuumPlannerRuntimeData("vacuum.old", vacuum_registry_id="registry-1")
    hass = SimpleNamespace(bus=SimpleNamespace(async_listen=listen))
    integration._subscribe_observer(hass, runtime)  # noqa: SLF001
    assert runtime.observer_unsubscribe is not None

    with pytest.raises(ExceptionGroup) as raised:
        runtime.observer_unsubscribe()

    assert [str(error) for error in raised.value.exceptions] == [
        "state cleanup failed",
        "entity_registry cleanup failed",
    ]
    assert calls == ["state", "entity_registry", "area_registry"]
    assert runtime.observation_active is False


def _failing_unsubscribe(calls: list[str], name: str) -> Callable[[], None]:
    def unsubscribe() -> None:
        calls.append(name)
        raise RuntimeError(f"{name} cleanup failed")

    return unsubscribe


def test_command_time_registry_resolution_follows_rename_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_entry = SimpleNamespace(
        id="registry-1",
        entity_id="vacuum.renamed",
        domain="vacuum",
        disabled=False,
        disabled_by=None,
        options={"vacuum": {"area_mapping": {"kitchen": ["7"]}}},
    )
    registry = SimpleNamespace(
        async_get=lambda value: registry_entry if value == "registry-1" else None
    )
    registry_module = __import__("types").ModuleType("homeassistant.helpers.entity_registry")
    exceptions_module = __import__("types").ModuleType("homeassistant.exceptions")
    vars(registry_module)["async_get"] = lambda _hass: registry
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    monkeypatch.setitem(
        __import__("sys").modules, "homeassistant.helpers.entity_registry", registry_module
    )
    monkeypatch.setitem(__import__("sys").modules, "homeassistant.exceptions", exceptions_module)
    runtime = VacuumPlannerRuntimeData("vacuum.stale", vacuum_registry_id="registry-1")

    assert integration._resolve_command_vacuum(SimpleNamespace(), runtime) == "vacuum.renamed"  # noqa: SLF001

    registry.async_get = lambda _value: None
    with pytest.raises(ValueError, match="registered"):
        integration._resolve_command_vacuum(SimpleNamespace(), runtime)  # noqa: SLF001


@pytest.mark.parametrize("workflow_state", [JobState.ACCEPTED, JobState.RUNNING])
def test_registry_removal_durably_quarantines_active_work_before_observer_detach(
    monkeypatch: pytest.MonkeyPatch,
    workflow_state: JobState,
) -> None:
    tracked: list[tuple[tuple[str, ...], Callable[[object], None]]] = []
    removed: list[tuple[str, ...]] = []
    registry_listeners: list[Callable[[object], None]] = []
    issues: set[str] = set()
    registry_entry: object | None = SimpleNamespace(id="registry-1", entity_id="vacuum.old")

    def track(
        _hass: object, entity_ids: list[str], callback: Callable[[object], None]
    ) -> Callable[[], None]:
        key = tuple(entity_ids)
        tracked.append((key, callback))
        return lambda: removed.append(key)

    event_module = ModuleType("homeassistant.helpers.event")
    registry_module = ModuleType("homeassistant.helpers.entity_registry")
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    vars(event_module)["async_track_state_change_event"] = track
    vars(registry_module)["async_get"] = lambda _hass: SimpleNamespace(
        async_get=lambda registry_id: registry_entry if registry_id == "registry-1" else None
    )
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: issues.add(issue_id),
        async_delete_issue=lambda _hass, _domain, issue_id: issues.discard(issue_id),
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    def listen(_event_type: str, callback: Callable[[object], None]) -> Callable[[], None]:
        registry_listeners.append(callback)
        return lambda: None

    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            assert removed == []
            saved.append(state)

    async def exercise() -> VacuumPlannerRuntimeData:
        nonlocal registry_entry
        state = _accepted_state()
        if workflow_state is JobState.RUNNING:
            state = integration_observer._running(state, AT)  # noqa: SLF001
        runtime = VacuumPlannerRuntimeData(
            "vacuum.old",
            coordinator=PlannerCoordinator(state, Store()),
            vacuum_registry_id="registry-1",
            config_entry_id="planner-entry-1",
        )
        tasks: list[asyncio.Task[object]] = []
        hass = SimpleNamespace(
            bus=SimpleNamespace(async_listen=listen),
            async_create_task=lambda coroutine: tasks.append(asyncio.create_task(coroutine)),
        )
        integration._subscribe_repairs(hass, runtime)  # noqa: SLF001
        integration._subscribe_observer(hass, runtime)  # noqa: SLF001
        stale_callback = tracked[0][1]
        registry_entry = None
        registry_listeners[0](SimpleNamespace(data={"action": "remove"}))
        stale_callback(
            SimpleNamespace(
                data={"new_state": SimpleNamespace(state="docked", attributes={})},
                time_fired=AT,
            )
        )
        await asyncio.gather(*tasks)
        return runtime

    runtime = asyncio.run(exercise())

    assert len(saved) == 1
    assert saved[0].ledger.blocks[0].state is BlockState.UNCERTAIN
    assert saved[0].ledger.jobs[0].state is JobState.UNCERTAIN
    assert runtime.state == saved[0]
    assert removed == [("vacuum.old",)]
    assert runtime.topology_ready is False
    assert runtime.observation_active is False
    assert issues == {
        "planner-entry-1_missing_registry",
        "planner-entry-1_unresolved_external_run",
    }


def test_uncertain_repair_tracks_only_durable_coordinator_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issues: set[str] = set()
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")
    vars(issue_registry).update(
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda _hass, _domain, issue_id, **_kwargs: issues.add(issue_id),
        async_delete_issue=lambda _hass, _domain, issue_id: issues.discard(issue_id),
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)

    class Store:
        fail = False

        async def async_save(self, _state: PlannerState) -> None:
            if self.fail:
                raise OSError("save failed")

    store = Store()
    runtime = VacuumPlannerRuntimeData(
        "vacuum.old",
        coordinator=PlannerCoordinator(_accepted_state(), store),
        config_entry_id="planner-entry-1",
    )
    integration._subscribe_repairs(SimpleNamespace(), runtime)  # noqa: SLF001

    asyncio.run(integration_observer.async_apply_observation(runtime, "unknown-new-state", {}, AT))
    issue = "planner-entry-1_unresolved_external_run"
    assert issues == {issue}

    assert runtime.coordinator is not None
    uncertain = runtime.coordinator.state
    store.fail = True
    with pytest.raises(OSError, match="save failed"):
        asyncio.run(
            runtime.coordinator.async_command(
                lambda _state: replace(
                    uncertain,
                    ledger=resolve_uncertain_job(
                        uncertain.ledger,
                        uncertain.ledger.jobs[0].job_id,
                        UncertainResolution.RETRY_SAFE,
                        AT,
                    ),
                )
            )
        )
    assert issues == {issue}

    store.fail = False
    asyncio.run(
        runtime.coordinator.async_command(
            lambda state: replace(
                state,
                ledger=resolve_uncertain_job(
                    state.ledger,
                    state.ledger.jobs[0].job_id,
                    UncertainResolution.RETRY_SAFE,
                    AT,
                ),
            )
        )
    )
    assert issues == set()
