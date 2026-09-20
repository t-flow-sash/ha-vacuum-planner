"""Public action buttons for Vacuum Planner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import CONF_CONFIG_ENTRY_ID, DOMAIN, VacuumPlannerRuntimeData
from .domain.models import BlockState

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the two standard-card planner controls."""
    async_add_entities(
        [VacuumPlannerStartNextButton(entry), VacuumPlannerCancelCurrentBlockButton(entry)]
    )


class VacuumPlannerButton(ButtonEntity):  # type: ignore[misc]
    """Base button attached to the planner service device."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData], key: str) -> None:
        super().__init__()
        self._entry_id = entry.entry_id
        self._runtime_data = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "entry_type": DeviceEntryType.SERVICE,
            "name": entry.title,
            "manufacturer": "Vacuum Planner",
        }

    async def _async_call(self, action: str, data: dict[str, object]) -> None:
        await self.hass.services.async_call(DOMAIN, action, data, blocking=True)


class VacuumPlannerStartNextButton(VacuumPlannerButton):
    """Invoke the canonical public one-tap action."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "start_next")

    async def async_press(self) -> None:
        """Start only the currently due work."""
        await self._async_call("start_next", {CONF_CONFIG_ENTRY_ID: self._entry_id})


class VacuumPlannerCancelCurrentBlockButton(VacuumPlannerButton):
    """Cancel the latest safely cancellable current block."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "cancel_current_block")

    async def async_press(self) -> None:
        """Invoke cancellation with an explicit block identity."""
        state = self._runtime_data.state
        block = (
            next(
                (item for item in reversed(state.ledger.blocks) if item.state is BlockState.SEALED),
                None,
            )
            if state is not None
            else None
        )
        if block is None:
            return
        await self._async_call(
            "cancel_block",
            {CONF_CONFIG_ENTRY_ID: self._entry_id, "block_id": block.block_id},
        )
