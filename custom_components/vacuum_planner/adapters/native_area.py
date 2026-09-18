"""Native Home Assistant ``vacuum.clean_area`` transport."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from homeassistant.core import Context


class _ServiceRegistry(Protocol):
    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, object],
        *,
        target: dict[str, object],
        blocking: bool,
        context: Context,
    ) -> None: ...


class _State(Protocol):
    state: str
    attributes: dict[str, object]


class _StateMachine(Protocol):
    def get(self, entity_id: str) -> _State | None: ...


class _HomeAssistant(Protocol):
    services: _ServiceRegistry
    states: _StateMachine


class _VacuumFeature(Protocol):
    CLEAN_AREA: int


class _VacuumModule(Protocol):
    VacuumEntityFeature: _VacuumFeature


class NativeAreaAdapter:
    """Dispatch ordered HA Area IDs through Home Assistant's public vacuum action."""

    def __init__(self, hass: _HomeAssistant, vacuum_entity_id: str) -> None:
        self._hass = hass
        self._vacuum_entity_id = vacuum_entity_id

    async def async_dispatch(
        self,
        area_ids: tuple[str, ...],
        context: Context,
    ) -> None:
        """Request one ordered native area-cleaning operation."""
        state = self._hass.states.get(self._vacuum_entity_id)
        if state is None or state.state in {"unknown", "unavailable"}:
            raise ValueError("configured vacuum is unavailable")
        vacuum = cast(
            "_VacuumModule",
            import_module("homeassistant.components.vacuum"),
        )
        supported_features = state.attributes.get("supported_features")
        if not isinstance(supported_features, int) or not (
            supported_features & int(vacuum.VacuumEntityFeature.CLEAN_AREA)
        ):
            raise ValueError("configured vacuum no longer supports CLEAN_AREA")
        await self._hass.services.async_call(
            "vacuum",
            "clean_area",
            {"cleaning_area_id": list(area_ids)},
            target={"entity_id": self._vacuum_entity_id},
            blocking=True,
            context=context,
        )
