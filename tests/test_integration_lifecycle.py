import asyncio
import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from custom_components.vacuum_planner import async_setup_entry, async_unload_entry
from custom_components.vacuum_planner.const import (
    CONF_AREA_IDS,
    CONF_PLANNING_ENABLED,
    CONF_VACUUM_ENTITY_ID,
    DOMAIN,
    VacuumPlannerRuntimeData,
)
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
