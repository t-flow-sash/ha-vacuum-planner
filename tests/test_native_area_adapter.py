import asyncio
from types import SimpleNamespace

from custom_components.vacuum_planner.adapters.native_area import NativeAreaAdapter


def test_native_area_adapter_dispatches_ordered_ha_area_ids() -> None:
    calls: list[
        tuple[str, str, dict[str, object], dict[str, object], bool]
    ] = []

    class Services:
        async def async_call(
            self,
            domain: str,
            service: str,
            service_data: dict[str, object],
            *,
            target: dict[str, object],
            blocking: bool,
        ) -> None:
            calls.append((domain, service, service_data, target, blocking))

    hass = SimpleNamespace(services=Services())
    adapter = NativeAreaAdapter(hass, "vacuum.downstairs")

    asyncio.run(adapter.async_dispatch(("kitchen", "hallway")))

    assert calls == [
        (
            "vacuum",
            "clean_area",
            {"cleaning_area_id": ["kitchen", "hallway"]},
            {"entity_id": "vacuum.downstairs"},
            True,
        )
    ]
