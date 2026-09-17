"""Vacuum Planner custom integration package."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from .const import CONF_VACUUM_ENTITY_ID, VacuumPlannerRuntimeData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class _RegistryEntry(Protocol):
    entity_id: str


class _EntityRegistry(Protocol):
    def async_get(self, entity_id_or_uuid: str) -> _RegistryEntry | None: ...


class _EntityRegistryModule(Protocol):
    def async_get(self, hass: HomeAssistant) -> _EntityRegistry: ...


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> bool:
    """Set up Vacuum Planner from a config entry without device side effects."""
    vacuum_entity_id = entry.data[CONF_VACUUM_ENTITY_ID]
    if entry.unique_id is not None:
        er = cast(
            "_EntityRegistryModule",
            import_module("homeassistant.helpers.entity_registry"),
        )
        registry_entry = er.async_get(hass).async_get(entry.unique_id)
        if registry_entry is not None:
            vacuum_entity_id = registry_entry.entity_id
            if vacuum_entity_id != entry.data[CONF_VACUUM_ENTITY_ID]:
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_VACUUM_ENTITY_ID: vacuum_entity_id},
                )
    entry.runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id=vacuum_entity_id
    )
    return True


async def async_unload_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> bool:
    """Unload a Vacuum Planner config entry."""
    entry.runtime_data = None
    return True
