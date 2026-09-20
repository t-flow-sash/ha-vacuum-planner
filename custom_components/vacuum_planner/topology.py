"""Shared fail-closed validation for configured vacuum topology."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class RegistryEntry(Protocol):
    """Entity-registry fields needed for topology validation."""

    id: str
    entity_id: str
    options: Mapping[str, object]


class _EntityRegistry(Protocol):
    def async_get(self, entity_id_or_registry_id: str) -> RegistryEntry | None: ...


class _EntityRegistryModule(Protocol):
    def async_get(self, hass: HomeAssistant) -> _EntityRegistry: ...


def async_get_valid_vacuum(
    hass: HomeAssistant, entity_id_or_registry_id: str
) -> tuple[RegistryEntry | None, str | None]:
    """Resolve a registered vacuum and strictly require CLEAN_AREA support."""
    entity_registry = cast(
        "_EntityRegistryModule", import_module("homeassistant.helpers.entity_registry")
    )
    vacuum = import_module("homeassistant.components.vacuum")
    ha_const = import_module("homeassistant.const")
    registry_entry = entity_registry.async_get(hass).async_get(entity_id_or_registry_id)
    if registry_entry is None or not isinstance(registry_entry.entity_id, str):
        return None, "entity_not_found"
    state = hass.states.get(registry_entry.entity_id)
    if state is None or state.state in {"unknown", "unavailable"}:
        return None, "entity_not_found"
    supported_features = state.attributes.get(ha_const.ATTR_SUPPORTED_FEATURES)
    if (
        type(supported_features) is not int
        or supported_features < 0
        or not supported_features & int(vacuum.VacuumEntityFeature.CLEAN_AREA)
    ):
        return None, "clean_area_unsupported"
    return registry_entry, None


def area_mapping(registry_entry: RegistryEntry) -> Mapping[str, object] | None:
    """Return the nested HA vacuum area mapping when structurally valid."""
    options = registry_entry.options
    vacuum_options = options.get("vacuum") if isinstance(options, Mapping) else None
    mapping = vacuum_options.get("area_mapping") if isinstance(vacuum_options, Mapping) else None
    return mapping if isinstance(mapping, Mapping) else None


def validate_area_ids(
    selected_area_ids: Sequence[str], registry_entry: RegistryEntry
) -> str | None:
    """Validate ordered, unique areas and their non-empty string segment mappings."""
    if not selected_area_ids:
        return "areas_required"
    if len(selected_area_ids) != len(set(selected_area_ids)):
        return "areas_duplicate"
    mapping = area_mapping(registry_entry)
    if mapping is None or any(
        not isinstance(segments := mapping.get(area_id), list)
        or not segments
        or any(not isinstance(segment_id, str) or not segment_id.strip() for segment_id in segments)
        for area_id in selected_area_ids
    ):
        return "areas_not_mapped"
    return None
