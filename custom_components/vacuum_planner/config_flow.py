"""Config flow for Vacuum Planner."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components.vacuum import VacuumEntityFeature
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import CONF_AREA_IDS, CONF_VACUUM_ENTITY_ID, DOMAIN


class VacuumPlannerConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg, misc]
    """Configure one Vacuum Planner entry for one existing vacuum entity."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient onboarding state."""
        super().__init__()
        self._vacuum_registry_id: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select the vacuum entity managed by this planner entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            vacuum_entity_id = user_input[CONF_VACUUM_ENTITY_ID]
            state = self.hass.states.get(vacuum_entity_id)
            registry_entry = er.async_get(self.hass).async_get(vacuum_entity_id)
            if state is None or registry_entry is None:
                errors[CONF_VACUUM_ENTITY_ID] = "entity_not_found"
            else:
                supported_features = state.attributes.get(ATTR_SUPPORTED_FEATURES)
                if (
                    type(supported_features) is not int
                    or supported_features < 0
                    or not supported_features & int(VacuumEntityFeature.CLEAN_AREA)
                ):
                    errors[CONF_VACUUM_ENTITY_ID] = "clean_area_unsupported"
                else:
                    await self.async_set_unique_id(registry_entry.id)
                    self._abort_if_unique_id_configured(
                        updates={CONF_VACUUM_ENTITY_ID: vacuum_entity_id}
                    )
                    self._vacuum_registry_id = registry_entry.id
                    return await self.async_step_areas()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VACUUM_ENTITY_ID): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="vacuum",
                            multiple=False,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_areas(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select ordered Home Assistant areas for this planner."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._vacuum_registry_id is None:
                return self.async_abort(reason="invalid_flow_state")
            registry_entry = er.async_get(self.hass).async_get(self._vacuum_registry_id)
            if (
                registry_entry is None
                or registry_entry.id != self._vacuum_registry_id
                or not isinstance(registry_entry.entity_id, str)
            ):
                return self.async_abort(reason="invalid_flow_state")
            registry_options = registry_entry.options
            vacuum_options = (
                registry_options.get("vacuum") if isinstance(registry_options, Mapping) else None
            )
            area_mapping = (
                vacuum_options.get("area_mapping") if isinstance(vacuum_options, Mapping) else None
            )
            selected_area_ids = user_input[CONF_AREA_IDS]
            if not selected_area_ids:
                errors[CONF_AREA_IDS] = "areas_required"
            elif len(selected_area_ids) != len(set(selected_area_ids)):
                errors[CONF_AREA_IDS] = "areas_duplicate"
            elif not isinstance(area_mapping, Mapping) or any(
                not isinstance(segments := area_mapping.get(area_id), list)
                or not segments
                or any(
                    not isinstance(segment_id, str) or not segment_id.strip()
                    for segment_id in segments
                )
                for area_id in selected_area_ids
            ):
                errors[CONF_AREA_IDS] = "areas_not_mapped"
            else:
                state = self.hass.states.get(registry_entry.entity_id)
                supported_features = (
                    state.attributes.get(ATTR_SUPPORTED_FEATURES) if state is not None else None
                )
                if (
                    type(supported_features) is not int
                    or supported_features < 0
                    or not supported_features & int(VacuumEntityFeature.CLEAN_AREA)
                ):
                    return self.async_abort(reason="invalid_flow_state")
                await self.async_set_unique_id(self._vacuum_registry_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_VACUUM_ENTITY_ID: registry_entry.entity_id}
                )
                return self.async_create_entry(
                    title=registry_entry.entity_id,
                    data={
                        CONF_VACUUM_ENTITY_ID: registry_entry.entity_id,
                        CONF_AREA_IDS: selected_area_ids,
                    },
                )
        return self.async_show_form(
            step_id="areas",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AREA_IDS): selector.AreaSelector(
                        selector.AreaSelectorConfig(multiple=True, reorder=True)
                    )
                }
            ),
            errors=errors,
        )
