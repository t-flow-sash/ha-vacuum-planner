import asyncio
import importlib
import sys
from enum import IntFlag
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar, Generic, TypeVar, cast

import pytest
import voluptuous as vol

from custom_components.vacuum_planner.const import (
    CONF_AREA_IDS,
    CONF_AREA_PLANS,
    CONF_DRY_RUN,
    CONF_MOP_INTERVAL_DAYS,
    CONF_PLANNING_ENABLED,
    CONF_PRIORITY,
    CONF_VACUUM_ENTITY_ID,
    CONF_VACUUM_INTERVAL_DAYS,
    DOMAIN,
)
from custom_components.vacuum_planner.domain.models import PlannerState


class AbortFlowError(Exception):
    """Minimal equivalent of HA's data-entry-flow abort signal."""


class StubVacuumEntityFeature(IntFlag):
    CLEAN_AREA = 16384


class StubConfigEntryDisabler:
    INTEGRATION = "integration"


MISSING_SUPPORTED_FEATURES = object()
REGISTRY_OPTIONS_FROM_AREA_MAPPING = object()
RuntimeDataT = TypeVar("RuntimeDataT")


class StubConfigEntry(Generic[RuntimeDataT]):
    """Minimal generic ConfigEntry surface imported by the production flow."""

    def __init__(
        self,
        *,
        entry_id: str = "entry-1",
        data: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
        unique_id: str | None = None,
        runtime_data: RuntimeDataT | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}
        self.unique_id = unique_id
        self.runtime_data = runtime_data


class StubConfigFlow:
    configured_unique_ids: ClassVar[set[str]] = set()
    domain: str | None = None

    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    def __init__(self) -> None:
        self.hass: Any = None
        self.unique_id: str | None = None
        self.abort_updates: dict[str, object] | None = None

    async def async_set_unique_id(self, unique_id: str) -> None:
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self, *, updates: dict[str, object] | None = None) -> None:
        if self.unique_id in self.configured_unique_ids:
            self.abort_updates = updates
            raise AbortFlowError("already_configured")

    def async_show_form(self, **result: object) -> dict[str, object]:
        return {"type": "form", **result}

    def async_create_entry(self, **result: object) -> dict[str, object]:
        return {"type": "create_entry", **result}

    def async_abort(self, **result: object) -> dict[str, object]:
        return {"type": "abort", **result}


class StubOptionsFlow:
    def __init__(self) -> None:
        self.config_entry: Any = None

    def async_show_form(self, **result: object) -> dict[str, object]:
        return {"type": "form", **result}

    def async_create_entry(self, **result: object) -> dict[str, object]:
        return {"type": "create_entry", **result}


class StubOptionsFlowWithReload(StubOptionsFlow):
    """Mirror HA's marker class for options flows that trigger reloads."""

    automatic_reload = True


class StubEntitySelectorConfig(dict[str, object]):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(kwargs)


class StubEntitySelector:
    def __init__(self, config: StubEntitySelectorConfig) -> None:
        self.config = config

    def __call__(self, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError
        return value


class StubAreaSelectorConfig(dict[str, object]):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(kwargs)


class StubAreaSelector:
    def __init__(self, config: StubAreaSelectorConfig) -> None:
        self.config = config

    def __call__(self, value: object) -> list[str]:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError
        return value


class StubEntityRegistry:
    def __init__(
        self,
        registry_id: str | None,
        options: object,
        entity_id: str,
    ) -> None:
        self.entry = (
            None
            if registry_id is None
            else SimpleNamespace(
                id=registry_id,
                entity_id=entity_id,
                options=options,
            )
        )

    def async_get(self, entity_id_or_registry_id: str) -> object | None:
        if self.entry is None:
            return None
        if entity_id_or_registry_id not in (self.entry.id, self.entry.entity_id):
            return None
        return self.entry

    def rename(self, entity_id: str) -> None:
        assert self.entry is not None
        self.entry.entity_id = entity_id

    def remove(self) -> None:
        self.entry = None

    def replace(self, entity_id: str, options: object) -> None:
        self.entry = SimpleNamespace(
            id="replacement-registry-entry",
            entity_id=entity_id,
            options=options,
        )


def import_config_flow() -> ModuleType:
    homeassistant = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    vacuum = ModuleType("homeassistant.components.vacuum")
    config_entries = ModuleType("homeassistant.config_entries")
    const = ModuleType("homeassistant.const")
    vars(vacuum)["VacuumEntityFeature"] = StubVacuumEntityFeature
    vars(config_entries)["ConfigEntry"] = StubConfigEntry
    vars(config_entries)["ConfigEntryDisabler"] = StubConfigEntryDisabler
    vars(config_entries)["ConfigFlow"] = StubConfigFlow
    vars(config_entries)["ConfigFlowResult"] = dict[str, object]
    vars(config_entries)["OptionsFlow"] = StubOptionsFlow
    vars(config_entries)["OptionsFlowWithReload"] = StubOptionsFlowWithReload
    vars(const)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
    helpers = ModuleType("homeassistant.helpers")
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    selector = ModuleType("homeassistant.helpers.selector")
    vars(entity_registry)["async_get"] = lambda hass: hass.entity_registry
    vars(selector)["EntitySelector"] = StubEntitySelector
    vars(selector)["EntitySelectorConfig"] = StubEntitySelectorConfig
    vars(selector)["AreaSelector"] = StubAreaSelector
    vars(selector)["AreaSelectorConfig"] = StubAreaSelectorConfig
    vars(homeassistant)["config_entries"] = config_entries
    vars(homeassistant)["components"] = components
    vars(homeassistant)["const"] = const
    vars(components)["vacuum"] = vacuum
    vars(homeassistant)["helpers"] = helpers
    vars(helpers)["entity_registry"] = entity_registry
    vars(helpers)["selector"] = selector
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.vacuum": vacuum,
            "homeassistant.config_entries": config_entries,
            "homeassistant.const": const,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_registry": entity_registry,
            "homeassistant.helpers.selector": selector,
        }
    )
    sys.modules.pop("custom_components.vacuum_planner.config_flow", None)
    return importlib.import_module("custom_components.vacuum_planner.config_flow")


def configured_flow(
    *,
    entity_exists: bool,
    registry_id: str | None = "vacuum-registry-entry",
    supported_features: object = int(StubVacuumEntityFeature.CLEAN_AREA),
    area_mapping: dict[str, list[str]] | None = None,
    registry_options: object = REGISTRY_OPTIONS_FROM_AREA_MAPPING,
    entity_id: str = "vacuum.downstairs",
) -> Any:
    module = import_config_flow()
    flow = module.VacuumPlannerConfigFlow()
    state = (
        SimpleNamespace(
            state="idle",
            attributes=(
                {}
                if supported_features is MISSING_SUPPORTED_FEATURES
                else {"supported_features": supported_features}
            ),
        )
        if entity_exists
        else None
    )

    def update_entry(
        entry: Any,
        *,
        data: dict[str, object],
        unique_id: str,
    ) -> None:
        flow.updated_entry = entry
        flow.updated_data = data
        flow.updated_unique_id = unique_id
        entry.data = data
        entry.unique_id = unique_id

    async def reload_entry(_entry_id: str) -> bool:
        return True

    async def unload_entry(_entry_id: str) -> bool:
        return True

    flow.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda _entity_id: state),
        entity_registry=StubEntityRegistry(
            registry_id,
            (
                registry_options
                if registry_options is not REGISTRY_OPTIONS_FROM_AREA_MAPPING
                else ({} if area_mapping is None else {"vacuum": {"area_mapping": area_mapping}})
            ),
            entity_id,
        ),
        config_entries=SimpleNamespace(
            async_update_entry=update_entry,
            async_reload=reload_entry,
            async_unload=unload_entry,
        ),
    )
    return flow


def finish_area_plans(flow: Any, result: dict[str, object]) -> dict[str, object]:
    """Submit the displayed defaults until the per-area UI sequence completes."""
    current = result
    while current.get("type") == "form" and current.get("step_id") == "area_plan":
        schema = cast("Any", current["data_schema"])
        current = asyncio.run(flow.async_step_area_plan(schema({})))
    return current


class MemoryStore:
    async def async_save(self, _state: PlannerState) -> None:
        pass


def test_user_form_selects_exactly_one_vacuum_entity() -> None:
    flow = configured_flow(entity_exists=True)

    result = asyncio.run(flow.async_step_user())

    assert flow.domain == DOMAIN
    assert flow.VERSION == 1
    schema = result["data_schema"]
    schema_definition = schema.schema
    assert len(schema_definition) == 1
    selector = next(iter(schema_definition.values()))
    assert selector.config == {"domain": "vacuum", "multiple": False}


def test_options_flow_persists_planning_enabled_preference() -> None:
    module = import_config_flow()
    flow = module.VacuumPlannerOptionsFlow()
    flow.config_entry = SimpleNamespace(options={})

    form = asyncio.run(flow.async_step_init())
    planning_field = next(iter(form["data_schema"].schema))
    assert planning_field.schema == "planning_enabled"
    assert form["data_schema"]({}) == {"planning_enabled": True, "dry_run": True}

    result = asyncio.run(flow.async_step_init({"planning_enabled": False, "dry_run": True}))

    assert result == {
        "type": "create_entry",
        "title": "",
        "data": {"planning_enabled": False, "dry_run": True},
    }


def test_options_flow_defaults_to_safe_dry_run() -> None:
    module = import_config_flow()
    flow = module.VacuumPlannerOptionsFlow()
    flow.config_entry = SimpleNamespace(options={})

    form = asyncio.run(flow.async_step_init())

    assert form["data_schema"]({})["dry_run"] is True


def test_options_ui_warns_that_disabling_dry_run_enables_vacuum_commands() -> None:
    catalog = __import__("json").loads(
        __import__("pathlib")
        .Path("custom_components/vacuum_planner/translations/en.json")
        .read_text(encoding="utf-8")
    )

    description = catalog["options"]["step"]["init"]["description"].lower()
    assert "disabling dry run" in description
    assert "vacuum commands" in description


def test_options_flow_allows_explicit_dry_run_disable() -> None:
    module = import_config_flow()
    flow = module.VacuumPlannerOptionsFlow()
    flow.config_entry = SimpleNamespace(options={})

    result = asyncio.run(flow.async_step_init({"planning_enabled": True, "dry_run": False}))

    assert result["data"]["dry_run"] is False


def test_options_flow_uses_ha_reload_contract_when_dry_run_changes() -> None:
    module = import_config_flow()
    flow = module.VacuumPlannerOptionsFlow()
    flow.config_entry = SimpleNamespace(options={"planning_enabled": True, "dry_run": False})

    result = asyncio.run(flow.async_step_init({"planning_enabled": True, "dry_run": True}))

    assert isinstance(flow, StubOptionsFlowWithReload)
    assert flow.automatic_reload is True
    assert result["data"]["dry_run"] is True


def test_config_flow_exposes_options_flow_to_home_assistant() -> None:
    module = import_config_flow()

    options_flow = module.VacuumPlannerConfigFlow.async_get_options_flow(
        SimpleNamespace(options={})
    )

    assert isinstance(options_flow, module.VacuumPlannerOptionsFlow)


def test_user_step_sets_stable_registry_identity_before_area_selection() -> None:
    flow = configured_flow(entity_exists=True)

    result = asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    assert result["type"] == "form"
    assert result["step_id"] == "areas"
    assert flow.unique_id == "vacuum-registry-entry"


def test_supported_vacuum_advances_to_multiple_area_selector() -> None:
    flow = configured_flow(entity_exists=True)

    result = asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    assert result["type"] == "form"
    assert result["step_id"] == "areas"
    schema = result["data_schema"]
    assert len(schema.schema) == 1
    area_selector = next(iter(schema.schema.values()))
    assert area_selector.config == {"multiple": True}
    assert flow.unique_id == "vacuum-registry-entry"


def test_area_step_collects_ui_only_plan_for_every_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"], "hallway": ["4"]},
    )
    monkeypatch.setattr(
        sys.modules[flow.__class__.__module__],
        "find_dreame_mova_cleaning_mode_entity",
        lambda _hass, _registry_id: "select.downstairs_cleaning_mode",
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    first = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen", "hallway"]}))
    assert first["step_id"] == "area_plan"
    assert set(first["data_schema"]({})) == {
        "active",
        "vacuum_interval_days",
        "mop_interval_days",
        "priority",
        "mode",
    }
    second = asyncio.run(
        flow.async_step_area_plan(
            {
                "active": False,
                "vacuum_interval_days": 3,
                "mop_interval_days": 9,
                "priority": 4,
                "mode": "vacuum_and_mop",
            }
        )
    )
    assert second["step_id"] == "area_plan"
    result = asyncio.run(
        flow.async_step_area_plan(
            {
                "active": True,
                "vacuum_interval_days": 5,
                "mop_interval_days": 11,
                "priority": 2,
                "mode": "vacuum_and_mop",
            }
        )
    )

    assert result["data"][CONF_AREA_PLANS] == {
        "kitchen": {
            "active": False,
            "vacuum_interval_days": 3,
            "mop_interval_days": 9,
            "priority": 4,
            "mode": "vacuum_and_mop",
        },
        "hallway": {
            "active": True,
            "vacuum_interval_days": 5,
            "mop_interval_days": 11,
            "priority": 2,
            "mode": "vacuum_and_mop",
        },
    }


def test_area_plans_require_one_homogeneous_native_batch_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"], "hallway": ["4"]},
    )
    monkeypatch.setattr(
        sys.modules[flow.__class__.__module__],
        "find_dreame_mova_cleaning_mode_entity",
        lambda _hass, _registry_id: "select.downstairs_cleaning_mode",
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen", "hallway"]}))
    second = asyncio.run(
        flow.async_step_area_plan(
            {
                "active": True,
                "vacuum_interval_days": 7,
                "mop_interval_days": 7,
                "priority": 0,
                "mode": "vacuum_and_mop",
            }
        )
    )

    with pytest.raises(vol.Invalid):
        second["data_schema"](
            {
                "active": True,
                "vacuum_interval_days": 7,
                "mop_interval_days": 7,
                "priority": 1,
                "mode": "vacuum",
            }
        )


def test_area_plan_does_not_offer_mop_without_confirmed_adapter_capability() -> None:
    flow = configured_flow(entity_exists=True, area_mapping={"kitchen": ["7"]})
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    form = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))

    with pytest.raises(vol.Invalid):
        form["data_schema"](
            {
                "active": True,
                "vacuum_interval_days": 7,
                "mop_interval_days": 7,
                "priority": 0,
                "mode": "vacuum_and_mop",
            }
        )


def test_area_plan_rejects_automatic_mode() -> None:
    flow = configured_flow(entity_exists=True, area_mapping={"kitchen": ["7"]})
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))

    form = asyncio.run(flow.async_step_area_plan())
    with pytest.raises(vol.Invalid):
        form["data_schema"](
            {
                "active": True,
                "vacuum_interval_days": 7,
                "mop_interval_days": 7,
                "priority": 0,
                "mode": "automatic",
            }
        )


@pytest.mark.parametrize(
    "field",
    [CONF_VACUUM_INTERVAL_DAYS, CONF_MOP_INTERVAL_DAYS, CONF_PRIORITY],
)
def test_area_plan_rejects_bool_for_integer_fields(field: str) -> None:
    flow = configured_flow(entity_exists=True, area_mapping={"kitchen": ["7"]})
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))
    form = asyncio.run(flow.async_step_area_plan())
    values = {
        "active": True,
        CONF_VACUUM_INTERVAL_DAYS: 7,
        CONF_MOP_INTERVAL_DAYS: 7,
        CONF_PRIORITY: 0,
        "mode": "vacuum",
    }
    values[field] = True

    with pytest.raises(vol.Invalid):
        form["data_schema"](values)


def test_area_step_creates_entry_with_ordered_mapped_ha_area_ids() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"], "hallway": ["4", "5"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    result = finish_area_plans(
        flow,
        asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["hallway", "kitchen"]})),
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "vacuum.downstairs"
    data = cast("dict[str, Any]", result["data"])
    assert data[CONF_VACUUM_ENTITY_ID] == "vacuum.downstairs"
    assert data[CONF_AREA_IDS] == ["hallway", "kitchen"]
    assert set(data[CONF_AREA_PLANS]) == {"hallway", "kitchen"}


def test_area_step_follows_registry_identity_across_entity_rename() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    flow.hass.entity_registry.rename("vacuum.ground_floor")

    result = finish_area_plans(
        flow,
        asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]})),
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "vacuum.ground_floor"
    data = cast("dict[str, Any]", result["data"])
    assert data[CONF_VACUUM_ENTITY_ID] == "vacuum.ground_floor"
    assert data[CONF_AREA_IDS] == ["kitchen"]


def test_area_step_aborts_if_registry_identity_becomes_configured_during_flow() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    flow.hass.entity_registry.rename("vacuum.ground_floor")
    flow.configured_unique_ids = {"vacuum-registry-entry"}

    with pytest.raises(AbortFlowError, match="already_configured"):
        finish_area_plans(
            flow,
            asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]})),
        )

    assert flow.unique_id == "vacuum-registry-entry"
    assert flow.abort_updates == {CONF_VACUUM_ENTITY_ID: "vacuum.ground_floor"}


def test_area_step_aborts_if_current_vacuum_state_disappears() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    flow.hass.states.get = lambda _entity_id: None

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))

    assert result == {"type": "abort", "reason": "invalid_flow_state"}


@pytest.mark.parametrize("supported_features", [0, None, "16384", True, -1])
def test_area_step_aborts_if_current_vacuum_loses_clean_area_capability(
    supported_features: object,
) -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    flow.hass.states.get = lambda _entity_id: SimpleNamespace(
        state="idle", attributes={"supported_features": supported_features}
    )

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))

    assert result == {"type": "abort", "reason": "invalid_flow_state"}


@pytest.mark.parametrize("change", ["remove", "replace"])
def test_area_step_aborts_if_selected_registry_entity_disappears_or_is_replaced(
    change: str,
) -> None:
    area_mapping = {"kitchen": ["7"]}
    flow = configured_flow(entity_exists=True, area_mapping=area_mapping)
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))
    registry = flow.hass.entity_registry
    if change == "remove":
        registry.remove()
    else:
        registry.replace(
            "vacuum.downstairs",
            {"vacuum": {"area_mapping": area_mapping}},
        )

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))

    assert result == {"type": "abort", "reason": "invalid_flow_state"}


@pytest.mark.parametrize(
    "registry_options",
    [
        None,
        [],
        {"vacuum": None},
        {"vacuum": []},
        {"vacuum": "invalid"},
        {"vacuum": {"area_mapping": []}},
        {"vacuum": {"area_mapping": {"kitchen": "7"}}},
        {"vacuum": {"area_mapping": {"kitchen": [None]}}},
    ],
)
def test_area_step_rejects_malformed_nested_registry_options_without_exception(
    registry_options: object,
) -> None:
    flow = configured_flow(entity_exists=True, registry_options=registry_options)
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AREA_IDS: "areas_not_mapped"}


def test_area_step_blocks_unmapped_ha_area_ids() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen", "hallway"]}))

    assert result["type"] == "form"
    assert result["step_id"] == "areas"
    assert result["errors"] == {CONF_AREA_IDS: "areas_not_mapped"}


def test_area_step_rejects_mapping_without_usable_segment_id() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": [""]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen"]}))

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AREA_IDS: "areas_not_mapped"}


def test_area_step_requires_at_least_one_area() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: []}))

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AREA_IDS: "areas_required"}


def test_area_step_rejects_duplicate_area_ids() -> None:
    flow = configured_flow(
        entity_exists=True,
        area_mapping={"kitchen": ["7"]},
    )
    asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    result = asyncio.run(flow.async_step_areas({CONF_AREA_IDS: ["kitchen", "kitchen"]}))

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AREA_IDS: "areas_duplicate"}


def test_user_step_accepts_clean_area_combined_with_other_features() -> None:
    flow = configured_flow(
        entity_exists=True,
        supported_features=int(StubVacuumEntityFeature.CLEAN_AREA) | 8192,
    )

    result = asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    assert result["type"] == "form"
    assert result["step_id"] == "areas"
    assert flow.unique_id == "vacuum-registry-entry"


@pytest.mark.parametrize(
    "supported_features",
    [0, None, 8192, MISSING_SUPPORTED_FEATURES],
)
def test_user_step_rejects_vacuum_without_native_area_cleaning(
    supported_features: object,
) -> None:
    flow = configured_flow(
        entity_exists=True,
        supported_features=supported_features,
    )

    result = asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_VACUUM_ENTITY_ID: "clean_area_unsupported"}
    assert flow.unique_id is None


def test_user_step_rejects_malformed_supported_features_fail_closed() -> None:
    malformed_values = ("16384", 16384.0, True, -1, "not-an-int", object())

    for supported_features in malformed_values:
        flow = configured_flow(
            entity_exists=True,
            supported_features=supported_features,
        )

        result = asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"}))

        assert result["type"] == "form"
        assert result["errors"] == {CONF_VACUUM_ENTITY_ID: "clean_area_unsupported"}
        assert flow.unique_id is None


def test_user_step_rejects_an_entity_that_no_longer_exists() -> None:
    flow = configured_flow(entity_exists=False, supported_features="not-an-int")

    result = asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.missing"}))

    assert result["type"] == "form"
    assert result["errors"] == {CONF_VACUUM_ENTITY_ID: "entity_not_found"}
    assert flow.unique_id is None


def test_user_step_aborts_when_vacuum_entity_is_already_configured() -> None:
    flow = configured_flow(entity_exists=True, entity_id="vacuum.renamed")
    flow.configured_unique_ids = {"vacuum-registry-entry"}

    with pytest.raises(AbortFlowError, match="already_configured"):
        asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.renamed"}))

    assert flow.abort_updates == {CONF_VACUUM_ENTITY_ID: "vacuum.renamed"}


def test_user_step_rejects_entity_without_registry_identity() -> None:
    flow = configured_flow(entity_exists=True, registry_id=None)

    result = asyncio.run(flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.unregistered"}))

    assert result["type"] == "form"
    assert result["errors"] == {CONF_VACUUM_ENTITY_ID: "entity_not_found"}
    assert flow.unique_id is None


def test_options_flow_contains_behavior_only() -> None:
    module = import_config_flow()
    flow = module.VacuumPlannerOptionsFlow()
    flow.config_entry = SimpleNamespace(options={})

    form = asyncio.run(flow.async_step_init())

    assert {marker.schema for marker in form["data_schema"].schema} == {
        CONF_PLANNING_ENABLED,
        CONF_DRY_RUN,
    }
    assert form["data_schema"]({})[CONF_DRY_RUN] is True
