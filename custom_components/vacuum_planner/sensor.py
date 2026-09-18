"""Sensor platform for Vacuum Planner."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import DOMAIN, VacuumPlannerRuntimeData
from .entity import planner_status

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the planner status projection for one config entry."""
    async_add_entities([VacuumPlannerStatusSensor(entry)])


class VacuumPlannerStatusSensor(SensorEntity):  # type: ignore[misc]
    """Expose the persisted planner lifecycle as an in-memory sensor."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_has_entity_name = True
    _attr_options: ClassVar[list[str]] = [
        "attention",
        "committing",
        "idle",
        "paused",
        "ready",
        "running",
    ]
    _attr_translation_key = "status"

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__()
        self._runtime_data = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "entry_type": DeviceEntryType.SERVICE,
            "name": entry.title,
            "manufacturer": "Vacuum Planner",
        }

    @property
    def native_value(self) -> str:
        """Return the current planner status without I/O."""
        return planner_status(self._runtime_data)

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates while the entity is loaded."""
        await super().async_added_to_hass()
        coordinator = self._runtime_data.coordinator
        if coordinator is not None:
            remove_listener: Callable[[], None] = coordinator.async_add_listener(
                self.async_write_ha_state
            )
            self.async_on_remove(remove_listener)
