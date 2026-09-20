"""Config flow for Vacuum Planner."""

from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.helpers import selector

from .adapters.native_area import find_dreame_mova_cleaning_mode_entity
from .const import (
    CONF_AREA_ACTIVE,
    CONF_AREA_IDS,
    CONF_AREA_PLANS,
    CONF_DRY_RUN,
    CONF_MODE,
    CONF_MOP_INTERVAL_DAYS,
    CONF_PLANNING_ENABLED,
    CONF_PRIORITY,
    CONF_VACUUM_ENTITY_ID,
    CONF_VACUUM_INTERVAL_DAYS,
    DOMAIN,
)
from .domain.models import PreferredMode
from .topology import RegistryEntry, async_get_valid_vacuum, validate_area_ids


def _strict_int(value: object) -> int:
    """Accept integers while explicitly excluding Python's bool subtype."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise vol.Invalid("expected integer")
    return value


class VacuumPlannerOptionsFlow(OptionsFlowWithReload):  # type: ignore[misc]
    """Configure optional planner behavior without changing topology."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure whether automatic planning is enabled."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PLANNING_ENABLED,
                        default=self.config_entry.options.get(CONF_PLANNING_ENABLED, True),
                    ): bool,
                    vol.Required(
                        CONF_DRY_RUN,
                        default=self.config_entry.options.get(CONF_DRY_RUN, True),
                    ): bool,
                }
            ),
        )


class VacuumPlannerConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg, misc]
    """Configure one Vacuum Planner entry for one existing vacuum entity."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(_config_entry: object) -> VacuumPlannerOptionsFlow:
        """Return the options flow for one planner entry."""
        return VacuumPlannerOptionsFlow()

    def __init__(self) -> None:
        """Initialize transient onboarding state."""
        super().__init__()
        self._vacuum_registry_id: str | None = None
        self._selected_area_ids: list[str] = []
        self._pending_area_plans: dict[str, dict[str, object]] = {}
        self._area_plan_index = 0

    def _vacuum_form(
        self,
        step_id: str,
        errors: dict[str, str],
        default_entity_id: str | None = None,
    ) -> ConfigFlowResult:
        """Show the shared vacuum selector."""
        marker = (
            vol.Required(CONF_VACUUM_ENTITY_ID, default=default_entity_id)
            if default_entity_id is not None
            else vol.Required(CONF_VACUUM_ENTITY_ID)
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    marker: selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="vacuum", multiple=False)
                    )
                }
            ),
            errors=errors,
        )

    def _areas_form(
        self,
        step_id: str,
        errors: dict[str, str],
        default_area_ids: list[str] | None = None,
    ) -> ConfigFlowResult:
        """Show the shared ordered area selector."""
        marker = (
            vol.Required(CONF_AREA_IDS, default=default_area_ids)
            if default_area_ids is not None
            else vol.Required(CONF_AREA_IDS)
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {marker: selector.AreaSelector(selector.AreaSelectorConfig(multiple=True))}
            ),
            errors=errors,
        )

    @staticmethod
    def _default_area_plan() -> dict[str, object]:
        """Return safe initial values for one newly selected area."""
        return {
            CONF_AREA_ACTIVE: True,
            CONF_VACUUM_INTERVAL_DAYS: 7,
            CONF_MOP_INTERVAL_DAYS: 7,
            CONF_PRIORITY: 0,
            CONF_MODE: PreferredMode.VACUUM.value,
        }

    def _begin_area_plans(self, area_ids: list[str]) -> ConfigFlowResult:
        self._selected_area_ids = list(area_ids)
        self._pending_area_plans = {}
        self._area_plan_index = 0
        return self._area_plan_form()

    def _area_plan_form(self) -> ConfigFlowResult:
        area_id = self._selected_area_ids[self._area_plan_index]
        defaults = self._default_area_plan()
        modes = [PreferredMode.VACUUM.value]
        if find_dreame_mova_cleaning_mode_entity(self.hass, self._vacuum_registry_id) is not None:
            modes.append(PreferredMode.VACUUM_AND_MOP.value)
        elif defaults[CONF_MODE] == PreferredMode.VACUUM_AND_MOP.value:
            defaults[CONF_MODE] = PreferredMode.VACUUM.value
        if self._pending_area_plans:
            first_plan = next(iter(self._pending_area_plans.values()))
            batch_mode = first_plan.get(CONF_MODE)
            if batch_mode in modes:
                modes = [cast("str", batch_mode)]
                defaults[CONF_MODE] = batch_mode
        return self.async_show_form(
            step_id="area_plan",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AREA_ACTIVE, default=defaults[CONF_AREA_ACTIVE]): bool,
                    vol.Required(
                        CONF_VACUUM_INTERVAL_DAYS,
                        default=defaults[CONF_VACUUM_INTERVAL_DAYS],
                    ): vol.All(_strict_int, vol.Range(min=1, max=365)),
                    vol.Required(
                        CONF_MOP_INTERVAL_DAYS,
                        default=defaults[CONF_MOP_INTERVAL_DAYS],
                    ): vol.All(_strict_int, vol.Range(min=1, max=365)),
                    vol.Required(CONF_PRIORITY, default=defaults[CONF_PRIORITY]): vol.All(
                        _strict_int, vol.Range(min=0)
                    ),
                    vol.Required(CONF_MODE, default=defaults[CONF_MODE]): vol.In(modes),
                }
            ),
            description_placeholders={"area_id": area_id},
        )

    async def async_step_area_plan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect one complete UI-owned plan per selected Home Assistant area."""
        if not self._selected_area_ids:
            return self.async_abort(reason="invalid_flow_state")
        if user_input is None:
            return self._area_plan_form()
        area_id = self._selected_area_ids[self._area_plan_index]
        self._pending_area_plans[area_id] = dict(user_input)
        self._area_plan_index += 1
        if self._area_plan_index < len(self._selected_area_ids):
            return self._area_plan_form()
        registry_entry = self._current_vacuum()
        if registry_entry is None:
            return self.async_abort(reason="invalid_flow_state")
        data: dict[str, object] = {
            CONF_VACUUM_ENTITY_ID: registry_entry.entity_id,
            CONF_AREA_IDS: self._selected_area_ids,
            CONF_AREA_PLANS: self._pending_area_plans,
        }
        await self.async_set_unique_id(registry_entry.id)
        self._abort_if_unique_id_configured(
            updates={CONF_VACUUM_ENTITY_ID: registry_entry.entity_id}
        )
        return self.async_create_entry(title=registry_entry.entity_id, data=data)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select the vacuum entity managed by this planner entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            registry_entry, error = async_get_valid_vacuum(
                self.hass, user_input[CONF_VACUUM_ENTITY_ID]
            )
            if error is not None or registry_entry is None:
                errors[CONF_VACUUM_ENTITY_ID] = error or "entity_not_found"
            else:
                await self.async_set_unique_id(registry_entry.id)
                self._abort_if_unique_id_configured(
                    updates={CONF_VACUUM_ENTITY_ID: registry_entry.entity_id}
                )
                self._vacuum_registry_id = registry_entry.id
                return await self.async_step_areas()
        return self._vacuum_form("user", errors)

    def _current_vacuum(self) -> RegistryEntry | None:
        """Revalidate the selected stable registry identity."""
        if self._vacuum_registry_id is None:
            return None
        registry_entry, error = async_get_valid_vacuum(self.hass, self._vacuum_registry_id)
        if (
            error is not None
            or registry_entry is None
            or registry_entry.id != self._vacuum_registry_id
        ):
            return None
        return registry_entry

    async def async_step_areas(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select ordered Home Assistant areas for this planner."""
        errors: dict[str, str] = {}
        if user_input is not None:
            registry_entry = self._current_vacuum()
            if registry_entry is None:
                return self.async_abort(reason="invalid_flow_state")
            selected_area_ids = user_input[CONF_AREA_IDS]
            if error := validate_area_ids(selected_area_ids, registry_entry):
                errors[CONF_AREA_IDS] = error
            else:
                return self._begin_area_plans(selected_area_ids)
        return self._areas_form("areas", errors)
