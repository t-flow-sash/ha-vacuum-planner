import asyncio
import sys
from types import SimpleNamespace

import pytest

from custom_components.vacuum_planner.adapters.native_area import (
    NativeAreaAdapter,
    find_dreame_mova_cleaning_mode_entity,
)
from custom_components.vacuum_planner.domain.models import Mode


def test_native_area_adapter_dispatches_ordered_ha_area_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object], dict[str, object], bool, object]] = []
    context = object()

    class Services:
        async def async_call(
            self,
            domain: str,
            service: str,
            service_data: dict[str, object],
            *,
            target: dict[str, object],
            blocking: bool,
            context: object,
        ) -> None:
            calls.append((domain, service, service_data, target, blocking, context))

    vacuum_module = SimpleNamespace(VacuumEntityFeature=SimpleNamespace(CLEAN_AREA=16384))
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 16384}
            )
        ),
    )
    adapter = NativeAreaAdapter(hass, "vacuum.downstairs")

    asyncio.run(adapter.async_dispatch(("kitchen", "hallway"), context))

    assert calls == [
        (
            "vacuum",
            "clean_area",
            {"cleaning_area_id": ["kitchen", "hallway"]},
            {"entity_id": "vacuum.downstairs"},
            True,
            context,
        )
    ]


def test_native_area_adapter_rejects_unavailable_vacuum_before_dispatch() -> None:
    calls: list[object] = []

    class Services:
        async def async_call(self, *args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(state="unavailable", attributes={})
        ),
    )
    adapter = NativeAreaAdapter(hass, "vacuum.downstairs")

    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(adapter.async_dispatch(("kitchen",), object()))

    assert calls == []


def test_native_area_adapter_rejects_missing_clean_area_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class Services:
        async def async_call(self, *args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

    vacuum_module = SimpleNamespace(VacuumEntityFeature=SimpleNamespace(CLEAN_AREA=16384))
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 0}
            )
        ),
    )
    adapter = NativeAreaAdapter(hass, "vacuum.downstairs")

    with pytest.raises(ValueError, match="CLEAN_AREA"):
        asyncio.run(adapter.async_dispatch(("kitchen",), object()))

    assert calls == []


@pytest.mark.parametrize(
    "supported_features",
    [-1, True, "16384", 16384.0, object()],
    ids=["negative", "bool", "string", "float", "object"],
)
def test_native_area_adapter_rejects_non_capability_values_without_calling_service(
    monkeypatch: pytest.MonkeyPatch,
    supported_features: object,
) -> None:
    calls: list[object] = []

    class Services:
        async def async_call(self, *args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

    vacuum_module = SimpleNamespace(VacuumEntityFeature=SimpleNamespace(CLEAN_AREA=16384))
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": supported_features}
            )
        ),
    )

    with pytest.raises(ValueError, match="CLEAN_AREA"):
        asyncio.run(
            NativeAreaAdapter(hass, "vacuum.downstairs").async_dispatch(("kitchen",), object())
        )

    assert calls == []


def test_dreame_mova_adapter_sets_confirmed_mop_mode_before_clean_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object], dict[str, object]]] = []

    class Services:
        async def async_call(
            self,
            domain: str,
            service: str,
            service_data: dict[str, object],
            *,
            target: dict[str, object],
            **_kwargs: object,
        ) -> None:
            calls.append((domain, service, service_data, target))

    vacuum_module = SimpleNamespace(VacuumEntityFeature=SimpleNamespace(CLEAN_AREA=16384))
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    states = {
        "vacuum.downstairs": SimpleNamespace(
            state="idle", attributes={"supported_features": 16384}
        ),
        "select.downstairs_cleaning_mode": SimpleNamespace(
            state="Vacuum", attributes={"options": ["Vacuum", "Vacuum and Mop"]}
        ),
    }
    adapter = NativeAreaAdapter(
        SimpleNamespace(services=Services(), states=SimpleNamespace(get=states.get)),
        "vacuum.downstairs",
        cleaning_mode_entity_id="select.downstairs_cleaning_mode",
    )

    asyncio.run(adapter.async_dispatch(("kitchen",), object(), modes=(Mode.VACUUM_AND_MOP,)))

    assert calls == [
        (
            "select",
            "select_option",
            {"option": "Vacuum and Mop"},
            {"entity_id": "select.downstairs_cleaning_mode"},
        ),
        (
            "vacuum",
            "clean_area",
            {"cleaning_area_id": ["kitchen"]},
            {"entity_id": "vacuum.downstairs"},
        ),
    ]


def test_generic_adapter_rejects_mop_mode_before_any_hardware_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class Services:
        async def async_call(self, *args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

    vacuum_module = SimpleNamespace(VacuumEntityFeature=SimpleNamespace(CLEAN_AREA=16384))
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 16384}
            )
        ),
    )

    with pytest.raises(ValueError, match=r"vacuum_and_mop.*confirmed"):
        asyncio.run(
            NativeAreaAdapter(hass, "vacuum.downstairs").async_dispatch(
                ("kitchen",), object(), modes=(Mode.VACUUM_AND_MOP,)
            )
        )

    assert calls == []


@pytest.mark.parametrize("platform", ["dreame_vacuum", "mova"])
def test_mode_capability_requires_a_live_vendor_cleaning_mode_selector(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    registry = SimpleNamespace(
        async_get=lambda _value: SimpleNamespace(device_id="device-1", platform=platform)
    )
    registry_module = SimpleNamespace(
        async_get=lambda _hass: registry,
        async_entries_for_device=lambda _registry, _device_id, **_kwargs: [
            SimpleNamespace(
                domain="select",
                entity_id="select.downstairs_cleaning_mode",
                unique_id="robot_cleaning_mode",
                disabled=False,
            )
        ],
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", registry_module)
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="Vacuum", attributes={"options": ["Vacuum", "Vacuum and Mop"]}
            )
        )
    )

    assert (
        find_dreame_mova_cleaning_mode_entity(hass, "vacuum-registry-entry")
        == "select.downstairs_cleaning_mode"
    )
