import asyncio
import sys
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from custom_components import vacuum_planner as integration
from custom_components.vacuum_planner import async_setup_entry, async_unload_entry
from custom_components.vacuum_planner.const import (
    CONF_AREA_IDS,
    CONF_PLANNING_ENABLED,
    CONF_VACUUM_ENTITY_ID,
    DOMAIN,
    VacuumPlannerRuntimeData,
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
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import start_due_block
from custom_components.vacuum_planner.domain.serialization import (
    deserialize_planner_state,
    serialize_planner_state,
)


def test_integration_constants_define_entry_identity() -> None:
    assert DOMAIN == "vacuum_planner"
    assert CONF_VACUUM_ENTITY_ID == "vacuum_entity_id"


def test_setup_and_unload_manage_entry_runtime_data_without_platforms() -> None:
    hass = SimpleNamespace()
    entry = SimpleNamespace(
        data={CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
        options={},
        unique_id=None,
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data == VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs"
    )
    assert entry.runtime_data.planning_enabled is True
    assert entry.runtime_data.dry_run is True

    assert asyncio.run(async_unload_entry(hass, entry)) is True
    assert entry.runtime_data is None


def test_integration_setup_registers_read_only_get_queue_action_permanently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[
        str,
        tuple[Callable[[object], Coroutine[object, object, dict[str, object]]], object, object],
    ] = {}
    removed: list[tuple[str, str]] = []

    class EmptyHAStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> None:
            return None

        async def async_save(self, _data: dict[str, Any]) -> None:
            pass

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[[object], Coroutine[object, object, dict[str, object]]],
            *,
            schema: object,
            supports_response: object,
        ) -> None:
            registered[f"{domain}.{service}"] = (handler, schema, supports_response)

        def async_remove(self, domain: str, service: str) -> None:
            removed.append((domain, service))

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    storage_module = ModuleType("homeassistant.helpers.storage")
    core_module = ModuleType("homeassistant.core")
    vars(storage_module)["Store"] = EmptyHAStore
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(homeassistant_module)["core"] = core_module
    vars(helpers_module)["storage"] = storage_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage_module)
    monkeypatch.setitem(sys.modules, "homeassistant.core", core_module)

    hass = SimpleNamespace(data={}, services=Services())
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={
            CONF_VACUUM_ENTITY_ID: "vacuum.downstairs",
            CONF_AREA_IDS: ["kitchen"],
        },
        options={},
        unique_id=None,
        runtime_data=None,
    )

    assert asyncio.run(integration.async_setup(hass, {})) is True
    assert asyncio.run(async_setup_entry(hass, entry)) is True
    handler, _schema, supports_response = registered["vacuum_planner.get_queue"]
    response = asyncio.run(handler(SimpleNamespace(data={"config_entry_id": entry.entry_id})))

    assert supports_response == "only"
    assert response == {"revision": 0, "blocks": [], "jobs": []}
    assert asyncio.run(async_unload_entry(hass, entry)) is True
    assert removed == []


def test_get_queue_action_rejects_an_unloaded_config_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[
        str,
        Callable[[object], Coroutine[object, object, dict[str, object]]],
    ] = {}

    class StubServiceValidationError(Exception):
        pass

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[[object], Coroutine[object, object, dict[str, object]]],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

    core_module = ModuleType("homeassistant.core")
    exceptions_module = ModuleType("homeassistant.exceptions")
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = StubServiceValidationError
    monkeypatch.setitem(sys.modules, "homeassistant.core", core_module)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)
    hass = SimpleNamespace(data={}, services=Services())

    assert asyncio.run(integration.async_setup(hass, {})) is True
    handler = registered["vacuum_planner.get_queue"]

    with pytest.raises(StubServiceValidationError, match="not loaded"):
        asyncio.run(handler(SimpleNamespace(data={"config_entry_id": "missing"})))


def test_start_next_action_seals_due_work_idempotently_without_hardware_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[
        str,
        Callable[[object], Coroutine[object, object, dict[str, object]]],
    ] = {}
    saved: list[dict[str, Any]] = []
    hardware_calls: list[object] = []

    class EmptyHAStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> None:
            return None

        async def async_save(self, data: dict[str, Any]) -> None:
            saved.append(data)

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[[object], Coroutine[object, object, dict[str, object]]],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

        async def async_call(self, *args: object, **kwargs: object) -> None:
            hardware_calls.append((args, kwargs))

    registry_entry = SimpleNamespace(
        id="vacuum-registry-entry",
        entity_id="vacuum.downstairs",
        options={"vacuum": {"area_mapping": {"kitchen": ["segment-7"]}}},
    )
    entity_registry = SimpleNamespace(async_get=lambda _value: registry_entry)
    area_registry = SimpleNamespace(
        async_get_area=lambda area_id: SimpleNamespace(id=area_id, name="Kitchen")
    )
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    storage_module = ModuleType("homeassistant.helpers.storage")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    area_registry_module = ModuleType("homeassistant.helpers.area_registry")
    core_module = ModuleType("homeassistant.core")
    exceptions_module = ModuleType("homeassistant.exceptions")
    vars(storage_module)["Store"] = EmptyHAStore
    vars(entity_registry_module)["async_get"] = lambda _hass: entity_registry
    vars(area_registry_module)["async_get"] = lambda _hass: area_registry
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["storage"] = storage_module
    vars(helpers_module)["entity_registry"] = entity_registry_module
    vars(helpers_module)["area_registry"] = area_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage_module)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.area_registry", area_registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.core", core_module)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)

    hass = SimpleNamespace(
        data={},
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(attributes={"supported_features": 1024})
        ),
    )
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={
            CONF_VACUUM_ENTITY_ID: "vacuum.downstairs",
            CONF_AREA_IDS: ["kitchen"],
        },
        options={},
        unique_id="vacuum-registry-entry",
        runtime_data=None,
    )

    assert asyncio.run(integration.async_setup(hass, {})) is True
    assert asyncio.run(async_setup_entry(hass, entry)) is True
    handler = registered["vacuum_planner.start_next"]

    first = asyncio.run(handler(SimpleNamespace(data={"config_entry_id": entry.entry_id})))
    second = asyncio.run(handler(SimpleNamespace(data={"config_entry_id": entry.entry_id})))

    assert first["status"] == "created"
    assert second["status"] == "existing"
    assert first["block_id"] == second["block_id"]
    assert first["area_ids"] == ["kitchen"]
    assert first["dry_run"] is True
    assert len(entry.runtime_data.state.ledger.blocks) == 1
    assert len(entry.runtime_data.state.ledger.jobs) == 1
    assert len(saved) == 2  # initial state and one successful command
    assert hardware_calls == []


def test_start_next_live_dispatch_persists_before_native_service_call(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[
        str,
        Callable[[object], Coroutine[object, object, dict[str, object]]],
    ] = {}
    events: list[tuple[str, object]] = []
    service_call_context = object()

    class EmptyHAStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> None:
            return None

        async def async_save(self, data: dict[str, Any]) -> None:
            events.append(("save", data))

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[[object], Coroutine[object, object, dict[str, object]]],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

        async def async_call(
            self,
            domain: str,
            service: str,
            service_data: dict[str, object],
            *,
            target: dict[str, object],
            blocking: bool,
            context: object,
        ) -> None:
            events.append(
                (
                    "call",
                    (domain, service, service_data, target, blocking, context),
                )
            )

    registry_entry = SimpleNamespace(
        id="vacuum-registry-entry",
        entity_id="vacuum.downstairs",
        options={
            "vacuum": {
                "area_mapping": {
                    "kitchen": ["segment-7"],
                    "hallway": ["segment-2"],
                }
            }
        },
    )
    entity_registry = SimpleNamespace(async_get=lambda _value: registry_entry)
    area_registry = SimpleNamespace(
        async_get_area=lambda area_id: SimpleNamespace(id=area_id, name=area_id.title())
    )
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    storage_module = ModuleType("homeassistant.helpers.storage")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    area_registry_module = ModuleType("homeassistant.helpers.area_registry")
    core_module = ModuleType("homeassistant.core")
    exceptions_module = ModuleType("homeassistant.exceptions")
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(storage_module)["Store"] = EmptyHAStore
    vars(entity_registry_module)["async_get"] = lambda _hass: entity_registry
    vars(area_registry_module)["async_get"] = lambda _hass: area_registry
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["storage"] = storage_module
    vars(helpers_module)["entity_registry"] = entity_registry_module
    vars(helpers_module)["area_registry"] = area_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage_module)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.area_registry", area_registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.core", core_module)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)

    hass = SimpleNamespace(
        data={},
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 1024}
            )
        ),
    )
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={
            CONF_VACUUM_ENTITY_ID: "vacuum.downstairs",
            CONF_AREA_IDS: ["kitchen", "hallway"],
        },
        options={"dry_run": False},
        unique_id="vacuum-registry-entry",
        runtime_data=None,
    )

    assert asyncio.run(integration.async_setup(hass, {})) is True
    assert asyncio.run(async_setup_entry(hass, entry)) is True
    events.clear()

    response = asyncio.run(
        registered["vacuum_planner.start_next"](
            SimpleNamespace(
                data={"config_entry_id": entry.entry_id},
                context=service_call_context,
            )
        )
    )

    assert [event[0] for event in events] == ["save", "save", "call", "save"]
    committing_payload = events[1][1]
    accepted_payload = events[3][1]
    assert isinstance(committing_payload, dict)
    assert isinstance(accepted_payload, dict)
    committing = deserialize_planner_state(committing_payload)
    accepted = deserialize_planner_state(accepted_payload)
    assert committing.ledger.blocks[0].state is BlockState.COMMITTING
    assert accepted.ledger.blocks[0].state is BlockState.COMMITTED
    assert {job.state for job in accepted.ledger.jobs} == {JobState.ACCEPTED}
    assert events[2][1] == (
        "vacuum",
        "clean_area",
        {"cleaning_area_id": ["hallway", "kitchen"]},
        {"entity_id": "vacuum.downstairs"},
        True,
        service_call_context,
    )
    assert response["status"] == "created"
    assert response["dry_run"] is False


def test_live_dispatch_failure_is_persisted_without_claiming_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    ids = iter(("block-1", "job-1"))
    result = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot(
            "revision-1",
            "lane-1",
            at,
            (SnapshotJob("kitchen", "Kitchen", (), Mode.VACUUM, 1, at),),
        ),
        "lane-1",
        "start-next-1",
        at,
        lambda: next(ids),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    initial = PlannerState(PlanRevision("revision-1", at, ()), result.ledger)
    saved: list[PlannerState] = []
    service_call_context = object()

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            raise OSError("service unavailable")

    class StubServiceValidationError(Exception):
        pass

    exceptions_module = ModuleType("homeassistant.exceptions")
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(exceptions_module)["ServiceValidationError"] = StubServiceValidationError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        dry_run=False,
        coordinator=coordinator,
    )

    with pytest.raises(StubServiceValidationError, match="dispatch failed"):
        asyncio.run(
            integration._async_dispatch_created_block(  # noqa: SLF001
                SimpleNamespace(
                    services=Services(),
                    states=SimpleNamespace(
                        get=lambda _entity_id: SimpleNamespace(
                            state="idle", attributes={"supported_features": 1024}
                        )
                    ),
                ),
                runtime,
                result,
                service_call_context,
                clock=lambda: at,
            )
        )

    assert [state.ledger.blocks[0].state for state in saved] == [
        BlockState.COMMITTING,
        BlockState.FAILED,
    ]
    assert {job.state for job in coordinator.state.ledger.jobs} == {JobState.FAILED}
    assert all(
        job.error_code == "native_area_dispatch_failed"
        for job in coordinator.state.ledger.jobs
    )


def test_setup_exposes_disabled_planning_option_in_runtime_data() -> None:
    hass = SimpleNamespace()
    entry = SimpleNamespace(
        data={CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
        options={CONF_PLANNING_ENABLED: False},
        unique_id=None,
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.planning_enabled is False


def test_setup_resolves_current_entity_id_from_stable_registry_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    registry = SimpleNamespace(
        async_get=lambda _registry_id: SimpleNamespace(entity_id="vacuum.renamed")
    )
    vars(entity_registry_module)["async_get"] = lambda _hass: registry
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["entity_registry"] = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module
    )

    updated: list[dict[str, str]] = []
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda _entry, *, data: updated.append(data)
        )
    )
    entry = SimpleNamespace(
        data={CONF_VACUUM_ENTITY_ID: "vacuum.old_name"},
        options={},
        unique_id="vacuum-registry-entry",
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data == VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.renamed"
    )
    assert updated == [{CONF_VACUUM_ENTITY_ID: "vacuum.renamed"}]


def test_setup_loads_entry_specific_planner_state_from_atomic_ha_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = PlannerState(
        plan_revision=PlanRevision(
            revision_id="revision-1",
            created_at=datetime(2026, 9, 17, 8, 0, tzinfo=UTC),
            room_plans=(),
        ),
        ledger=QueueLedger.empty(),
    )
    constructed: list[tuple[object, int, str, bool]] = []

    class FakeHAStore:
        def __init__(
            self,
            hass: object,
            version: int,
            key: str,
            *,
            atomic_writes: bool = False,
        ) -> None:
            constructed.append((hass, version, key, atomic_writes))

        async def async_load(self) -> dict[str, Any]:
            return serialize_planner_state(expected)

        async def async_save(self, _data: dict[str, Any]) -> None:
            raise AssertionError("setup must not rewrite loaded state")

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    storage_module = ModuleType("homeassistant.helpers.storage")
    vars(storage_module)["Store"] = FakeHAStore
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["storage"] = storage_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage_module)

    hass = SimpleNamespace()
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
        options={},
        unique_id=None,
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.state == expected
    assert entry.runtime_data.coordinator is not None
    assert entry.runtime_data.coordinator.state == expected
    assert constructed == [(hass, 1, "vacuum_planner.planner-entry-1", True)]


def test_setup_initializes_and_persists_room_plans_for_configured_ha_areas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[dict[str, Any]] = []

    class EmptyHAStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> None:
            return None

        async def async_save(self, data: dict[str, Any]) -> None:
            assert entry.runtime_data is None
            saved.append(data)

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    storage_module = ModuleType("homeassistant.helpers.storage")
    vars(storage_module)["Store"] = EmptyHAStore
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["storage"] = storage_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage_module)

    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={
            CONF_VACUUM_ENTITY_ID: "vacuum.downstairs",
            CONF_AREA_IDS: ["hallway", "kitchen"],
        },
        options={},
        unique_id=None,
        runtime_data=None,
    )
    before_setup = datetime.now(UTC)

    assert asyncio.run(async_setup_entry(SimpleNamespace(), entry)) is True
    after_setup = datetime.now(UTC)

    assert entry.runtime_data.coordinator is not None
    assert len(saved) == 1
    initial = deserialize_planner_state(saved[0])
    assert entry.runtime_data.state == initial
    assert [plan.area_id for plan in initial.plan_revision.room_plans] == [
        "hallway",
        "kitchen",
    ]
    assert all(
        plan.lane_id == "planner-entry-1"
        and plan.enabled
        and plan.vacuum_interval_days == 7
        and plan.vacuum_and_mop_interval_days is None
        and plan.preferred_mode is PreferredMode.VACUUM
        for plan in initial.plan_revision.room_plans
    )
    assert initial.ledger == QueueLedger.empty()
    assert before_setup <= initial.plan_revision.created_at <= after_setup
    assert initial.plan_revision.created_at.tzinfo is UTC
    assert UUID(initial.plan_revision.revision_id).version == 4


def test_setup_quarantines_and_persists_ambiguous_dispatch_before_runtime_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    ids = iter(("block-1", "job-1"))
    ledger = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot(
            "revision-1",
            "lane-1",
            started_at,
            (SnapshotJob("kitchen", "Kitchen", 7, Mode.VACUUM, 1, started_at),),
        ),
        "lane-1",
        "2026-09-17",
        started_at,
        lambda: next(ids),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    for state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        ledger = ledger.replace_block_state("block-1", state, started_at)
    ledger = ledger.replace_job_state("job-1", JobState.DISPATCHING, started_at)
    loaded = PlannerState(
        PlanRevision("revision-1", started_at, ()),
        ledger,
    )
    saved: list[dict[str, Any]] = []

    class FakeHAStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> dict[str, Any]:
            return serialize_planner_state(loaded)

        async def async_save(self, data: dict[str, Any]) -> None:
            assert entry.runtime_data is None
            saved.append(data)

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    storage_module = ModuleType("homeassistant.helpers.storage")
    vars(storage_module)["Store"] = FakeHAStore
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["storage"] = storage_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage_module)

    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
        options={},
        unique_id=None,
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(SimpleNamespace(), entry)) is True

    assert len(saved) == 1
    recovered = deserialize_planner_state(saved[0])
    assert recovered.ledger.blocks[0].state is BlockState.UNCERTAIN
    assert recovered.ledger.blocks[0].completed_at is None
    assert recovered.ledger.jobs[0].state is JobState.UNCERTAIN
    assert recovered.ledger.jobs[0].finished_at is None
    assert recovered.ledger.revision == loaded.ledger.revision + 1
    assert entry.runtime_data.state == recovered


@pytest.mark.parametrize("failure_operation", ["load", "save"])
def test_setup_retries_when_planner_store_has_transient_io_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure_operation: str,
) -> None:
    class StubConfigEntryNotReadyError(Exception):
        pass

    class FailingHAStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> dict[str, Any] | None:
            if failure_operation == "load":
                raise OSError("storage temporarily unavailable")
            return None

        async def async_save(self, _data: dict[str, Any]) -> None:
            if failure_operation == "save":
                raise OSError("storage temporarily unavailable")
            raise AssertionError("setup must not save state after a load failure")

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    storage_module = ModuleType("homeassistant.helpers.storage")
    exceptions_module = ModuleType("homeassistant.exceptions")
    vars(storage_module)["Store"] = FailingHAStore
    vars(exceptions_module)["ConfigEntryNotReady"] = StubConfigEntryNotReadyError
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(homeassistant_module)["exceptions"] = exceptions_module
    vars(helpers_module)["storage"] = storage_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage_module)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)

    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        data={CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
        options={},
        unique_id=None,
        runtime_data=None,
    )

    with pytest.raises(StubConfigEntryNotReadyError) as raised:
        asyncio.run(async_setup_entry(SimpleNamespace(), entry))

    assert isinstance(raised.value.__cause__, OSError)
    assert entry.runtime_data is None
