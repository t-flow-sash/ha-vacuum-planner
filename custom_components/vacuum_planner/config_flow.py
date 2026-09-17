"""Config flow for Vacuum Planner."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import CONF_VACUUM_ENTITY_ID, DOMAIN


class VacuumPlannerConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg, misc]
    """Configure one Vacuum Planner entry for one existing vacuum entity."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the vacuum entity managed by this planner entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            vacuum_entity_id = user_input[CONF_VACUUM_ENTITY_ID]
            registry_entry = er.async_get(self.hass).async_get(vacuum_entity_id)
            if (
                self.hass.states.get(vacuum_entity_id) is None
                or registry_entry is None
            ):
                errors[CONF_VACUUM_ENTITY_ID] = "entity_not_found"
            else:
                await self.async_set_unique_id(registry_entry.id)
                self._abort_if_unique_id_configured(
                    updates={CONF_VACUUM_ENTITY_ID: vacuum_entity_id}
                )
                return self.async_create_entry(
                    title=vacuum_entity_id,
                    data={CONF_VACUUM_ENTITY_ID: vacuum_entity_id},
                )

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
