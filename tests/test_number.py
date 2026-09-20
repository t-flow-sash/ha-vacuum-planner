import asyncio
import importlib
import sys
from datetime import UTC, datetime
from enum import Enum
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from custom_components.vacuum_planner.const import PLATFORMS, VacuumPlannerRuntimeData
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import (
    PlannerState,
    PlanRevision,
    PreferredMode,
    QueueLedger,
    RoomPlan,
)

NOW = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)


class RecordingStore:
    def __init__(self) -> None:
        self.saved: list[PlannerState] = []
        self.fail = False
        self.coordinator: PlannerCoordinator | None = None
        self.state_during_save: PlannerState | None = None

    async def async_save(self, state: PlannerState) -> None:
        if self.coordinator is not None:
            self.state_during_save = self.coordinator.state
        if self.fail:
            raise OSError("store unavailable")
        self.saved.append(state)


def planner_state(*, second_room: bool = False) -> PlannerState:
    rooms = [
        RoomPlan(
            area_id="kitchen",
            lane_id="lane-1",
            enabled=True,
            vacuum_interval_days=2,
            vacuum_and_mop_interval_days=7,
            preferred_mode=PreferredMode.VACUUM_AND_MOP,
            priority=10,
        )
    ]
    if second_room:
        rooms.append(
            RoomPlan(
                area_id="hallway",
                lane_id="lane-1",
                enabled=True,
                vacuum_interval_days=3,
                vacuum_and_mop_interval_days=8,
                preferred_mode=PreferredMode.VACUUM,
                priority=20,
            )
        )
    return PlannerState(PlanRevision("revision-1", NOW, tuple(rooms)), QueueLedger.empty())


def load_number_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:  # noqa: C901
    number_module = ModuleType("homeassistant.components.number")
    device_module = ModuleType("homeassistant.helpers.device_registry")
    const_module = ModuleType("homeassistant.const")

    class NumberMode(Enum):
        BOX = "box"

    class NumberEntity:
        _attr_device_info: dict[str, object]
        _attr_mode: NumberMode
        _attr_native_max_value: float
        _attr_native_min_value: float
        _attr_native_step: float
        _attr_native_unit_of_measurement: str | None
        _attr_translation_key: str
        _attr_translation_placeholders: dict[str, str]
        _attr_unique_id: str

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
        def translation_placeholders(self) -> dict[str, str]:
            return self._attr_translation_placeholders

        @property
        def device_info(self) -> dict[str, object]:
            return self._attr_device_info

        @property
        def native_min_value(self) -> float:
            return self._attr_native_min_value

        @property
        def native_max_value(self) -> float:
            return self._attr_native_max_value

        @property
        def native_step(self) -> float:
            return self._attr_native_step

        @property
        def native_unit_of_measurement(self) -> str | None:
            return self._attr_native_unit_of_measurement

        @property
        def mode(self) -> NumberMode:
            return self._attr_mode

        def async_on_remove(self, callback: Any) -> None:
            self.remove_callbacks.append(callback)

        def async_write_ha_state(self) -> None:
            self.write_count += 1

        async def async_added_to_hass(self) -> None:
            pass

    vars(number_module)["NumberEntity"] = NumberEntity
    vars(number_module)["NumberMode"] = NumberMode
    vars(device_module)["DeviceEntryType"] = SimpleNamespace(SERVICE="service")
    vars(const_module)["EntityCategory"] = SimpleNamespace(CONFIG="config")
    vars(const_module)["UnitOfTime"] = SimpleNamespace(DAYS="d")
    monkeypatch.setitem(sys.modules, "homeassistant.components.number", number_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.device_registry", device_module)
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)
    sys.modules.pop("custom_components.vacuum_planner.number", None)
    return importlib.import_module("custom_components.vacuum_planner.number")


def make_entry(
    state: PlannerState,
    store: RecordingStore,
    *,
    entry_id: str = "planner-entry-1",
) -> Any:
    return SimpleNamespace(
        entry_id=entry_id,
        title="Downstairs",
        runtime_data=VacuumPlannerRuntimeData(
            vacuum_entity_id="vacuum.downstairs",
            coordinator=PlannerCoordinator(state, store),
            area_names={"kitchen": "Kitchen", "hallway": "Hallway"},
        ),
    )


def test_number_platform_is_forwarded_and_unloaded_with_config_entry() -> None:
    assert PLATFORMS == ("sensor", "switch", "binary_sensor", "button", "number")


def test_number_platform_projects_three_native_config_entities_per_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    number = load_number_module(monkeypatch)
    entry = make_entry(planner_state(second_room=True), RecordingStore())
    entities: list[Any] = []

    asyncio.run(number.async_setup_entry(SimpleNamespace(), entry, entities.extend))

    assert len(entities) == 6
    assert {entity.unique_id for entity in entities} == {
        f"planner-entry-1_{area_id}_{key}"
        for area_id in ("kitchen", "hallway")
        for key in ("vacuum_interval", "vacuum_and_mop_interval", "priority")
    }
    kitchen = {
        entity.translation_key: entity
        for entity in entities
        if entity.translation_placeholders == {"area_name": "Kitchen"}
    }
    assert set(kitchen) == {"vacuum_interval", "vacuum_and_mop_interval", "priority"}
    assert kitchen["vacuum_interval"].native_value == 2
    assert kitchen["vacuum_and_mop_interval"].native_value == 7
    assert kitchen["priority"].native_value == 10
    assert kitchen["vacuum_interval"].native_min_value == 1
    assert kitchen["vacuum_interval"].native_max_value == 365
    assert kitchen["vacuum_interval"].native_step == 1
    assert kitchen["vacuum_interval"].native_unit_of_measurement == "d"
    assert kitchen["priority"].native_min_value == 0
    assert kitchen["priority"].native_step == 1
    assert kitchen["priority"].native_unit_of_measurement is None
    assert all(entity.mode is number.NumberMode.BOX for entity in entities)
    assert all(
        entity.device_info
        == {
            "identifiers": {("vacuum_planner", "planner-entry-1")},
            "entry_type": "service",
            "name": "Downstairs",
            "manufacturer": "Vacuum Planner",
        }
        for entity in entities
    )


def test_number_write_revises_and_persists_complete_plan_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> tuple[PlannerState, PlannerState, RecordingStore, int]:
        number = load_number_module(monkeypatch)
        initial = planner_state(second_room=True)
        store = RecordingStore()
        entry = make_entry(initial, store)
        coordinator = entry.runtime_data.coordinator
        assert coordinator is not None
        store.coordinator = coordinator
        entity = number.VacuumPlannerVacuumIntervalNumber(entry, "kitchen")
        await entity.async_added_to_hass()

        await entity.async_set_native_value(5.0)

        return initial, coordinator.state, store, entity.write_count

    initial, updated, store, write_count = asyncio.run(exercise())

    assert store.state_during_save is initial
    assert store.saved == [updated]
    assert updated is not initial
    assert updated.ledger is initial.ledger
    assert updated.plan_revision.revision_id != initial.plan_revision.revision_id
    assert updated.plan_revision.created_at > initial.plan_revision.created_at
    assert updated.plan_revision.room_plans[0].vacuum_interval_days == 5
    assert updated.plan_revision.room_plans[1] is initial.plan_revision.room_plans[1]
    assert write_count == 1


def test_number_save_failure_keeps_runtime_projection_and_entity_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> tuple[PlannerState, PlannerState, RecordingStore, int]:
        number = load_number_module(monkeypatch)
        initial = planner_state()
        store = RecordingStore()
        store.fail = True
        entry = make_entry(initial, store)
        coordinator = entry.runtime_data.coordinator
        assert coordinator is not None
        entity = number.VacuumPlannerPriorityNumber(entry, "kitchen")
        await entity.async_added_to_hass()

        with pytest.raises(OSError, match="store unavailable"):
            await entity.async_set_native_value(50.0)

        return initial, coordinator.state, store, entity.write_count

    initial, published, store, write_count = asyncio.run(exercise())

    assert published is initial
    assert published.plan_revision.room_plans[0].priority == 10
    assert store.saved == []
    assert write_count == 0


@pytest.mark.parametrize("value", [True, 1.5, 0.0, 366.0])
def test_interval_number_rejects_non_integer_and_out_of_range_values(
    monkeypatch: pytest.MonkeyPatch,
    value: Any,
) -> None:
    async def exercise() -> None:
        number = load_number_module(monkeypatch)
        store = RecordingStore()
        entry = make_entry(planner_state(), store)
        entity = number.VacuumPlannerVacuumIntervalNumber(entry, "kitchen")

        with pytest.raises(ValueError, match=r"whole numbers|outside the supported range"):
            await entity.async_set_native_value(value)

        assert entry.runtime_data.state is not None
        assert entry.runtime_data.state.plan_revision.room_plans[0].vacuum_interval_days == 2
        assert store.saved == []

    asyncio.run(exercise())
