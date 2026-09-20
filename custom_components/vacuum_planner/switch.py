"""Planning preference switch for Vacuum Planner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import CONF_PLANNING_ENABLED, DOMAIN, VacuumPlannerRuntimeData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the planning preference switch."""
    async_add_entities([VacuumPlannerPlanningSwitch(entry)])


class VacuumPlannerPlanningSwitch(SwitchEntity):  # type: ignore[misc]
    """Control automatic planning without reading properties from HA."""

    _attr_has_entity_name = True
    _attr_translation_key = "planning"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__()
        self._entry = entry
        self._runtime_data = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_planning"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "entry_type": DeviceEntryType.SERVICE,
            "name": entry.title,
            "manufacturer": "Vacuum Planner",
        }

    @property
    def is_on(self) -> bool:
        """Return the in-memory planning preference."""
        return bool(self._runtime_data.planning_enabled)

    async def _async_set_enabled(self, *, enabled: bool) -> None:
        previous_options = dict(self._entry.options)
        updated_options = {**previous_options, CONF_PLANNING_ENABLED: enabled}

        def commit() -> None:
            self.hass.config_entries.async_update_entry(self._entry, options=updated_options)

        def rollback() -> None:
            self.hass.config_entries.async_update_entry(self._entry, options=previous_options)

        await self._runtime_data.async_set_planning_enabled(
            enabled=enabled,
            commit=commit,
            rollback=rollback,
        )

    async def async_turn_on(self, **_kwargs: object) -> None:
        """Enable planning through the shared coordinator lock."""
        await self._async_set_enabled(enabled=True)

    async def async_turn_off(self, **_kwargs: object) -> None:
        """Pause planning through the shared coordinator lock."""
        await self._async_set_enabled(enabled=False)
