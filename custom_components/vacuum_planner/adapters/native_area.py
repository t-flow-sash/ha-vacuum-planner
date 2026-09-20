"""Native Home Assistant ``vacuum.clean_area`` transport."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from custom_components.vacuum_planner.domain.models import Mode

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import Context


_VENDOR_PLATFORMS = frozenset({"dreame_vacuum", "mova"})
_MODE_OPTIONS = frozenset({"Vacuum", "Vacuum and Mop"})


def find_dreame_mova_cleaning_mode_entity(
    hass: _HomeAssistant,
    vacuum_registry_id: str | None,
) -> str | None:
    """Return a verified vendor mode selector, otherwise fail closed."""
    if vacuum_registry_id is None:
        return None
    registry_module = import_module("homeassistant.helpers.entity_registry")
    registry = registry_module.async_get(hass)
    vacuum_entry = registry.async_get(vacuum_registry_id)
    device_id = getattr(vacuum_entry, "device_id", None)
    if (
        vacuum_entry is None
        or getattr(vacuum_entry, "platform", None) not in _VENDOR_PLATFORMS
        or not isinstance(device_id, str)
    ):
        return None
    entries_for_device = getattr(registry_module, "async_entries_for_device", None)
    if not callable(entries_for_device):
        return None
    for entry in entries_for_device(registry, device_id):
        unique_id = getattr(entry, "unique_id", "")
        if (
            getattr(entry, "domain", None) != "select"
            or not isinstance(unique_id, str)
            or "cleaning_mode" not in unique_id.lower()
            or getattr(entry, "disabled", False)
            or getattr(entry, "disabled_by", None) is not None
        ):
            continue
        entity_id = getattr(entry, "entity_id", None)
        state = hass.states.get(entity_id) if isinstance(entity_id, str) else None
        options = None if state is None else state.attributes.get("options")
        if (
            state is not None
            and state.state not in {"unknown", "unavailable"}
            and isinstance(options, list)
            and _MODE_OPTIONS.issubset(options)
        ):
            return entity_id
    return None


def resolve_bound_cleaning_mode_entity(
    hass: _HomeAssistant,
    cleaning_mode_registry_id: str | None,
) -> str | None:
    """Resolve and validate only the cleaning-mode selector bound at setup."""
    if cleaning_mode_registry_id is None:
        return None
    registry_module = import_module("homeassistant.helpers.entity_registry")
    entry = registry_module.async_get(hass).async_get(cleaning_mode_registry_id)
    entity_id = getattr(entry, "entity_id", None)
    unique_id = getattr(entry, "unique_id", "")
    if (
        entry is None
        or getattr(entry, "id", None) != cleaning_mode_registry_id
        or getattr(entry, "domain", None) != "select"
        or not isinstance(unique_id, str)
        or "cleaning_mode" not in unique_id.lower()
        or getattr(entry, "disabled", False)
        or getattr(entry, "disabled_by", None) is not None
        or not isinstance(entity_id, str)
    ):
        return None
    state = hass.states.get(entity_id)
    options = None if state is None else state.attributes.get("options")
    if (
        state is None
        or state.state in {"unknown", "unavailable"}
        or not isinstance(options, list)
        or not _MODE_OPTIONS.issubset(options)
    ):
        return None
    return entity_id


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

    def __init__(
        self,
        hass: _HomeAssistant,
        vacuum_entity_id: str,
        *,
        cleaning_mode_entity_id: str | None = None,
        before_side_effect: Callable[[], None] | None = None,
    ) -> None:
        self._hass = hass
        self._vacuum_entity_id = vacuum_entity_id
        self._cleaning_mode_entity_id = cleaning_mode_entity_id
        self._before_side_effect = before_side_effect

    def preflight(self, modes: tuple[Mode, ...] = ()) -> str | None:
        """Validate local state before any external service call can begin."""
        state = self._hass.states.get(self._vacuum_entity_id)
        if state is None or state.state in {"unknown", "unavailable"}:
            raise ValueError("configured vacuum is unavailable")
        vacuum = cast(
            "_VacuumModule",
            import_module("homeassistant.components.vacuum"),
        )
        supported_features = state.attributes.get("supported_features")
        if (
            type(supported_features) is not int
            or supported_features < 0
            or not (supported_features & int(vacuum.VacuumEntityFeature.CLEAN_AREA))
        ):
            raise ValueError("configured vacuum no longer supports CLEAN_AREA")
        requested_modes = frozenset(modes or (Mode.VACUUM,))
        if len(requested_modes) != 1:
            raise ValueError("native area batch requires one homogeneous cleaning mode")
        requested_mode = next(iter(requested_modes))
        if self._cleaning_mode_entity_id is None:
            if requested_mode is Mode.VACUUM_AND_MOP:
                raise ValueError("vacuum_and_mop requires a confirmed Dreame/Mova mode selector")
            return None
        mode_state = self._hass.states.get(self._cleaning_mode_entity_id)
        options = None if mode_state is None else mode_state.attributes.get("options")
        expected = "Vacuum and Mop" if requested_mode is Mode.VACUUM_AND_MOP else "Vacuum"
        if (
            mode_state is None
            or not isinstance(options, list)
            or expected not in options
            or mode_state.state in {"unknown", "unavailable"}
        ):
            raise ValueError(f"cleaning mode selector does not confirm {expected}")
        return expected

    async def async_dispatch(
        self,
        area_ids: tuple[str, ...],
        context: Context,
        *,
        modes: tuple[Mode, ...] = (),
    ) -> None:
        """Validate and request one ordered native area-cleaning operation."""
        mode_option = self.preflight(modes)
        await self.async_dispatch_after_preflight(area_ids, context, mode_option=mode_option)

    async def async_dispatch_after_preflight(
        self,
        area_ids: tuple[str, ...],
        context: Context,
        *,
        mode_option: str | None = None,
    ) -> None:
        """Begin the external call after a successful local preflight."""
        if mode_option is not None and self._cleaning_mode_entity_id is not None:
            if self._before_side_effect is not None:
                self._before_side_effect()
            await self._hass.services.async_call(
                "select",
                "select_option",
                {"option": mode_option},
                target={"entity_id": self._cleaning_mode_entity_id},
                blocking=True,
                context=context,
            )
        if self._before_side_effect is not None:
            self._before_side_effect()
        await self._hass.services.async_call(
            "vacuum",
            "clean_area",
            {"cleaning_area_id": list(area_ids)},
            target={"entity_id": self._vacuum_entity_id},
            blocking=True,
            context=context,
        )
