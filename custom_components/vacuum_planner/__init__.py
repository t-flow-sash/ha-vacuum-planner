"""Vacuum Planner custom integration package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast
from uuid import uuid4

import voluptuous as vol

from .adapters.native_area import NativeAreaAdapter
from .const import (
    CONF_AREA_IDS,
    CONF_CONFIG_ENTRY_ID,
    CONF_DRY_RUN,
    CONF_PLANNING_ENABLED,
    CONF_VACUUM_ENTITY_ID,
    DOMAIN,
    SERVICE_GET_QUEUE,
    SERVICE_START_NEXT,
    VacuumPlannerRuntimeData,
)
from .coordinator import PlannerCoordinator
from .domain.models import (
    BlockGuarantee,
    BlockState,
    DispatchStrategy,
    JobState,
    PlannerState,
    PlanRevision,
    PreferredMode,
    QueueLedger,
    RoomPlan,
)
from .domain.planning import AreaBinding, PlanningValidationError, build_due_snapshot
from .domain.queue import (
    StartResult,
    fail_block_commit,
    quarantine_ambiguous_dispatches,
    start_due_block,
)
from .store import PlannerStore, StoreBackend

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Context, HomeAssistant


class _RegistryEntry(Protocol):
    entity_id: str
    options: Mapping[str, object]


class _EntityRegistry(Protocol):
    def async_get(self, entity_id_or_uuid: str) -> _RegistryEntry | None: ...


class _EntityRegistryModule(Protocol):
    def async_get(self, hass: HomeAssistant) -> _EntityRegistry: ...


class _AreaEntry(Protocol):
    name: str


class _AreaRegistry(Protocol):
    def async_get_area(self, area_id: str) -> _AreaEntry | None: ...


class _AreaRegistryModule(Protocol):
    def async_get(self, hass: HomeAssistant) -> _AreaRegistry: ...


class _StoreFactory(Protocol):
    def __call__(
        self,
        hass: HomeAssistant,
        version: int,
        key: str,
        *,
        atomic_writes: bool = False,
    ) -> StoreBackend: ...


class _StorageModule(Protocol):
    Store: _StoreFactory


class _ExceptionsModule(Protocol):
    ConfigEntryNotReady: type[Exception]
    ServiceValidationError: type[Exception]


class _SupportsResponse(Protocol):
    ONLY: object


class _CoreModule(Protocol):
    SupportsResponse: _SupportsResponse


class _ServiceCall(Protocol):
    data: dict[str, object]
    context: Context


def get_queue_response(runtime_data: VacuumPlannerRuntimeData) -> dict[str, object]:
    """Return the recorder-safe public queue projection."""
    state = runtime_data.state
    if state is None:
        return {"revision": 0, "blocks": [], "jobs": []}
    return {
        "revision": state.ledger.revision,
        "blocks": [
            {
                "block_id": block.block_id,
                "kind": block.kind.value,
                "state": block.state.value,
                "guarantee": block.guarantee.value,
                "job_ids": list(block.job_ids),
            }
            for block in state.ledger.blocks
        ],
        "jobs": [
            {
                "job_id": job.job_id,
                "block_id": job.block_id,
                "area_id": job.area_id,
                "area_name": job.area_name_snapshot,
                "mode": job.mode.value,
                "state": job.state.value,
                "position": job.position,
            }
            for job in state.ledger.jobs
        ],
    }


def _register_get_queue_action(hass: HomeAssistant) -> None:
    """Register the read-only queue response action once per HA instance."""
    runtimes = hass.data[DOMAIN]

    async def async_get_queue(call: object) -> dict[str, object]:
        call_data = cast("_ServiceCall", call).data
        entry_id = cast("str", call_data[CONF_CONFIG_ENTRY_ID])
        runtime_data = cast("dict[str, VacuumPlannerRuntimeData]", runtimes).get(entry_id)
        if runtime_data is None:
            exceptions = cast(
                "_ExceptionsModule",
                import_module("homeassistant.exceptions"),
            )
            raise exceptions.ServiceValidationError("Vacuum Planner entry is not loaded")
        return get_queue_response(runtime_data)

    core = cast("_CoreModule", import_module("homeassistant.core"))
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_QUEUE,
        async_get_queue,
        schema=vol.Schema({vol.Required(CONF_CONFIG_ENTRY_ID): str}),
        supports_response=core.SupportsResponse.ONLY,
    )


def _validation_error(message: str) -> Exception:
    exceptions = cast("_ExceptionsModule", import_module("homeassistant.exceptions"))
    return exceptions.ServiceValidationError(message)


def _utcnow() -> datetime:
    """Return the current UTC time at an injectable application boundary."""
    return datetime.now(UTC)


def _resolve_area_bindings(
    hass: HomeAssistant,
    runtime_data: VacuumPlannerRuntimeData,
) -> dict[str, AreaBinding]:
    """Resolve current HA registry data into vendor-neutral snapshot bindings."""
    er = cast(
        "_EntityRegistryModule",
        import_module("homeassistant.helpers.entity_registry"),
    )
    registry_entry = er.async_get(hass).async_get(runtime_data.vacuum_entity_id)
    if registry_entry is None:
        raise _validation_error("Configured vacuum entity is no longer registered")
    vacuum_options = registry_entry.options.get("vacuum")
    area_mapping = (
        vacuum_options.get("area_mapping") if isinstance(vacuum_options, Mapping) else None
    )
    if not isinstance(area_mapping, Mapping):
        raise _validation_error("Configured vacuum has no Home Assistant area mapping")
    area_registry = cast(
        "_AreaRegistryModule",
        import_module("homeassistant.helpers.area_registry"),
    ).async_get(hass)
    state = runtime_data.state
    if state is None:
        raise _validation_error("Vacuum Planner state is unavailable")
    bindings: dict[str, AreaBinding] = {}
    for plan in state.plan_revision.room_plans:
        segments = area_mapping.get(plan.area_id)
        area = area_registry.async_get_area(plan.area_id)
        if (
            area is None
            or not isinstance(segments, list)
            or not segments
            or any(not isinstance(segment, str) or not segment.strip() for segment in segments)
        ):
            raise _validation_error(f"Area {plan.area_id} has no valid vacuum mapping")
        bindings[plan.area_id] = AreaBinding(
            area_id=plan.area_id,
            area_name=area.name,
            adapter_target=tuple(segments),
            supports_vacuum_and_mop=False,
        )
    return bindings


async def _async_dispatch_created_block(
    hass: HomeAssistant,
    runtime_data: VacuumPlannerRuntimeData,
    result: StartResult,
    context: Context,
    *,
    clock: Callable[[], datetime] = _utcnow,
) -> PlannerState:
    """Persist the native batch boundary before and after its HA service call."""
    if result.block is None:
        raise RuntimeError("created start has no block")
    if runtime_data.coordinator is None:
        raise RuntimeError("created start has no coordinator")
    block_id = result.block.block_id
    jobs = result.jobs

    def begin_commit(state: PlannerState) -> PlannerState:
        return replace(
            state,
            ledger=state.ledger.replace_block_state(
                block_id,
                BlockState.COMMITTING,
                clock(),
            ),
        )

    await runtime_data.coordinator.async_command(begin_commit)
    adapter = NativeAreaAdapter(hass, runtime_data.vacuum_entity_id)
    try:
        await adapter.async_dispatch(tuple(job.area_id for job in jobs), context)
    except Exception as err:
        failed_at = clock()

        def record_failure(state: PlannerState) -> PlannerState:
            return replace(
                state,
                ledger=fail_block_commit(
                    state.ledger,
                    block_id,
                    failed_at,
                    error_code="native_area_dispatch_failed",
                ),
            )

        await runtime_data.coordinator.async_command(record_failure)
        raise _validation_error("Native area dispatch failed") from err
    accepted_at = clock()

    def record_acceptance(state: PlannerState) -> PlannerState:
        ledger = state.ledger.replace_block_state(
            block_id,
            BlockState.COMMITTED,
            accepted_at,
        )
        for job in jobs:
            ledger = ledger.replace_job_state(
                job.job_id,
                JobState.DISPATCHING,
                accepted_at,
            )
            ledger = ledger.replace_job_state(
                job.job_id,
                JobState.ACCEPTED,
                accepted_at,
            )
        return replace(state, ledger=ledger)

    return await runtime_data.coordinator.async_command(record_acceptance)


def _register_start_next_action(hass: HomeAssistant) -> None:
    """Register safe, idempotent one-tap planning and optional native dispatch."""
    runtimes = hass.data[DOMAIN]

    async def async_start_next(call: object) -> dict[str, object]:
        service_call = cast("_ServiceCall", call)
        call_data = service_call.data
        entry_id = cast("str", call_data[CONF_CONFIG_ENTRY_ID])
        runtime_data = cast("dict[str, VacuumPlannerRuntimeData]", runtimes).get(entry_id)
        if runtime_data is None:
            raise _validation_error("Vacuum Planner entry is not loaded")
        if not runtime_data.planning_enabled:
            raise _validation_error("Vacuum Planner is paused")
        if runtime_data.coordinator is None:
            raise _validation_error("Vacuum Planner state is unavailable")
        bindings = _resolve_area_bindings(hass, runtime_data)
        evaluated_at = datetime.now(UTC)
        result: StartResult | None = None

        def command(state: PlannerState) -> PlannerState:
            nonlocal result
            try:
                snapshot = build_due_snapshot(state.plan_revision, bindings, evaluated_at)
            except PlanningValidationError as err:
                raise _validation_error(str(err)) from err
            lane_id = snapshot.lane_id
            result = start_due_block(
                state.ledger,
                snapshot,
                lane_id,
                f"start_next:{state.plan_revision.revision_id}:{evaluated_at.date().isoformat()}",
                evaluated_at,
                lambda: str(uuid4()),
                (
                    DispatchStrategy.PLANNER_SEQUENTIAL
                    if runtime_data.dry_run
                    else DispatchStrategy.NATIVE_BATCH
                ),
                BlockGuarantee.PLANNER_ATOMIC,
            )
            if result.ledger == state.ledger:
                return state
            return replace(state, ledger=result.ledger)

        updated = await runtime_data.coordinator.async_command(command)
        if result is None:
            raise RuntimeError("start_next command returned no result")
        if not runtime_data.dry_run and result.status.value == "created":
            updated = await _async_dispatch_created_block(
                hass,
                runtime_data,
                result,
                service_call.context,
            )
        return {
            "status": result.status.value,
            "block_id": result.block.block_id if result.block is not None else None,
            "area_ids": [job.area_id for job in result.jobs],
            "revision": updated.ledger.revision,
            "dry_run": runtime_data.dry_run,
        }

    core = cast("_CoreModule", import_module("homeassistant.core"))
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_NEXT,
        async_start_next,
        schema=vol.Schema({vol.Required(CONF_CONFIG_ENTRY_ID): str}),
        supports_response=core.SupportsResponse.ONLY,
    )


async def async_setup(hass: HomeAssistant, _config: object) -> bool:
    """Register integration actions independently of config-entry availability."""
    hass.data.setdefault(DOMAIN, {})
    _register_get_queue_action(hass)
    _register_start_next_action(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> bool:
    """Set up Vacuum Planner from a config entry without device side effects."""
    vacuum_entity_id = entry.data[CONF_VACUUM_ENTITY_ID]
    if entry.unique_id is not None:
        er = cast(
            "_EntityRegistryModule",
            import_module("homeassistant.helpers.entity_registry"),
        )
        registry_entry = er.async_get(hass).async_get(entry.unique_id)
        if registry_entry is not None:
            vacuum_entity_id = registry_entry.entity_id
            if vacuum_entity_id != entry.data[CONF_VACUUM_ENTITY_ID]:
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_VACUUM_ENTITY_ID: vacuum_entity_id},
                )
    planner_store = None
    planner_state = None
    coordinator = None
    if entry_id := getattr(entry, "entry_id", None):
        storage = cast(
            "_StorageModule",
            import_module("homeassistant.helpers.storage"),
        )
        planner_store = PlannerStore(
            storage.Store(
                hass,
                1,
                f"{DOMAIN}.{entry_id}",
                atomic_writes=True,
            )
        )
        try:
            planner_state = await planner_store.async_load()
            if planner_state is None:
                lane_id = entry.unique_id or entry_id
                planner_state = PlannerState(
                    plan_revision=PlanRevision(
                        revision_id=str(uuid4()),
                        created_at=datetime.now(UTC),
                        room_plans=tuple(
                            RoomPlan(
                                area_id=area_id,
                                lane_id=lane_id,
                                enabled=True,
                                vacuum_interval_days=7,
                                vacuum_and_mop_interval_days=None,
                                preferred_mode=PreferredMode.VACUUM,
                                priority=0,
                            )
                            for area_id in entry.data.get(CONF_AREA_IDS, ())
                        ),
                    ),
                    ledger=QueueLedger.empty(),
                )
                await planner_store.async_save(planner_state)
            else:
                recovered_ledger = quarantine_ambiguous_dispatches(
                    planner_state.ledger, datetime.now(UTC)
                )
                if (
                    recovered_ledger.blocks != planner_state.ledger.blocks
                    or recovered_ledger.jobs != planner_state.ledger.jobs
                ):
                    planner_state = replace(planner_state, ledger=recovered_ledger)
                    await planner_store.async_save(planner_state)
            coordinator = PlannerCoordinator(planner_state, planner_store)
        except OSError as err:
            exceptions = cast(
                "_ExceptionsModule",
                import_module("homeassistant.exceptions"),
            )
            raise exceptions.ConfigEntryNotReady(
                "Unable to load or initialize stored Vacuum Planner state"
            ) from err
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id=vacuum_entity_id,
        planning_enabled=entry.options.get(CONF_PLANNING_ENABLED, True),
        dry_run=entry.options.get(CONF_DRY_RUN, True),
        store=planner_store,
        coordinator=coordinator,
    )
    entry.runtime_data = runtime_data
    if (
        (entry_id := getattr(entry, "entry_id", None))
        and hasattr(hass, "data")
        and hasattr(hass, "services")
    ):
        hass.data.setdefault(DOMAIN, {})[entry_id] = runtime_data
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> bool:
    """Unload a Vacuum Planner config entry."""
    if entry_id := getattr(entry, "entry_id", None):
        runtimes = hass.data.get(DOMAIN, {})
        runtimes.pop(entry_id, None)
    entry.runtime_data = None
    return True
