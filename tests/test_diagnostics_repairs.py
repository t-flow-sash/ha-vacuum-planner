import asyncio
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from custom_components import vacuum_planner as integration
from custom_components.vacuum_planner.const import (
    CONF_AREA_IDS,
    CONF_VACUUM_ENTITY_ID,
    DOMAIN,
)
from custom_components.vacuum_planner.domain.models import (
    BlockState,
    JobState,
    PlannerState,
    PreferredMode,
)
from custom_components.vacuum_planner.domain.serialization import (
    SchemaVersionError,
    deserialize_planner_state,
    serialize_planner_state,
)
from tests.test_serialization import ledger, revision


def test_diagnostics_are_allowlisted_and_exclude_topology_and_history() -> None:
    diagnostics = importlib.import_module("custom_components.vacuum_planner.diagnostics")
    runtime = SimpleNamespace(
        planning_enabled=False,
        dry_run=True,
        store=object(),
        state=SimpleNamespace(
            plan_revision=SimpleNamespace(room_plans=(object(), object())),
            ledger=SimpleNamespace(
                revision=7,
                blocks=(SimpleNamespace(state=BlockState.UNCERTAIN),),
                jobs=(SimpleNamespace(state=JobState.ACCEPTED),),
            ),
        ),
    )
    entry = SimpleNamespace(
        version=1,
        minor_version=1,
        unique_id="registry-secret",
        data={
            "vacuum_entity_id": "vacuum.private_name",
            "area_ids": ["private-kitchen", "private-hall"],
            "history": [{"segment_id": "segment-secret", "payload": "private"}],
        },
        runtime_data=runtime,
    )

    result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(SimpleNamespace(), entry))

    assert result == {
        "entry": {
            "version": 1,
            "minor_version": 1,
            "registry_identity_configured": True,
            "configured_area_count": 2,
        },
        "runtime": {
            "loaded": True,
            "planning_enabled": False,
            "dry_run": True,
            "store_initialized": True,
            "plan_room_count": 2,
            "queue_revision": 7,
            "block_count": 1,
            "job_count": 1,
            "block_states": {"uncertain": 1},
            "job_states": {"accepted": 1},
        },
    }
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "entity_id",
        "area_id",
        "name",
        "segment",
        "history",
        "payload",
        "registry-secret",
        "vacuum.private_name",
        "private-kitchen",
        "segment-secret",
    ):
        assert forbidden not in serialized


def _install_issue_registry_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], list[str]]:
    issues: dict[str, Any] = {}
    deleted: list[str] = []
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")

    class Severity:
        ERROR = "error"

    def async_create_issue(_hass: object, domain: str, issue_id: str, **kwargs: object) -> None:
        assert domain == DOMAIN
        issues[issue_id] = kwargs

    def async_delete_issue(_hass: object, domain: str, issue_id: str) -> None:
        assert domain == DOMAIN
        deleted.append(issue_id)
        issues.pop(issue_id, None)

    vars(issue_registry).update(
        IssueSeverity=Severity,
        async_create_issue=async_create_issue,
        async_delete_issue=async_delete_issue,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)
    return issues, deleted


def test_repairs_use_stable_deduplicated_issue_ids_and_clear_by_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issues, deleted = _install_issue_registry_stub(monkeypatch)
    repairs = importlib.import_module("custom_components.vacuum_planner.repairs")

    repairs.async_create_entry_issue(SimpleNamespace(), "planner-entry-1", repairs.MISSING_REGISTRY)
    repairs.async_create_entry_issue(SimpleNamespace(), "planner-entry-1", repairs.MISSING_REGISTRY)

    assert list(issues) == ["planner-entry-1_missing_registry"]
    assert issues["planner-entry-1_missing_registry"]["translation_key"] == "missing_registry"
    repairs.async_clear_entry_issues(SimpleNamespace(), "planner-entry-1")
    assert issues == {}
    assert deleted == [
        "planner-entry-1_missing_registry",
        "planner-entry-1_missing_mapping",
        "planner-entry-1_lost_capability",
        "planner-entry-1_removed_areas",
        "planner-entry-1_unresolved_external_run",
        "planner-entry-1_corrupt_store",
        "planner-entry-1_future_store",
    ]


def test_remove_entry_deletes_exact_entry_store_and_all_repairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _issues, deleted = _install_issue_registry_stub(monkeypatch)
    constructed: list[tuple[object, int, str, bool]] = []
    removed: list[str] = []

    class Store:
        def __init__(
            self,
            hass: object,
            version: int,
            key: str,
            *,
            atomic_writes: bool = False,
        ) -> None:
            constructed.append((hass, version, key, atomic_writes))
            self.key = key

        async def async_remove(self) -> None:
            removed.append(self.key)

    storage = ModuleType("homeassistant.helpers.storage")
    vars(storage)["Store"] = Store
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage)
    hass = SimpleNamespace()
    entry = SimpleNamespace(entry_id="planner-entry-1")

    asyncio.run(integration.async_remove_entry(hass, entry))

    assert constructed == [(hass, 1, "vacuum_planner.planner-entry-1", True)]
    assert removed == ["vacuum_planner.planner-entry-1"]
    assert deleted == [
        "planner-entry-1_missing_registry",
        "planner-entry-1_missing_mapping",
        "planner-entry-1_lost_capability",
        "planner-entry-1_removed_areas",
        "planner-entry-1_unresolved_external_run",
        "planner-entry-1_corrupt_store",
        "planner-entry-1_future_store",
    ]


def test_remove_entry_attempts_every_repair_delete_before_propagating_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted: list[str] = []
    issue_registry = ModuleType("homeassistant.helpers.issue_registry")

    def async_delete_issue(_hass: object, _domain: str, issue_id: str) -> None:
        deleted.append(issue_id)
        if issue_id.endswith("missing_registry"):
            raise RuntimeError("repair cleanup failed")

    vars(issue_registry)["async_delete_issue"] = async_delete_issue
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.issue_registry", issue_registry)
    store_removed: list[bool] = []

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_remove(self) -> None:
            store_removed.append(True)

    storage = ModuleType("homeassistant.helpers.storage")
    vars(storage)["Store"] = Store
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage)

    with pytest.raises(RuntimeError, match="repair cleanup failed"):
        asyncio.run(
            integration.async_remove_entry(
                SimpleNamespace(),
                SimpleNamespace(entry_id="planner-entry-1"),
            )
        )

    assert store_removed == [True]
    assert deleted == [
        "planner-entry-1_missing_registry",
        "planner-entry-1_missing_mapping",
        "planner-entry-1_lost_capability",
        "planner-entry-1_removed_areas",
        "planner-entry-1_unresolved_external_run",
        "planner-entry-1_corrupt_store",
        "planner-entry-1_future_store",
    ]


def test_remove_entry_keeps_repairs_when_store_removal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _issues, deleted = _install_issue_registry_stub(monkeypatch)

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_remove(self) -> None:
            raise OSError("storage unavailable")

    storage = ModuleType("homeassistant.helpers.storage")
    vars(storage)["Store"] = Store
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage)

    with pytest.raises(OSError, match="storage unavailable"):
        asyncio.run(
            integration.async_remove_entry(
                SimpleNamespace(),
                SimpleNamespace(entry_id="planner-entry-1"),
            )
        )

    assert deleted == []


def test_store_failures_distinguish_future_schema_from_corruption() -> None:
    repairs = importlib.import_module("custom_components.vacuum_planner.repairs")
    with pytest.raises(SchemaVersionError) as future:
        deserialize_planner_state({"schema_version": 99, "kind": "planner_state", "data": {}})

    assert repairs.store_issue_condition(future.value) == repairs.FUTURE_STORE
    assert repairs.store_issue_condition(ValueError("malformed payload")) == repairs.CORRUPT_STORE


def test_repair_fix_flow_points_topology_issues_to_reload_or_recreation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repairs_module = ModuleType("homeassistant.components.repairs")

    class RepairsFlow:
        def async_abort(self, **result: object) -> dict[str, object]:
            return {"type": "abort", **result}

    vars(repairs_module)["RepairsFlow"] = RepairsFlow
    monkeypatch.setitem(sys.modules, "homeassistant.components.repairs", repairs_module)
    sys.modules.pop("custom_components.vacuum_planner.repairs", None)
    repairs = importlib.import_module("custom_components.vacuum_planner.repairs")

    flow = asyncio.run(
        repairs.async_create_fix_flow(
            SimpleNamespace(),
            "planner-entry-1_missing_mapping",
            {"entry_id": "planner-entry-1"},
        )
    )

    assert asyncio.run(flow.async_step_init()) == {
        "type": "abort",
        "reason": "reload_or_recreate_required",
    }


def _setup_lifecycle_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mapping: object,
    payload: dict[str, Any] | None,
    registry_present: bool = True,
    supported_features: object = 16384,
) -> tuple[Any, Any, dict[str, Any], list[str]]:
    issues, deleted = _install_issue_registry_stub(monkeypatch)

    class Store:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def async_load(self) -> dict[str, Any] | None:
            return payload

        async def async_save(self, _data: dict[str, Any]) -> None:
            pass

    class StubConfigEntryNotReadyError(Exception):
        pass

    registry_entry = SimpleNamespace(
        id="vacuum-registry-entry",
        entity_id="vacuum.private",
        options={"vacuum": {"area_mapping": mapping}},
    )
    entity_registry = SimpleNamespace(
        async_get=lambda _value: registry_entry if registry_present else None
    )
    storage = ModuleType("homeassistant.helpers.storage")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    vacuum = ModuleType("homeassistant.components.vacuum")
    ha_const = ModuleType("homeassistant.const")
    exceptions = ModuleType("homeassistant.exceptions")
    vars(storage)["Store"] = Store
    vars(entity_registry_module)["async_get"] = lambda _hass: entity_registry
    vars(vacuum)["VacuumEntityFeature"] = SimpleNamespace(CLEAN_AREA=16384)
    vars(ha_const)["ATTR_SUPPORTED_FEATURES"] = "supported_features"
    vars(exceptions).update(
        ConfigEntryNotReady=StubConfigEntryNotReadyError,
        ServiceValidationError=ValueError,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", storage)
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum)
    monkeypatch.setitem(sys.modules, "homeassistant.const", ha_const)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module
    )
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions)

    hass = SimpleNamespace(
        data={},
        services=object(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": supported_features}
            )
        ),
        config_entries=SimpleNamespace(
            async_forward_entry_setups=lambda *_args: asyncio.sleep(0),
            async_update_entry=lambda *_args, **_kwargs: None,
        ),
    )
    entry = SimpleNamespace(
        entry_id="planner-entry-1",
        version=1,
        data={CONF_VACUUM_ENTITY_ID: "vacuum.private", CONF_AREA_IDS: ["private-area"]},
        options={},
        unique_id="vacuum-registry-entry",
        runtime_data=None,
    )
    return hass, entry, issues, deleted


def test_setup_keeps_missing_mapping_issue_and_clears_it_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, issues, _deleted = _setup_lifecycle_stubs(monkeypatch, mapping={}, payload=None)

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    assert list(issues) == ["planner-entry-1_missing_mapping"]

    hass, entry, issues, deleted = _setup_lifecycle_stubs(
        monkeypatch, mapping={"private-area": ["private-segment"]}, payload=None
    )
    issues["planner-entry-1_missing_mapping"] = {}

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    assert issues == {}
    assert "planner-entry-1_missing_mapping" in deleted


def test_setup_reports_missing_registry_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, issues, _deleted = _setup_lifecycle_stubs(
        monkeypatch,
        mapping={},
        payload=None,
        registry_present=False,
    )

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    assert list(issues) == ["planner-entry-1_missing_registry"]


def test_setup_reports_lost_native_area_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, issues, _deleted = _setup_lifecycle_stubs(
        monkeypatch,
        mapping={"private-area": ["private-segment"]},
        payload=None,
        supported_features=0,
    )

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    assert list(issues) == ["planner-entry-1_lost_capability"]


def test_setup_reports_configured_area_removed_from_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass, entry, issues, _deleted = _setup_lifecycle_stubs(
        monkeypatch,
        mapping={"another-area": ["private-segment"]},
        payload=None,
    )

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    assert list(issues) == ["planner-entry-1_removed_areas"]


def test_setup_reports_unresolved_external_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_revision = revision()
    persisted_revision = replace(
        persisted_revision,
        room_plans=(
            replace(
                persisted_revision.room_plans[0],
                vacuum_and_mop_interval_days=None,
                preferred_mode=PreferredMode.VACUUM,
            ),
        ),
    )
    payload = serialize_planner_state(PlannerState(persisted_revision, ledger()))
    hass, entry, issues, _deleted = _setup_lifecycle_stubs(
        monkeypatch,
        mapping={"kitchen": ["private-segment"]},
        payload=payload,
    )
    entry.data[CONF_AREA_IDS] = ["kitchen"]

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    assert list(issues) == ["planner-entry-1_unresolved_external_run"]


@pytest.mark.parametrize(
    ("payload", "condition"),
    [
        ({"schema_version": 99, "kind": "planner_state", "data": {}}, "future_store"),
        ({"schema_version": 1, "kind": "planner_state", "data": {}}, "corrupt_store"),
    ],
)
def test_setup_surfaces_durable_store_failures_as_repairs(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    condition: str,
) -> None:
    hass, entry, issues, _deleted = _setup_lifecycle_stubs(
        monkeypatch,
        mapping={"private-area": ["private-segment"]},
        payload=payload,
    )

    with pytest.raises(Exception, match="stored Vacuum Planner state"):
        asyncio.run(integration.async_setup_entry(hass, entry))

    assert list(issues) == [f"planner-entry-1_{condition}"]


def test_english_and_german_translations_cover_safe_setup_and_repairs() -> None:
    component = Path("custom_components/vacuum_planner")
    strings = json.loads((component / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((component / "translations/en.json").read_text(encoding="utf-8"))
    german = json.loads((component / "translations/de.json").read_text(encoding="utf-8"))

    assert english == strings
    for catalog in (english, german):
        removed_step = "re" + "configure"
        assert removed_step not in catalog["config"]["step"]
        assert f"{removed_step}_areas" not in catalog["config"]["step"]
        assert set(catalog["issues"]) == {
            "missing_registry",
            "missing_mapping",
            "lost_capability",
            "removed_areas",
            "unresolved_external_run",
            "corrupt_store",
            "future_store",
        }
        for issue_key in (
            "missing_registry",
            "missing_mapping",
            "lost_capability",
            "removed_areas",
        ):
            fix_flow = catalog["issues"][issue_key]["fix_flow"]
            assert "reload_or_recreate_required" in fix_flow["abort"]
            assert {"title", "description"}.issubset(fix_flow["step"]["init"])
