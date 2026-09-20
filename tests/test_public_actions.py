import asyncio
import sys
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest
import voluptuous as vol

from custom_components import vacuum_planner as integration
from custom_components.vacuum_planner.const import VacuumPlannerRuntimeData
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockState,
    DispatchStrategy,
    JobState,
    Mode,
    PlannerState,
    PlanRevision,
    PlanSnapshot,
    PreferredMode,
    QueueLedger,
    RoomPlan,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import start_due_block
from custom_components.vacuum_planner.public_actions import (
    cancel_pending_block,
    postpone_area,
    skip_area_today,
)

NOW = datetime(2026, 9, 19, 8, tzinfo=UTC)


def state_with_sealed_block() -> PlannerState:
    ids = iter(("block", "job"))
    result = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot(
            "revision",
            "lane",
            NOW,
            (SnapshotJob("kitchen", "Kitchen", "private-target", Mode.VACUUM, 0, NOW),),
        ),
        "lane",
        "key",
        NOW,
        lambda: next(ids),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    plan = RoomPlan("kitchen", "lane", True, 1, None, PreferredMode.VACUUM, 0)
    return PlannerState(PlanRevision("revision", NOW, (plan,)), result.ledger)


def test_postpone_and_safe_cancel_are_pure_fail_closed_commands() -> None:
    state = postpone_area(state_with_sealed_block(), "kitchen", NOW, 2, "revision-2")
    assert state.plan_revision.room_plans[0].skip_until == datetime(2026, 9, 21, 8, tzinfo=UTC)

    state = cancel_pending_block(state, "block", NOW)
    assert state.ledger.blocks[0].state is BlockState.CANCELLED
    assert state.ledger.jobs[0].state is JobState.CANCELLED
    assert "private-target" not in str(
        {
            "block_id": state.ledger.blocks[0].block_id,
            "area_id": state.ledger.jobs[0].area_id,
        }
    )


def test_skip_today_uses_next_home_assistant_local_midnight() -> None:
    state = skip_area_today(
        state_with_sealed_block(), "kitchen", NOW, "Europe/Berlin", "revision-2"
    )
    assert state.plan_revision.room_plans[0].skip_until == datetime(2026, 9, 19, 22, tzinfo=UTC)


def test_cancel_rejects_ambiguous_external_work() -> None:
    state = state_with_sealed_block()
    committed_ledger = state.ledger.replace_block_state("block", BlockState.COMMITTING, NOW)
    committed_ledger = committed_ledger.replace_block_state("block", BlockState.COMMITTED, NOW)
    committed = PlannerState(state.plan_revision, committed_ledger)

    with pytest.raises(ValueError, match="adapter cancellation confirmation"):
        cancel_pending_block(committed, "block", NOW)


def test_all_public_actions_are_registered_with_explicit_entry_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[
        str, tuple[Callable[..., Coroutine[object, object, object]], object, object]
    ] = {}

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[..., Coroutine[object, object, object]],
            *,
            schema: object,
            supports_response: object,
        ) -> None:
            registered[f"{domain}.{service}"] = (handler, schema, supports_response)

    core = ModuleType("homeassistant.core")
    vars(core)["SupportsResponse"] = SimpleNamespace(ONLY="only", OPTIONAL="optional")
    monkeypatch.setitem(sys.modules, "homeassistant.core", core)
    hass = SimpleNamespace(data={}, services=Services())

    assert asyncio.run(integration.async_setup(hass, {})) is True
    expected = {
        "start_next",
        "skip_area_today",
        "postpone_area",
        "cancel_block",
        "resolve_uncertain_run",
        "get_queue",
    }
    assert {name.removeprefix("vacuum_planner.") for name in registered} == expected
    for name, (_handler, schema, supports_response) in registered.items():
        assert isinstance(schema, vol.Schema)
        assert supports_response == ("only" if name.endswith(".get_queue") else "optional")
        with pytest.raises(vol.Invalid):
            schema({})
    postpone_schema = cast("vol.Schema", registered["vacuum_planner.postpone_area"][1])
    for invalid_days in (True, False, 0, 366, "2"):
        with pytest.raises(vol.Invalid):
            postpone_schema(
                {"config_entry_id": "entry", "area_id": "kitchen", "days": invalid_days}
            )
    for empty_field in ("config_entry_id", "area_id"):
        payload: dict[str, object] = {
            "config_entry_id": "entry",
            "area_id": "kitchen",
            "days": 1,
        }
        payload[empty_field] = ""
        with pytest.raises(vol.Invalid):
            postpone_schema(payload)


def test_skip_service_uses_local_midnight_through_shared_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[str, Callable[..., Coroutine[object, object, object]]] = {}
    saved: list[PlannerState] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[..., Coroutine[object, object, object]],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

    core = ModuleType("homeassistant.core")
    exceptions = ModuleType("homeassistant.exceptions")
    vars(core)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions)["ServiceValidationError"] = ValueError
    monkeypatch.setitem(sys.modules, "homeassistant.core", core)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions)
    monkeypatch.setattr(integration, "_utcnow", lambda: NOW)

    coordinator = PlannerCoordinator(state_with_sealed_block(), Store())
    runtime = VacuumPlannerRuntimeData("vacuum.test", coordinator=coordinator)
    hass = SimpleNamespace(
        data={"vacuum_planner": {"entry": runtime}},
        services=Services(),
        config=SimpleNamespace(time_zone="Europe/Berlin"),
    )
    assert asyncio.run(integration.async_setup(hass, {})) is True

    response = asyncio.run(
        registered["vacuum_planner.skip_area_today"](
            SimpleNamespace(data={"config_entry_id": "entry", "area_id": "kitchen"})
        )
    )

    assert response == {"status": "skipped_today"}
    assert coordinator.state.plan_revision.room_plans[0].skip_until == datetime(
        2026, 9, 19, 22, tzinfo=UTC
    )
    assert saved == [coordinator.state]


def test_latched_topology_blocks_every_public_mutation_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: dict[str, Callable[..., Coroutine[object, object, object]]] = {}
    saved: list[PlannerState] = []
    side_effects: list[object] = []

    class Store:
        async def async_save(self, state: PlannerState) -> None:
            saved.append(state)

    class Services:
        def async_register(
            self,
            domain: str,
            service: str,
            handler: Callable[..., Coroutine[object, object, object]],
            **_kwargs: object,
        ) -> None:
            registered[f"{domain}.{service}"] = handler

        async def async_call(self, *args: object, **kwargs: object) -> None:
            side_effects.append((args, kwargs))

    class StubServiceValidationError(Exception):
        pass

    core = ModuleType("homeassistant.core")
    exceptions = ModuleType("homeassistant.exceptions")
    vars(core)["SupportsResponse"] = SimpleNamespace(ONLY="only")
    vars(exceptions)["ServiceValidationError"] = StubServiceValidationError
    monkeypatch.setitem(sys.modules, "homeassistant.core", core)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions)

    initial = state_with_sealed_block()
    coordinator = PlannerCoordinator(initial, Store())
    runtime = VacuumPlannerRuntimeData("vacuum.test", coordinator=coordinator, topology_ready=False)
    hass = SimpleNamespace(
        data={"vacuum_planner": {"entry": runtime}},
        services=Services(),
        config=SimpleNamespace(time_zone="UTC"),
    )
    assert asyncio.run(integration.async_setup(hass, {})) is True

    calls = {
        "start_next": {"config_entry_id": "entry"},
        "skip_area_today": {"config_entry_id": "entry", "area_id": "kitchen"},
        "postpone_area": {"config_entry_id": "entry", "area_id": "kitchen", "days": 1},
        "cancel_block": {"config_entry_id": "entry", "block_id": "block"},
        "resolve_uncertain_run": {
            "config_entry_id": "entry",
            "job_id": "job",
            "resolution": "retry_safe",
        },
    }
    for action, data in calls.items():
        with pytest.raises(
            StubServiceValidationError,
            match=r"topology.*reload|reload.*topology",
        ):
            asyncio.run(
                registered[f"vacuum_planner.{action}"](SimpleNamespace(data=data, context=object()))
            )

    assert coordinator.state == initial
    assert saved == []
    assert side_effects == []


def test_latched_topology_blocks_planning_switch_mutation_before_commit() -> None:
    committed: list[bool] = []

    class Store:
        async def async_save(self, _state: PlannerState) -> None:
            pass

    runtime = VacuumPlannerRuntimeData(
        "vacuum.test",
        coordinator=PlannerCoordinator(state_with_sealed_block(), Store()),
        topology_ready=False,
    )

    with pytest.raises(RuntimeError, match=r"topology.*reload|reload.*topology"):
        asyncio.run(
            runtime.async_set_planning_enabled(
                enabled=False,
                commit=lambda: committed.append(True),
            )
        )

    assert runtime.planning_enabled is True
    assert committed == []
