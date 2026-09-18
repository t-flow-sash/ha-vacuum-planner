"""Native Home Assistant ``vacuum.clean_area`` transport."""

from __future__ import annotations

from typing import Protocol


class _ServiceRegistry(Protocol):
    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, object],
        *,
        target: dict[str, object],
        blocking: bool,
    ) -> None: ...


class _HomeAssistant(Protocol):
    services: _ServiceRegistry


class NativeAreaAdapter:
    """Dispatch ordered HA Area IDs through Home Assistant's public vacuum action."""

    def __init__(self, hass: _HomeAssistant, vacuum_entity_id: str) -> None:
        self._hass = hass
        self._vacuum_entity_id = vacuum_entity_id

    async def async_dispatch(self, area_ids: tuple[str, ...]) -> None:
        """Request one ordered native area-cleaning operation."""
        await self._hass.services.async_call(
            "vacuum",
            "clean_area",
            {"cleaning_area_id": list(area_ids)},
            target={"entity_id": self._vacuum_entity_id},
            blocking=True,
        )
