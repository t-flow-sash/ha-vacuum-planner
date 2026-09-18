import asyncio
import sys
from types import SimpleNamespace

import pytest

from custom_components.vacuum_planner.adapters.native_area import NativeAreaAdapter


def test_native_area_adapter_dispatches_ordered_ha_area_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[
        tuple[str, str, dict[str, object], dict[str, object], bool, object]
    ] = []
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

    vacuum_module = SimpleNamespace(VacuumEntityFeature=SimpleNamespace(CLEAN_AREA=1024))
    monkeypatch.setitem(sys.modules, "homeassistant.components.vacuum", vacuum_module)
    hass = SimpleNamespace(
        services=Services(),
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                state="idle", attributes={"supported_features": 1024}
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

    vacuum_module = SimpleNamespace(VacuumEntityFeature=SimpleNamespace(CLEAN_AREA=1024))
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
