import asyncio
import importlib
import sys
from enum import IntFlag
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar

import pytest

from custom_components.vacuum_planner.const import CONF_VACUUM_ENTITY_ID, DOMAIN


class AbortFlowError(Exception):
    """Minimal equivalent of HA's data-entry-flow abort signal."""


class StubVacuumEntityFeature(IntFlag):
    CLEAN_AREA = 16384


MISSING_SUPPORTED_FEATURES = object()


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

    def _abort_if_unique_id_configured(
        self, *, updates: dict[str, object] | None = None
    ) -> None:
        if self.unique_id in self.configured_unique_ids:
            self.abort_updates = updates
            raise AbortFlowError("already_configured")

    def async_show_form(self, **result: object) -> dict[str, object]:
        return {"type": "form", **result}

    def async_create_entry(self, **result: object) -> dict[str, object]:
        return {"type": "create_entry", **result}


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


class StubEntityRegistry:
    def __init__(self, registry_id: str | None) -> None:
        self.registry_id = registry_id

    def async_get(self, _entity_id: str) -> object | None:
        if self.registry_id is None:
            return None
        return SimpleNamespace(id=self.registry_id)


def import_config_flow() -> ModuleType:
    homeassistant = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    vacuum = ModuleType("homeassistant.components.vacuum")
    config_entries = ModuleType("homeassistant.config_entries")
    const = ModuleType("homeassistant.const")
    vars(vacuum)["VacuumEntityFeature"] = StubVacuumEntityFeature
    vars(config_entries)["ConfigFlow"] = StubConfigFlow
    vars(config_entries)["ConfigFlowResult"] = dict[str, object]
    vars(const)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
    helpers = ModuleType("homeassistant.helpers")
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    selector = ModuleType("homeassistant.helpers.selector")
    vars(entity_registry)["async_get"] = lambda hass: hass.entity_registry
    vars(selector)["EntitySelector"] = StubEntitySelector
    vars(selector)["EntitySelectorConfig"] = StubEntitySelectorConfig
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
) -> Any:
    module = import_config_flow()
    flow = module.VacuumPlannerConfigFlow()
    state = (
        SimpleNamespace(
            attributes=(
                {}
                if supported_features is MISSING_SUPPORTED_FEATURES
                else {"supported_features": supported_features}
            )
        )
        if entity_exists
        else None
    )
    flow.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda _entity_id: state),
        entity_registry=StubEntityRegistry(registry_id),
    )
    return flow


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


def test_user_step_creates_entry_identified_by_existing_vacuum_entity() -> None:
    flow = configured_flow(entity_exists=True)

    result = asyncio.run(
        flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"})
    )

    assert result == {
        "type": "create_entry",
        "title": "vacuum.downstairs",
        "data": {CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"},
    }
    assert flow.unique_id == "vacuum-registry-entry"


def test_user_step_accepts_clean_area_combined_with_other_features() -> None:
    flow = configured_flow(
        entity_exists=True,
        supported_features=int(StubVacuumEntityFeature.CLEAN_AREA) | 8192,
    )

    result = asyncio.run(
        flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"})
    )

    assert result["type"] == "create_entry"
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

    result = asyncio.run(
        flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"})
    )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {
        CONF_VACUUM_ENTITY_ID: "clean_area_unsupported"
    }
    assert flow.unique_id is None


def test_user_step_rejects_malformed_supported_features_fail_closed() -> None:
    malformed_values = ("16384", 16384.0, True, -1, "not-an-int", object())

    for supported_features in malformed_values:
        flow = configured_flow(
            entity_exists=True,
            supported_features=supported_features,
        )

        result = asyncio.run(
            flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.downstairs"})
        )

        assert result["type"] == "form"
        assert result["errors"] == {
            CONF_VACUUM_ENTITY_ID: "clean_area_unsupported"
        }
        assert flow.unique_id is None


def test_user_step_rejects_an_entity_that_no_longer_exists() -> None:
    flow = configured_flow(entity_exists=False, supported_features="not-an-int")

    result = asyncio.run(
        flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.missing"})
    )

    assert result["type"] == "form"
    assert result["errors"] == {CONF_VACUUM_ENTITY_ID: "entity_not_found"}
    assert flow.unique_id is None


def test_user_step_aborts_when_vacuum_entity_is_already_configured() -> None:
    flow = configured_flow(entity_exists=True)
    flow.configured_unique_ids = {"vacuum-registry-entry"}

    with pytest.raises(AbortFlowError, match="already_configured"):
        asyncio.run(
            flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.renamed"})
        )

    assert flow.abort_updates == {CONF_VACUUM_ENTITY_ID: "vacuum.renamed"}


def test_user_step_rejects_entity_without_registry_identity() -> None:
    flow = configured_flow(entity_exists=True, registry_id=None)

    result = asyncio.run(
        flow.async_step_user({CONF_VACUUM_ENTITY_ID: "vacuum.unregistered"})
    )

    assert result["type"] == "form"
    assert result["errors"] == {CONF_VACUUM_ENTITY_ID: "entity_not_found"}
    assert flow.unique_id is None
