import asyncio
import importlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any, Protocol, cast

import pytest

from custom_components.vacuum_planner.const import PLATFORMS, VacuumPlannerRuntimeData
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import PlannerState, PlanRevision, QueueLedger

NOW = datetime(2026, 9, 19, tzinfo=UTC)


class NullStore:
    async def async_save(self, _state: PlannerState) -> None:
        pass


class BaseEntity:
    _attr_unique_id: str
    _attr_device_info: dict[str, object]

    def __init__(self) -> None:
        self.hass: Any = None

    async def async_added_to_hass(self) -> None:
        pass

    def async_on_remove(self, _callback: object) -> None:
        pass

    def async_write_ha_state(self) -> None:
        pass

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def device_info(self) -> dict[str, object]:
        return self._attr_device_info


class CreatedEntity(Protocol):
    unique_id: str
    device_info: dict[str, object]


def install_platform_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, entity_name in (
        ("binary_sensor", "BinarySensorEntity"),
        ("button", "ButtonEntity"),
        ("switch", "SwitchEntity"),
    ):
        module = ModuleType(f"homeassistant.components.{name}")
        vars(module)[entity_name] = BaseEntity
        monkeypatch.setitem(sys.modules, f"homeassistant.components.{name}", module)
    device = ModuleType("homeassistant.helpers.device_registry")
    const = ModuleType("homeassistant.const")
    vars(device)["DeviceEntryType"] = SimpleNamespace(SERVICE="service")
    vars(const)["EntityCategory"] = SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic")
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.device_registry", device)
    monkeypatch.setitem(sys.modules, "homeassistant.const", const)


def entry() -> SimpleNamespace:
    state = PlannerState(PlanRevision("revision", NOW, ()), QueueLedger.empty())
    return SimpleNamespace(
        entry_id="entry-1",
        title="Planner",
        options={},
        runtime_data=VacuumPlannerRuntimeData(
            vacuum_entity_id="vacuum.test",
            coordinator=PlannerCoordinator(state, NullStore()),
        ),
    )


def test_public_platforms_expose_stable_service_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    install_platform_stubs(monkeypatch)
    assert PLATFORMS == ("sensor", "switch", "binary_sensor", "button", "number")
    created: list[object] = []
    config_entry = entry()

    for platform in ("switch", "binary_sensor", "button"):
        sys.modules.pop(f"custom_components.vacuum_planner.{platform}", None)
        module = importlib.import_module(f"custom_components.vacuum_planner.{platform}")
        asyncio.run(module.async_setup_entry(SimpleNamespace(), config_entry, created.extend))

    typed_created = cast("list[CreatedEntity]", created)
    assert {item.unique_id for item in typed_created} == {
        "entry-1_planning",
        "entry-1_ready",
        "entry-1_attention",
        "entry-1_start_next",
        "entry-1_cancel_current_block",
    }
    assert all(item.device_info["entry_type"] == "service" for item in typed_created)


def test_switch_and_buttons_use_public_actions_and_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_platform_stubs(monkeypatch)
    switch = importlib.import_module("custom_components.vacuum_planner.switch")
    button = importlib.import_module("custom_components.vacuum_planner.button")
    config_entry = entry()
    options: list[dict[str, object]] = []
    calls: list[tuple[str, str, dict[str, object]]] = []

    async def async_call(
        domain: str, service: str, data: dict[str, object], **_kwargs: object
    ) -> None:
        calls.append((domain, service, data))

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda _entry, **kwargs: options.append(kwargs["options"])
        ),
        services=SimpleNamespace(async_call=async_call),
    )

    planning = switch.VacuumPlannerPlanningSwitch(config_entry)
    planning.hass = hass
    asyncio.run(planning.async_turn_off())
    assert config_entry.runtime_data.planning_enabled is False
    assert options == [{"planning_enabled": False}]

    start = button.VacuumPlannerStartNextButton(config_entry)
    start.hass = hass
    asyncio.run(start.async_press())
    assert calls == [("vacuum_planner", "start_next", {"config_entry_id": "entry-1"})]


def test_cancel_button_does_not_target_committed_external_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_platform_stubs(monkeypatch)
    button = importlib.import_module("custom_components.vacuum_planner.button")
    config_entry = entry()
    config_entry.runtime_data.coordinator._state = SimpleNamespace(  # noqa: SLF001
        ledger=SimpleNamespace(
            blocks=(SimpleNamespace(block_id="committed", state=button.BlockState.COMMITTED),)
        )
    )
    calls: list[object] = []

    async def async_call(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    cancel = button.VacuumPlannerCancelCurrentBlockButton(config_entry)
    cancel.hass = SimpleNamespace(services=SimpleNamespace(async_call=async_call))
    asyncio.run(cancel.async_press())

    assert calls == []


@pytest.mark.parametrize("failure", ["persist", "runtime"])
def test_planning_switch_rolls_back_atomically_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    install_platform_stubs(monkeypatch)
    switch = importlib.import_module("custom_components.vacuum_planner.switch")
    config_entry = entry()
    published: list[bool] = []
    original_set_enabled = VacuumPlannerRuntimeData.async_set_planning_enabled

    async def set_enabled(
        runtime: VacuumPlannerRuntimeData,
        *,
        enabled: bool,
        commit: Callable[[], None] | None = None,
        rollback: Callable[[], None] | None = None,
    ) -> None:
        if failure == "runtime":
            assert commit is not None
            assert rollback is not None
            commit()
            rollback()
            raise RuntimeError("runtime failed")
        await original_set_enabled(
            runtime,
            enabled=enabled,
            commit=commit,
            rollback=rollback,
        )

    monkeypatch.setattr(
        VacuumPlannerRuntimeData,
        "async_set_planning_enabled",
        set_enabled,
    )

    update_attempt = 0

    def update_entry(_entry: object, *, options: dict[str, object]) -> None:
        nonlocal update_attempt
        update_attempt += 1
        if failure == "persist" and update_attempt == 1:
            raise RuntimeError("persist failed")
        config_entry.options = options

    planning = switch.VacuumPlannerPlanningSwitch(config_entry)
    planning.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))

    with pytest.raises(RuntimeError, match="failed"):
        asyncio.run(planning.async_turn_off())

    assert config_entry.options == {}
    assert config_entry.runtime_data.planning_enabled is True
    assert published == []


def test_planning_switch_fails_closed_when_option_rollback_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_platform_stubs(monkeypatch)
    switch = importlib.import_module("custom_components.vacuum_planner.switch")
    config_entry = entry()
    attempts = 0

    def update_entry(_entry: object, *, options: dict[str, object]) -> None:
        nonlocal attempts
        attempts += 1
        config_entry.options = options
        raise RuntimeError("options unavailable")

    planning = switch.VacuumPlannerPlanningSwitch(config_entry)
    planning.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))

    with pytest.raises(RuntimeError, match="fail-closed"):
        asyncio.run(planning.async_turn_on())

    assert attempts == 2
    assert config_entry.runtime_data.planning_enabled is False
