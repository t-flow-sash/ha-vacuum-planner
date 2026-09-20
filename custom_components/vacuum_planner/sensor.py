"""Sensor platform for Vacuum Planner."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import DOMAIN, VacuumPlannerRuntimeData
from .entity import (
    capability_tier,
    current_phase,
    next_action,
    pending_count,
    planner_status,
    queue_projection,
)

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
    """Add stable planner service projections for one config entry."""
    async_add_entities(
        [
            VacuumPlannerStatusSensor(entry),
            VacuumPlannerNextActionSensor(entry),
            VacuumPlannerPendingCountSensor(entry),
            VacuumPlannerCurrentPhaseSensor(entry),
            VacuumPlannerCapabilityTierSensor(entry),
            VacuumPlannerQueueSensor(entry),
        ]
    )


class VacuumPlannerSensor(SensorEntity):  # type: ignore[misc]
    """Base for in-memory sensors attached to one planner service device."""

    _attr_has_entity_name = True

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
        """Subscribe to coordinator updates while the entity is loaded."""
        await super().async_added_to_hass()
        coordinator = self._runtime_data.coordinator
        if coordinator is not None:
            remove_listener: Callable[[], None] = coordinator.async_add_listener(
                self.async_write_ha_state
            )
            self.async_on_remove(remove_listener)


class VacuumPlannerStatusSensor(VacuumPlannerSensor):
    """Expose the persisted planner lifecycle as an in-memory sensor."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        "attention",
        "committing",
        "idle",
        "paused",
        "ready",
        "running",
    ]

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "status")

    @property
    def native_value(self) -> str:
        """Return the current planner status without I/O."""
        return planner_status(self._runtime_data)


class VacuumPlannerNextActionSensor(VacuumPlannerSensor):
    """Expose a compact human-readable next due action."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "next_action")

    @property
    def native_value(self) -> str | None:
        """Return area and normalized mode from memory."""
        action = next_action(self._runtime_data)
        if action is None:
            return None
        if action.get("status") == "blocked":
            return "Blocked · reload required"
        return f"{action['area_name']} · {action['mode']}"

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the small public next-action projection."""
        return next_action(self._runtime_data)


class VacuumPlannerPendingCountSensor(VacuumPlannerSensor):
    """Expose the number of nonterminal planner jobs."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "pending_count")

    @property
    def native_value(self) -> int:
        """Return the in-memory pending count."""
        return pending_count(self._runtime_data)


class VacuumPlannerQueueSensor(VacuumPlannerSensor):
    """Expose a bounded, safe queue projection for standard Lovelace cards."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "queue")

    @property
    def native_value(self) -> int:
        """Return the total queue size, including rows outside the projection limit."""
        return queue_projection(self._runtime_data)["total_count"]

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return ordered public rows without private adapter or persistence identifiers."""
        return dict(queue_projection(self._runtime_data))


class VacuumPlannerCurrentPhaseSensor(VacuumPlannerSensor):
    """Expose the current block phase."""

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "current_phase")

    @property
    def native_value(self) -> str:
        """Return the latest open block phase."""
        return current_phase(self._runtime_data)


class VacuumPlannerCapabilityTierSensor(VacuumPlannerSensor):
    """Expose the setup-time capability tier as disabled-by-default diagnostics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: ConfigEntry[VacuumPlannerRuntimeData]) -> None:
        super().__init__(entry, "capability_tier")

    @property
    def native_value(self) -> str:
        """Return the setup-time capability tier."""
        return capability_tier(self._runtime_data)
