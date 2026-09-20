import asyncio
import importlib
import sys
from dataclasses import replace
from datetime import UTC, datetime
from enum import Enum
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from custom_components.vacuum_planner.const import VacuumPlannerRuntimeData
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
    QueueLedger,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import start_due_block

NOW = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


class NullStore:
    async def async_save(self, _state: PlannerState) -> None:
        pass


def load_sensor_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:  # noqa: C901
    sensor_module = ModuleType("homeassistant.components.sensor")
    device_registry_module = ModuleType("homeassistant.helpers.device_registry")
    const_module = ModuleType("homeassistant.const")

    class SensorDeviceClass(Enum):
        ENUM = "enum"

    class SensorEntity:
        _attr_device_class: SensorDeviceClass
        _attr_unique_id: str
        _attr_options: list[str]
        _attr_translation_key: str
        _attr_has_entity_name: bool
        _attr_device_info: dict[str, object]

        def __init__(self) -> None:
            self.remove_callbacks: list[Any] = []
            self.write_count = 0

        @property
        def unique_id(self) -> str:
            return self._attr_unique_id

        @property
        def translation_key(self) -> str:
            return self._attr_translation_key

        @property
        def has_entity_name(self) -> bool:
            return self._attr_has_entity_name

        @property
        def device_info(self) -> dict[str, object]:
            return self._attr_device_info

        @property
        def device_class(self) -> SensorDeviceClass:
            return self._attr_device_class

        @property
        def options(self) -> list[str]:
            return self._attr_options

        def async_on_remove(self, callback: Any) -> None:
            self.remove_callbacks.append(callback)

        def async_write_ha_state(self) -> None:
            self.write_count += 1

        async def async_added_to_hass(self) -> None:
            pass

    vars(sensor_module)["SensorDeviceClass"] = SensorDeviceClass
    vars(sensor_module)["SensorEntity"] = SensorEntity
    vars(device_registry_module)["DeviceEntryType"] = SimpleNamespace(SERVICE="service")
    vars(const_module)["EntityCategory"] = SimpleNamespace(DIAGNOSTIC="diagnostic")
    monkeypatch.setitem(sys.modules, "homeassistant.components.sensor", sensor_module)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.device_registry", device_registry_module
    )
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)
    sys.modules.pop("custom_components.vacuum_planner.sensor", None)
    return importlib.import_module("custom_components.vacuum_planner.sensor")


def test_sensor_platform_adds_one_stable_planner_status_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor = load_sensor_module(monkeypatch)
    state = PlannerState(
        plan_revision=PlanRevision("revision-1", NOW, ()),
        ledger=QueueLedger.empty(),
    )
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        title="Downstairs",
        runtime_data=VacuumPlannerRuntimeData(
            vacuum_entity_id="vacuum.downstairs",
            coordinator=PlannerCoordinator(state, NullStore()),
        ),
    )
    entities: list[Any] = []

    asyncio.run(sensor.async_setup_entry(SimpleNamespace(), entry, entities.extend))

    assert len(entities) == 6
    by_key = {entity.translation_key: entity for entity in entities}
    assert set(by_key) == {
        "status",
        "next_action",
        "pending_count",
        "current_phase",
        "capability_tier",
        "queue",
    }
    assert {entity.unique_id for entity in entities} == {
        "planner-entry-1_status",
        "planner-entry-1_next_action",
        "planner-entry-1_pending_count",
        "planner-entry-1_current_phase",
        "planner-entry-1_capability_tier",
        "planner-entry-1_queue",
    }
    entity = by_key["status"]
    assert entity.translation_key == "status"
    assert entity.has_entity_name is True
    assert entity.device_class is sensor.SensorDeviceClass.ENUM
    assert entity.options == [
        "attention",
        "committing",
        "idle",
        "paused",
        "ready",
        "running",
    ]
    assert entity.native_value == "idle"
    assert entity.device_info == {
        "identifiers": {("vacuum_planner", "planner-entry-1")},
        "entry_type": "service",
        "name": "Downstairs",
        "manufacturer": "Vacuum Planner",
    }
    queue = by_key["queue"]
    assert queue.native_value == 0
    assert queue.extra_state_attributes == {
        "items": [],
        "projected_count": 0,
        "revision": 0,
        "total_count": 0,
        "truncated": False,
    }


def test_queue_sensor_reflects_coordinator_changes_without_reloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> tuple[dict[str, object], dict[str, object], dict[str, object], int]:
        sensor = load_sensor_module(monkeypatch)
        state = PlannerState(PlanRevision("revision-1", NOW, ()), QueueLedger.empty())
        coordinator = PlannerCoordinator(state, NullStore())
        entry = SimpleNamespace(
            entry_id="planner-entry-1",
            title="Downstairs",
            runtime_data=VacuumPlannerRuntimeData(
                vacuum_entity_id="vacuum.downstairs",
                coordinator=coordinator,
            ),
        )
        entity = sensor.VacuumPlannerQueueSensor(entry)
        await entity.async_added_to_hass()
        before = entity.extra_state_attributes
        ids = iter(("block", "job"))
        result = start_due_block(
            state.ledger,
            PlanSnapshot(
                "revision-1",
                "lane",
                NOW,
                (SnapshotJob("kitchen", "Kitchen", 7, Mode.VACUUM, 1, NOW),),
            ),
            "lane",
            "key",
            NOW,
            lambda: next(ids),
            DispatchStrategy.PLANNER_SEQUENTIAL,
            BlockGuarantee.PLANNER_ATOMIC,
        )
        await coordinator.async_command(lambda current: replace(current, ledger=result.ledger))
        pending = entity.extra_state_attributes
        ledger = result.ledger
        ledger = ledger.replace_block_state("block", BlockState.COMMITTING, NOW)
        ledger = ledger.replace_block_state("block", BlockState.COMMITTED, NOW)
        ledger = ledger.replace_job_state("job", JobState.DISPATCHING, NOW)
        ledger = ledger.replace_job_state("job", JobState.ACCEPTED, NOW)
        ledger = ledger.replace_job_state("job", JobState.RUNNING, NOW)
        ledger = ledger.replace_job_state("job", JobState.COMPLETED, NOW)
        await coordinator.async_command(lambda current: replace(current, ledger=ledger))
        return before, pending, entity.extra_state_attributes, entity.write_count

    before, pending, completed, writes = asyncio.run(exercise())

    assert before["items"] == []
    assert pending["items"] == [
        {"area_name": "Kitchen", "mode": "vacuum", "position": 0, "status": "pending"}
    ]
    assert completed["items"] == [
        {"area_name": "Kitchen", "mode": "vacuum", "position": 0, "status": "completed"}
    ]
    assert pending["revision"] == 1
    assert completed["revision"] == 7
    assert writes == 2


def test_status_sensor_refreshes_only_after_coordinator_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> tuple[int, int]:
        sensor = load_sensor_module(monkeypatch)
        state = PlannerState(
            plan_revision=PlanRevision("revision-1", NOW, ()),
            ledger=QueueLedger.empty(),
        )
        coordinator = PlannerCoordinator(state, NullStore())
        entry = SimpleNamespace(
            entry_id="planner-entry-1",
            title="Downstairs",
            runtime_data=VacuumPlannerRuntimeData(
                vacuum_entity_id="vacuum.downstairs",
                coordinator=coordinator,
            ),
        )
        entity = sensor.VacuumPlannerStatusSensor(entry)
        await entity.async_added_to_hass()
        before = entity.write_count
        await coordinator.async_command(
            lambda current: replace(
                current,
                ledger=replace(current.ledger, revision=current.ledger.revision + 1),
            )
        )
        return before, entity.write_count

    before, after = asyncio.run(exercise())

    assert before == 0
    assert after == 1
