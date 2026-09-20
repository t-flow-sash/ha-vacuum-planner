"""Lifecycle tests against a real Home Assistant runtime."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

import pytest
import voluptuous as vol
from homeassistant.components.vacuum import VacuumEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import Context, SupportsResponse
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vacuum_planner.adapters.native_area import NativeAreaAdapter
from custom_components.vacuum_planner.config_flow import VacuumPlannerConfigFlow
from custom_components.vacuum_planner.const import (
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
    PLATFORMS,
    SERVICE_GET_QUEUE,
    SERVICE_START_NEXT,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _serialize_form_schema(schema: vol.Schema) -> object:
    """Exercise the active HA release's frontend schema serializer."""
    try:
        serializer = import_module("probatio")
    except ImportError:
        serializer = import_module("voluptuous_serialize")
        return serializer.convert(schema)
    return serializer.to_field_list(schema)


async def test_area_plan_form_schema_is_frontend_serializable(
    hass: HomeAssistant,
) -> None:
    """Keep the displayed form compatible with Probatio and older HA serializers."""
    area = ar.async_get(hass).async_create("Kitchen")
    flow = VacuumPlannerConfigFlow()
    flow.hass = hass
    flow._selected_area_ids = [area.id]  # noqa: SLF001

    result = await flow.async_step_area_plan()

    fields = _serialize_form_schema(result["data_schema"])
    assert isinstance(fields, list)
    assert {field["name"] for field in fields} == {
        "active",
        "vacuum_interval_days",
        "mop_interval_days",
        "priority",
        "mode",
    }
    assert result["description_placeholders"] == {
        "area_name": "Kitchen",
        "current": "1",
        "total": "1",
    }


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
    assert len(PLATFORMS) == 5
    assert hass.states.get("sensor.vacuum_planner_test_status") is not None
    assert hass.states.get("switch.vacuum_planner_test_planning") is not None
    assert hass.states.get("binary_sensor.vacuum_planner_test_ready") is not None
    assert hass.states.get("button.vacuum_planner_test_start_next_due_task") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state.value == "not_loaded"
    assert not hasattr(entry, "runtime_data")
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_native_room_numbers_write_authoritative_plan_in_real_home_assistant(
    hass: HomeAssistant,
) -> None:
    """Exercise registration and number.set_value without controlling a vacuum."""
    area = ar.async_get(hass).async_create("Kitchen")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Vacuum Planner numbers",
        data={
            CONF_VACUUM_ENTITY_ID: "vacuum.test",
            CONF_AREA_IDS: [area.id],
            CONF_AREA_PLANS: {
                area.id: {
                    CONF_AREA_ACTIVE: True,
                    CONF_VACUUM_INTERVAL_DAYS: 2,
                    CONF_MOP_INTERVAL_DAYS: 7,
                    CONF_PRIORITY: 10,
                    CONF_MODE: "vacuum",
                }
            },
        },
        options={CONF_PLANNING_ENABLED: True, CONF_DRY_RUN: True},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry_entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    numbers = {item.unique_id: item for item in registry_entries if item.domain == "number"}
    assert set(numbers) == {
        f"{entry.entry_id}_{area.id}_priority",
        f"{entry.entry_id}_{area.id}_vacuum_and_mop_interval",
        f"{entry.entry_id}_{area.id}_vacuum_interval",
    }
    priority = numbers[f"{entry.entry_id}_{area.id}_priority"]
    before_revision = entry.runtime_data.state.plan_revision.revision_id

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: priority.entity_id, "value": 50},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = entry.runtime_data.state
    assert state.plan_revision.revision_id != before_revision
    assert state.plan_revision.room_plans[0].priority == 50
    assert hass.states.get(priority.entity_id).state == "50"

    assert await hass.config_entries.async_unload(entry.entry_id)


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
