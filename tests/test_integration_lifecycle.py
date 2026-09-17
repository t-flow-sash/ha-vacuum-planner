import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from custom_components.vacuum_planner import async_setup_entry, async_unload_entry
from custom_components.vacuum_planner.const import (
    CONF_VACUUM_ENTITY_ID,
    DOMAIN,
    VacuumPlannerRuntimeData,
)


def test_integration_constants_define_entry_identity() -> None:
    assert DOMAIN == "vacuum_planner"
    assert CONF_VACUUM_ENTITY_ID == "vacuum_entity_id"


def test_setup_and_unload_manage_entry_runtime_data_without_platforms() -> None:
    hass = SimpleNamespace()
    entry = SimpleNamespace(
        data={CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
        unique_id=None,
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data == VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs"
    )

    assert asyncio.run(async_unload_entry(hass, entry)) is True
    assert entry.runtime_data is None


def test_setup_resolves_current_entity_id_from_stable_registry_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    registry = SimpleNamespace(
        async_get=lambda _registry_id: SimpleNamespace(entity_id="vacuum.renamed")
    )
    vars(entity_registry_module)["async_get"] = lambda _hass: registry
    vars(homeassistant_module)["helpers"] = helpers_module
    vars(helpers_module)["entity_registry"] = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module
    )

    updated: list[dict[str, str]] = []
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda _entry, *, data: updated.append(data)
        )
    )
    entry = SimpleNamespace(
        data={CONF_VACUUM_ENTITY_ID: "vacuum.old_name"},
        unique_id="vacuum-registry-entry",
        runtime_data=None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert entry.runtime_data == VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.renamed"
    )
    assert updated == [{CONF_VACUUM_ENTITY_ID: "vacuum.renamed"}]
