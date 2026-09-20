"""Diagnostic binary sensors for Vacuum Planner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import DOMAIN, VacuumPlannerRuntimeData
from .entity import attention_required, planner_ready

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
    """Add readiness and attention projections."""
    async_add_entities(
        [VacuumPlannerReadyBinarySensor(entry), VacuumPlannerAttentionBinarySensor(entry)]
    )


class VacuumPlannerBinarySensor(BinarySensorEntity):  # type: ignore[misc]
    """Base diagnostic sensor attached to the planner service device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData], key: str) -> None:
        super().__init__()
        self._runtime_data = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "entry_type": DeviceEntryType.SERVICE,
            "name": entry.title,
            "manufacturer": "Vacuum Planner",
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to published coordinator changes."""
        await super().async_added_to_hass()
        coordinator = self._runtime_data.coordinator
        if coordinator is not None:
            remove: Callable[[], None] = coordinator.async_add_listener(self.async_write_ha_state)
            self.async_on_remove(remove)


class VacuumPlannerReadyBinarySensor(VacuumPlannerBinarySensor):
    """Expose whether planner commands are currently safe to attempt."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "ready")

    @property
    def is_on(self) -> bool:
        """Return readiness from memory."""
        return planner_ready(self._runtime_data)


class VacuumPlannerAttentionBinarySensor(VacuumPlannerBinarySensor):
    """Expose unresolved or invalid planner state."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "attention")

    @property
    def is_on(self) -> bool:
        """Return attention state from memory."""
        return attention_required(self._runtime_data)
