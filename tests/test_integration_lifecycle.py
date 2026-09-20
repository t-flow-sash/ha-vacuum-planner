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
    RoomPlan,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import start_due_block
from custom_components.vacuum_planner.domain.serialization import (
    deserialize_planner_state,
    serialize_planner_state,
)
from custom_components.vacuum_planner.integration_observer import async_apply_observation


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
    assert entry.runtime_data == VacuumPlannerRuntimeData(vacuum_entity_id="vacuum.downstairs")
    assert entry.runtime_data.planning_enabled is True
    assert entry.runtime_data.dry_run is True

    assert asyncio.run(async_unload_entry(hass, entry)) is True
    assert entry.runtime_data is None


def test_setup_forwards_sensor_platform_and_unload_removes_it() -> None:
    forwarded: list[tuple[object, tuple[str, ...]]] = []
    unloaded: list[tuple[object, tuple[str, ...]]] = []

    class ConfigEntries:
        async def async_forward_entry_setups(
            self, entry: object, platforms: tuple[str, ...]
        ) -> None:
            forwarded.append((entry, platforms))

        async def async_unload_platforms(self, entry: object, platforms: tuple[str, ...]) -> bool:
            unloaded.append((entry, platforms))
            return True

    hass = SimpleNamespace(config_entries=ConfigEntries())
    entry = SimpleNamespace(
        data={CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
        options={},
        unique_id=None,
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert forwarded == [(entry, ("sensor", "switch", "binary_sensor", "button", "number"))]
    assert asyncio.run(async_unload_entry(hass, entry)) is True
    assert unloaded == [(entry, ("sensor", "switch", "binary_sensor", "button", "number"))]
    assert entry.runtime_data is None


def test_failed_platform_unload_preserves_runtime_data() -> None:
    class ConfigEntries:
        async def async_unload_platforms(self, _entry: object, _platforms: tuple[str, ...]) -> bool:
            return False

    runtime_data = VacuumPlannerRuntimeData(vacuum_entity_id="vacuum.downstairs")
    hass = SimpleNamespace(config_entries=ConfigEntries())
    entry = SimpleNamespace(entry_id=None, runtime_data=runtime_data)

    assert asyncio.run(async_unload_entry(hass, entry)) is False
    assert entry.runtime_data is runtime_data


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


def test_start_next_action_seals_due_work_idempotently_without_hardware_calls(  # noqa: PLR0915 - hermetic HA module setup
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
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    const_module = ModuleType("homeassistant.const")
    vars(storage_module)["Store"] = EmptyHAStore
    vars(entity_registry_module)["async_get"] = lambda _hass: entity_registry
    vars(area_registry_module)["async_get"] = lambda _hass: area_registry
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    vars(const_module)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
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
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)

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

    entry.runtime_data.dry_run = False
    with pytest.raises(ValueError, match=r"Dry-run block cancelled.*retry"):
        asyncio.run(handler(SimpleNamespace(data={"config_entry_id": entry.entry_id})))

    assert entry.runtime_data.state.ledger.blocks[0].state is BlockState.CANCELLED
    assert entry.runtime_data.state.ledger.jobs[0].state is JobState.CANCELLED
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
        domain="vacuum",
        disabled=False,
        disabled_by=None,
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
    const_module = ModuleType("homeassistant.const")
    vars(storage_module)["Store"] = EmptyHAStore
    vars(entity_registry_module)["async_get"] = lambda _hass: entity_registry
    vars(area_registry_module)["async_get"] = lambda _hass: area_registry
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    vars(const_module)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
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
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)

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
    sealed_payload = events[0][1]
    committing_payload = events[1][1]
    accepted_payload = events[3][1]
    assert isinstance(sealed_payload, dict)
    assert isinstance(committing_payload, dict)
    assert isinstance(accepted_payload, dict)
    sealed = deserialize_planner_state(sealed_payload)
    committing = deserialize_planner_state(committing_payload)
    accepted = deserialize_planner_state(accepted_payload)
    assert sealed.ledger.blocks[0].state is BlockState.SEALED
    assert committing.ledger.blocks[0].state is BlockState.COMMITTING
    assert accepted.ledger.blocks[0].state is BlockState.COMMITTED
    assert {job.state for job in accepted.ledger.jobs} == {JobState.ACCEPTED}
    assert events[2][1] == (
        "vacuum",
        "clean_area",
        {"cleaning_area_id": ["hallway"]},
        {"entity_id": "vacuum.downstairs"},
        True,
        service_call_context,
    )
    assert response["status"] == "created"
    assert response["area_ids"] == ["hallway"]
    assert response["dry_run"] is False


def test_start_next_reuses_persisted_sealed_native_batch_after_restart(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    current_at = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    persisted_date = started_at.date().isoformat()
    current_date = current_at.date().isoformat()
    assert persisted_date != current_date
    monkeypatch.setattr(integration, "_utcnow", lambda: current_at)
    sealed_revision_id = "revision-1"
    plan = PlanRevision("revision-2", current_at, ())
    ids = iter(("block-1", "job-1"))
    sealed = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot(
            sealed_revision_id,
            "vacuum-registry-entry",
            started_at,
            (SnapshotJob("kitchen", "Kitchen", ("segment-7",), Mode.VACUUM, 0, started_at),),
        ),
        "vacuum-registry-entry",
        f"start_next:{sealed_revision_id}:{persisted_date}",
        started_at,
        lambda: next(ids),
        DispatchStrategy.NATIVE_BATCH,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    loaded = PlannerState(plan, sealed.ledger)
    registered: dict[
        str,
        Callable[[object], Coroutine[object, object, dict[str, object]]],
    ] = {}
    events: list[tuple[str, object]] = []

    class FakeHAStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> dict[str, Any]:
            return serialize_planner_state(loaded)

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

        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            events.append(("call", None))

    registry_entry = SimpleNamespace(
        id="vacuum-registry-entry",
        entity_id="vacuum.downstairs",
        domain="vacuum",
        disabled=False,
        disabled_by=None,
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
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    const_module = ModuleType("homeassistant.const")
    vars(storage_module)["Store"] = FakeHAStore
    vars(entity_registry_module)["async_get"] = lambda _hass: entity_registry
    vars(area_registry_module)["async_get"] = lambda _hass: area_registry
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = ValueError
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    vars(const_module)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
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
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)
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
            CONF_AREA_IDS: ["kitchen"],
        },
        options={"dry_run": False},
        unique_id="vacuum-registry-entry",
        runtime_data=None,
    )

    assert asyncio.run(integration.async_setup(hass, {})) is True
    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.topology_ready is True
    response = asyncio.run(
        registered["vacuum_planner.start_next"](
            SimpleNamespace(data={"config_entry_id": entry.entry_id}, context=object())
        )
    )

    assert response["status"] == "existing"
    assert response["block_id"] == "block-1"
    assert [event[0] for event in events] == ["save", "call", "save"]
    committing_payload = events[0][1]
    assert isinstance(committing_payload, dict)
    committing = deserialize_planner_state(committing_payload)
    assert committing.ledger.blocks[0].state is BlockState.COMMITTING
    assert entry.runtime_data.state.ledger.blocks[0].state is BlockState.COMMITTED


def test_parallel_start_next_claims_native_batch_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    plan = PlanRevision(
        "revision-1",
        started_at,
        (
            RoomPlan(
                area_id="kitchen",
                lane_id="lane-1",
                enabled=True,
                vacuum_interval_days=1,
                vacuum_and_mop_interval_days=None,
                preferred_mode=PreferredMode.VACUUM,
                priority=0,
            ),
        ),
    )
    saved: list[PlannerState] = []
    service_calls = 0
    first_save_started = asyncio.Event()
    release_first_save = asyncio.Event()
    service_started = asyncio.Event()
    release_service = asyncio.Event()
    registered: dict[
        str,
        Callable[[object], Coroutine[object, object, dict[str, object]]],
    ] = {}

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            if not saved:
                first_save_started.set()
                await release_first_save.wait()
            saved.append(state)

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[[object], Coroutine[object, object, dict[str, object]]],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            nonlocal service_calls
            service_calls += 1
            service_started.set()
            await release_service.wait()

    registry_entry = SimpleNamespace(
        id="vacuum-registry-entry",
        entity_id="vacuum.downstairs",
        domain="vacuum",
        disabled=False,
        disabled_by=None,
        options={"vacuum": {"area_mapping": {"kitchen": ["segment-7"]}}},
    )
    entity_registry = SimpleNamespace(async_get=lambda _value: registry_entry)
    area_registry = SimpleNamespace(
        async_get_area=lambda area_id: SimpleNamespace(id=area_id, name="Kitchen")
    )
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    area_registry_module = ModuleType("homeassistant.helpers.area_registry")
    core_module = ModuleType("homeassistant.core")
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(entity_registry_module)["async_get"] = lambda _hass: entity_registry
    vars(area_registry_module)["async_get"] = lambda _hass: area_registry
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.area_registry", area_registry_module)
    monkeypatch.setitem(sys.modules, "homeassistant.core", core_module)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    coordinator = PlannerCoordinator(PlannerState(plan, QueueLedger.empty()), Store())
    runtime = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        dry_run=False,
        coordinator=coordinator,
        vacuum_registry_id="vacuum-registry-entry",
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"planner-entry-1": runtime}},
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 1024}
            )
        ),
    )
    integration._register_start_next_action(hass)  # noqa: SLF001
    handler = registered["vacuum_planner.start_next"]

    async def exercise_parallel_start() -> tuple[dict[str, object], dict[str, object]]:
        first_task = asyncio.create_task(
            handler(SimpleNamespace(data={"config_entry_id": "planner-entry-1"}, context=object()))
        )
        await first_save_started.wait()
        second_task = asyncio.create_task(
            handler(SimpleNamespace(data={"config_entry_id": "planner-entry-1"}, context=object()))
        )
        await asyncio.sleep(0)
        release_first_save.set()
        await service_started.wait()
        release_service.set()
        first, second = await asyncio.gather(first_task, second_task)
        return first, second

    first, second = asyncio.run(exercise_parallel_start())

    assert first["status"] == "created"
    assert second["status"] == "existing"
    assert first["block_id"] == second["block_id"]
    assert service_calls == 1
    assert [state.ledger.blocks[0].state for state in saved] == [
        BlockState.SEALED,
        BlockState.COMMITTING,
        BlockState.COMMITTED,
    ]


def test_pause_queued_before_start_wins_under_shared_command_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[
        str,
        Callable[[object], Coroutine[object, object, dict[str, object]]],
    ] = {}

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[[object], Coroutine[object, object, dict[str, object]]],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    class StubServiceValidationError(Exception):
        pass

    core_module = ModuleType("homeassistant.core")
    exceptions_module = ModuleType("homeassistant.exceptions")
    vars(core_module)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions_module)["ServiceValidationError"] = StubServiceValidationError
    monkeypatch.setitem(sys.modules, "homeassistant.core", core_module)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions_module)

    coordinator = PlannerCoordinator(
        PlannerState(PlanRevision("revision-1", datetime.now(UTC), ()), QueueLedger.empty()),
        Store(),
    )
    runtime = VacuumPlannerRuntimeData("vacuum.downstairs", coordinator=coordinator)
    hass = SimpleNamespace(
        data={DOMAIN: {"planner-entry-1": runtime}},
        services=Services(),
    )
    integration._register_start_next_action(hass)  # noqa: SLF001
    handler = registered["vacuum_planner.start_next"]

    async def exercise() -> None:
        await coordinator._command_lock.acquire()  # noqa: SLF001 - deterministic queue ordering
        pause = asyncio.create_task(runtime.async_set_planning_enabled(enabled=False))
        await asyncio.sleep(0)
        start = asyncio.create_task(
            handler(SimpleNamespace(data={"config_entry_id": "planner-entry-1"}, context=object()))
        )
        await asyncio.sleep(0)
        coordinator._command_lock.release()  # noqa: SLF001
        await pause
        with pytest.raises(StubServiceValidationError, match="paused"):
            await start

    asyncio.run(exercise())
    assert runtime.planning_enabled is False


def test_live_dispatch_preflight_failure_keeps_sealed_block_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.downstairs")
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
    service_calls = 0

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            nonlocal service_calls
            service_calls += 1

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
        vacuum_entity_id="vacuum.downstairs", dry_run=False, coordinator=coordinator
    )

    with pytest.raises(StubServiceValidationError, match="preflight"):
        asyncio.run(
            integration._async_dispatch_created_block(  # noqa: SLF001
                SimpleNamespace(
                    services=Services(),
                    states=SimpleNamespace(
                        get=lambda _entity_id: SimpleNamespace(
                            state="idle", attributes={"supported_features": -1}
                        )
                    ),
                ),
                runtime,
                result,
                object(),
                clock=lambda: at,
            )
        )

    assert service_calls == 0
    assert saved == []
    assert coordinator.state.ledger.blocks[0].state is BlockState.SEALED
    assert coordinator.state.ledger.jobs[0].state is JobState.PENDING


@pytest.mark.parametrize(
    "observations",
    [
        (("cleaning", {}),),
        (("error", {}),),
        (("unavailable", {}),),
        (("cleaning", {}), ("idle", {})),
    ],
)
def test_live_dispatch_does_not_overwrite_advanced_observation(
    monkeypatch: pytest.MonkeyPatch,
    observations: tuple[tuple[str, dict[str, object]], ...],
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.downstairs")
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

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        dry_run=False,
        coordinator=coordinator,
    )

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            for vacuum_state, attributes in observations:
                await async_apply_observation(runtime, vacuum_state, attributes, at)

    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 1024}
            )
        ),
    )

    persisted = asyncio.run(
        integration._async_dispatch_created_block(  # noqa: SLF001
            hass,
            runtime,
            result,
            object(),
            clock=lambda: at,
        )
    )

    assert persisted is coordinator.state
    assert persisted.ledger.blocks[0].state is not BlockState.COMMITTED


def test_live_dispatch_exception_after_side_effect_is_quarantined_as_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.downstairs")
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
        BlockState.UNCERTAIN,
    ]
    assert {job.state for job in coordinator.state.ledger.jobs} == {JobState.UNCERTAIN}
    assert all(job.sent_at == at for job in coordinator.state.ledger.jobs)


def test_live_dispatch_cancellation_is_quarantined_before_reraising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.downstairs")
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

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            raise asyncio.CancelledError

    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        dry_run=False,
        coordinator=coordinator,
    )

    with pytest.raises(asyncio.CancelledError):
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
                object(),
                clock=lambda: at,
            )
        )

    assert [state.ledger.blocks[0].state for state in saved] == [
        BlockState.COMMITTING,
        BlockState.UNCERTAIN,
    ]
    assert {job.state for job in coordinator.state.ledger.jobs} == {JobState.UNCERTAIN}


def test_live_dispatch_double_cancellation_waits_for_blocked_quarantine_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.downstairs")
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
    service_started = asyncio.Event()
    quarantine_save_started = asyncio.Event()
    release_quarantine_save = asyncio.Event()
    save_attempt = 0

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            nonlocal save_attempt
            save_attempt += 1
            if save_attempt == 2:
                quarantine_save_started.set()
                await release_quarantine_save.wait()
            saved.append(state)

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            service_started.set()
            await asyncio.Event().wait()

    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        dry_run=False,
        coordinator=coordinator,
    )

    async def exercise_double_cancellation() -> None:
        dispatch = asyncio.create_task(
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
                object(),
                clock=lambda: at,
            )
        )
        await service_started.wait()
        dispatch.cancel()
        await quarantine_save_started.wait()
        dispatch.cancel()
        await asyncio.sleep(0)

        assert not dispatch.done()
        release_quarantine_save.set()
        with pytest.raises(asyncio.CancelledError):
            await dispatch

    asyncio.run(exercise_double_cancellation())

    assert [state.ledger.blocks[0].state for state in saved] == [
        BlockState.COMMITTING,
        BlockState.UNCERTAIN,
    ]
    assert {job.state for job in coordinator.state.ledger.jobs} == {JobState.UNCERTAIN}


def test_live_dispatch_cancellation_during_acceptance_is_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.downstairs")
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
    save_attempt = 0

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            nonlocal save_attempt
            save_attempt += 1
            if save_attempt == 2:
                raise asyncio.CancelledError
            saved.append(state)

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            return None

    vacuum_module = ModuleType("homeassistant.components.vacuum")
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=1024)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        dry_run=False,
        coordinator=coordinator,
    )

    with pytest.raises(asyncio.CancelledError):
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
                object(),
                clock=lambda: at,
            )
        )

    assert [state.ledger.blocks[0].state for state in saved] == [
        BlockState.COMMITTING,
        BlockState.UNCERTAIN,
    ]
    assert {job.state for job in coordinator.state.ledger.jobs} == {JobState.UNCERTAIN}


def test_live_dispatch_acceptance_save_failure_is_quarantined_and_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_resolve_command_vacuum", lambda *_args: "vacuum.downstairs")
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
    save_attempt = 0
    service_calls = 0

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            nonlocal save_attempt
            save_attempt += 1
            if save_attempt == 2:
                raise OSError("acceptance storage unavailable")
            saved.append(state)

    class Services:
        async def async_call(self, *_args: object, **_kwargs: object) -> None:
            nonlocal service_calls
            service_calls += 1

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

    with pytest.raises(
        StubServiceValidationError,
        match="Native area dispatch acceptance could not be persisted",
    ) as raised:
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
                object(),
                clock=lambda: at,
            )
        )

    assert service_calls == 1
    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "acceptance storage unavailable"
    assert save_attempt == 3
    assert [state.ledger.blocks[0].state for state in saved] == [
        BlockState.COMMITTING,
        BlockState.UNCERTAIN,
    ]
    assert {job.state for job in saved[-1].ledger.jobs} == {JobState.UNCERTAIN}
    assert coordinator.state == saved[-1]


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
    vacuum_module = ModuleType("homeassistant.components.vacuum")
    const_module = ModuleType("homeassistant.const")
    registry = SimpleNamespace(
        async_get=lambda _registry_id: SimpleNamespace(
            id="vacuum-registry-entry",
            entity_id="vacuum.renamed",
            options={"vacuum": {"area_mapping": {"kitchen": ["segment-7"]}}},
        )
    )
    vars(entity_registry_module)["async_get"] = lambda _hass: registry
    vars(vacuum_module)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=16384)
    vars(const_module)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["entity_registry"] = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module
    )
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)

    updated: list[dict[str, object]] = []
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 16384}
            )
        ),
        config_entries=SimpleNamespace(
            async_update_entry=lambda _entry, *, data: updated.append(data)
        ),
    )
    entry = SimpleNamespace(
        data={
            CONF_VACUUM_ENTITY_ID: "vacuum.old_name",
            CONF_AREA_IDS: ["kitchen"],
        },
        options={},
        unique_id="vacuum-registry-entry",
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data == VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.renamed",
        vacuum_registry_id="vacuum-registry-entry",
        configured_area_ids=("kitchen",),
    )
    assert updated == [
        {
            CONF_VACUUM_ENTITY_ID: "vacuum.renamed",
            CONF_AREA_IDS: ["kitchen"],
        }
    ]


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
        and plan.vacuum_and_mop_interval_days == 7
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
