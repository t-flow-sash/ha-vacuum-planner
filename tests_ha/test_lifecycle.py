"""Lifecycle tests against a real Home Assistant runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import voluptuous as vol
from homeassistant.components.vacuum import VacuumEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import Context, SupportsResponse
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vacuum_planner.adapters.native_area import NativeAreaAdapter
from custom_components.vacuum_planner.const import (
    CONF_AREA_IDS,
    CONF_DRY_RUN,
    CONF_PLANNING_ENABLED,
    CONF_VACUUM_ENTITY_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_GET_QUEUE,
    SERVICE_START_NEXT,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_config_entry_setup_and_unload_real_home_assistant(
    hass: HomeAssistant,
) -> None:
    """Set up, forward platforms, persist initial state, and unload cleanly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vacuum Planner test",
        data={CONF_VACUUM_ENTITY_ID: "vacuum.test", CONF_AREA_IDS: []},
        options={CONF_PLANNING_ENABLED: True, CONF_DRY_RUN: True},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state.value == "loaded"
    assert entry.runtime_data is hass.data[DOMAIN][entry.entry_id]
    assert entry.runtime_data.store is not None
    assert entry.runtime_data.coordinator is not None
    assert len(PLATFORMS) == 4
    assert hass.states.get("sensor.vacuum_planner_test_status") is not None
    assert hass.states.get("switch.vacuum_planner_test_planning") is not None
    assert hass.states.get("binary_sensor.vacuum_planner_test_ready") is not None
    assert hass.states.get("button.vacuum_planner_test_start_next_due_task") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state.value == "not_loaded"
    assert not hasattr(entry, "runtime_data")
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_native_clean_area_contract_uses_cleaning_area_id_without_hardware(
    hass: HomeAssistant,
) -> None:
    """Exercise the HA 2026.9 service registry contract with a local fake handler."""
    calls: list[dict[str, Any]] = []

    async def capture(call: Any) -> None:
        calls.append(dict(call.data))

    hass.states.async_set(
        "vacuum.contract_robot",
        "idle",
        {ATTR_SUPPORTED_FEATURES: int(VacuumEntityFeature.CLEAN_AREA)},
    )
    hass.services.async_register(
        "vacuum",
        "clean_area",
        capture,
        schema=vol.Schema(
            {
                vol.Required("cleaning_area_id"): [str],
                vol.Optional(ATTR_ENTITY_ID): vol.Any(str, [str]),
            },
            extra=vol.PREVENT_EXTRA,
        ),
    )

    await NativeAreaAdapter(hass, "vacuum.contract_robot").async_dispatch(
        ("kitchen", "hallway"),
        Context(),
    )

    assert len(calls) == 1
    assert calls[0]["cleaning_area_id"] == ["kitchen", "hallway"]
    assert "area_id" not in calls[0]
    assert calls[0][ATTR_ENTITY_ID] == "vacuum.contract_robot"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_supports_response_and_button_press_contracts_without_hardware(
    hass: HomeAssistant,
) -> None:
    """Verify response metadata and a real button.press call without a robot backend."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vacuum Planner contracts",
        data={CONF_VACUUM_ENTITY_ID: "vacuum.contract", CONF_AREA_IDS: []},
        options={CONF_PLANNING_ENABLED: True, CONF_DRY_RUN: True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.supports_response(DOMAIN, SERVICE_GET_QUEUE) is SupportsResponse.ONLY
    assert hass.services.supports_response(DOMAIN, SERVICE_START_NEXT) is SupportsResponse.OPTIONAL
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_QUEUE,
        {"config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert response == {"revision": 0, "blocks": [], "jobs": []}

    button_calls: list[dict[str, Any]] = []

    async def capture_button_action(call: Any) -> dict[str, str]:
        button_calls.append(dict(call.data))
        return {"status": "captured"}

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_NEXT,
        capture_button_action,
        supports_response=SupportsResponse.OPTIONAL,
    )
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.vacuum_planner_contracts_start_next_due_task"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert button_calls == [{"config_entry_id": entry.entry_id}]
