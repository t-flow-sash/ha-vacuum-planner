"""Native per-room number entities for Vacuum Planner plan settings."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING, ClassVar, Final
from uuid import uuid4

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import DOMAIN, VacuumPlannerRuntimeData
from .domain.models import PlannerState, PlanRevision, RoomPlan

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_MAX_INTERVAL_DAYS: Final = 365
_MAX_PRIORITY: Final = 2_147_483_647


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add three native planning numbers for every configured room."""
    state = entry.runtime_data.state
    if state is None:
        return
    async_add_entities(
        [
            entity_type(entry, room_plan.area_id)
            for room_plan in state.plan_revision.room_plans
            for entity_type in (
                VacuumPlannerVacuumIntervalNumber,
                VacuumPlannerVacuumAndMopIntervalNumber,
                VacuumPlannerPriorityNumber,
            )
        ]
    )


class VacuumPlannerRoomNumber(NumberEntity):  # type: ignore[misc]
    """Base for one in-memory room-plan number projection."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_unit_of_measurement: str | None = None
    _plan_field: ClassVar[str]

    def __init__(
        self,
        entry: ConfigEntry[VacuumPlannerRuntimeData],
        area_id: str,
        key: str,
    ) -> None:
        super().__init__()
        self._runtime_data: VacuumPlannerRuntimeData = entry.runtime_data
        self._area_id = area_id
        self._attr_unique_id = f"{entry.entry_id}_{area_id}_{key}"
        self._attr_translation_key = key
        area_names = entry.runtime_data.area_names or {}
        self._attr_translation_placeholders = {"area_name": area_names.get(area_id, area_id)}
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "entry_type": DeviceEntryType.SERVICE,
            "name": entry.title,
            "manufacturer": "Vacuum Planner",
        }

    def _room_plan(self) -> RoomPlan:
        state = self._runtime_data.state
        if state is None:
            raise RuntimeError("Vacuum Planner state is unavailable")
        return next(
            plan for plan in state.plan_revision.room_plans if plan.area_id == self._area_id
        )

    async def async_added_to_hass(self) -> None:
        """Refresh the entity after successfully persisted coordinator changes."""
        await super().async_added_to_hass()
        coordinator = self._runtime_data.coordinator
        if coordinator is not None:
            remove_listener: Callable[[], None] = coordinator.async_add_listener(
                self.async_write_ha_state
            )
            self.async_on_remove(remove_listener)

    def _replace_room_value(self, room: RoomPlan, value: int) -> RoomPlan:
        if self._plan_field == "vacuum_interval_days":
            return replace(room, vacuum_interval_days=value)
        if self._plan_field == "vacuum_and_mop_interval_days":
            return replace(room, vacuum_and_mop_interval_days=value)
        return replace(room, priority=value)

    async def async_set_native_value(self, value: float) -> None:
        """Persist a complete new plan revision through the shared command lock."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Vacuum Planner number values must be whole numbers")
        numeric_value = float(value)
        if not isfinite(numeric_value) or not numeric_value.is_integer():
            raise ValueError("Vacuum Planner number values must be whole numbers")
        integer_value = int(numeric_value)
        if not self._attr_native_min_value <= integer_value <= self._attr_native_max_value:
            raise ValueError("Vacuum Planner number value is outside the supported range")
        coordinator = self._runtime_data.coordinator
        if coordinator is None:
            raise RuntimeError("Vacuum Planner state is unavailable")
        command_generation = self._runtime_data.capture_command_generation()

        def update(state: PlannerState) -> PlannerState:
            current_revision = state.plan_revision
            room_plans = tuple(
                self._replace_room_value(room, integer_value)
                if room.area_id == self._area_id
                else room
                for room in current_revision.room_plans
            )
            if room_plans == current_revision.room_plans:
                return state
            created_at = max(
                datetime.now(UTC), current_revision.created_at + timedelta(microseconds=1)
            )
            return replace(
                state,
                plan_revision=PlanRevision(str(uuid4()), created_at, room_plans),
            )

        await coordinator.async_command(
            update,
            guard=lambda: self._runtime_data.require_command_generation(command_generation),
        )


class VacuumPlannerVacuumIntervalNumber(VacuumPlannerRoomNumber):
    """Configure the vacuum interval for one room."""

    _attr_native_min_value = 1
    _attr_native_max_value = _MAX_INTERVAL_DAYS
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _plan_field = "vacuum_interval_days"

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData], area_id: str) -> None:
        super().__init__(entry, area_id, "vacuum_interval")

    @property
    def native_value(self) -> int:
        """Project the authoritative vacuum interval."""
        return self._room_plan().vacuum_interval_days


class VacuumPlannerVacuumAndMopIntervalNumber(VacuumPlannerRoomNumber):
    """Configure the vacuum-and-mop interval for one room."""

    _attr_native_min_value = 1
    _attr_native_max_value = _MAX_INTERVAL_DAYS
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _plan_field = "vacuum_and_mop_interval_days"

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData], area_id: str) -> None:
        super().__init__(entry, area_id, "vacuum_and_mop_interval")

    @property
    def native_value(self) -> int | None:
        """Project the authoritative vacuum-and-mop interval."""
        return self._room_plan().vacuum_and_mop_interval_days


class VacuumPlannerPriorityNumber(VacuumPlannerRoomNumber):
    """Configure planning priority for one room."""

    _attr_native_min_value = 0
    _attr_native_max_value = _MAX_PRIORITY
    _plan_field = "priority"

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData], area_id: str) -> None:
        super().__init__(entry, area_id, "priority")

    @property
    def native_value(self) -> int:
        """Project the authoritative room priority."""
        return self._room_plan().priority
