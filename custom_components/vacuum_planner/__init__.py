"""Vacuum Planner custom integration package."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, TypeVar, cast
from uuid import uuid4

import voluptuous as vol

from .adapters.native_area import (
    NativeAreaAdapter,
    find_dreame_mova_cleaning_mode_entity,
    resolve_bound_cleaning_mode_entity,
)
from .const import (
    CONF_AREA_ACTIVE,
    CONF_AREA_IDS,
    CONF_AREA_PLANS,
    CONF_CONFIG_ENTRY_ID,
    CONF_DRY_RUN,
    CONF_MODE,
    CONF_MOP_INTERVAL_DAYS,
    CONF_PLANNING_ENABLED,
    CONF_PRIORITY,
    CONF_VACUUM_ENTITY_ID,
    CONF_VACUUM_INTERVAL_DAYS,
    DOMAIN,
    PLATFORMS,
    SERVICE_CANCEL_BLOCK,
    SERVICE_GET_QUEUE,
    SERVICE_POSTPONE_AREA,
    SERVICE_RESOLVE_UNCERTAIN_RUN,
    SERVICE_SKIP_AREA_TODAY,
    SERVICE_START_NEXT,
    RuntimeInactiveError,
    TopologyNotReadyError,
    VacuumPlannerRuntimeData,
    activate_commands,
    invalidate_commands,
    invalidate_observations,
    shutdown_runtime,
)
from .coordinator import PlannerCoordinator
from .domain.models import (
    BlockGuarantee,
    BlockState,
    DispatchStrategy,
    JobState,
    PlannerState,
    PlanRevision,
    PlanSnapshot,
    PreferredMode,
    QueueJob,
    QueueLedger,
    RoomPlan,
)
from .domain.planning import AreaBinding, PlanningValidationError, build_due_snapshot
from .domain.queue import (
    StartResult,
    StartStatus,
    UncertainResolution,
    begin_native_batch_commit,
    quarantine_ambiguous_dispatches,
    quarantine_block_dispatch,
    resolve_uncertain_job,
    start_due_block,
)
from .integration_observer import async_apply_observation
from .public_actions import cancel_pending_block, postpone_area, skip_area_today
from .repairs import (
    LOST_CAPABILITY,
    MISSING_MAPPING,
    MISSING_REGISTRY,
    REMOVED_AREAS,
    UNRESOLVED_EXTERNAL_RUN,
    async_clear_entry_issues,
    async_create_entry_issue,
    async_reconcile_entry_issues,
    async_reconcile_unresolved_external_run,
    store_issue_condition,
)
from .store import PlannerStore, StoreBackend
from .topology import area_mapping, async_get_valid_vacuum, validate_area_ids

CONFIG_SCHEMA = vol.Schema(
    {vol.Optional(DOMAIN): vol.Schema({})},
    extra=vol.ALLOW_EXTRA,
)

if TYPE_CHECKING:
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
    OPTIONAL: object


class _CoreModule(Protocol):
    SupportsResponse: _SupportsResponse


class _ServiceCall(Protocol):
    data: dict[str, object]
    context: Context


_T = TypeVar("_T")
_MAX_POSTPONE_DAYS = 365


def _non_empty_string(value: object) -> str:
    """Validate an identifier without Voluptuous' permissive coercions."""
    if type(value) is not str or not value.strip():
        raise vol.Invalid("value must be a non-empty string")
    return value


def _postpone_days(value: object) -> int:
    """Validate the documented bounded postpone interval without accepting bool."""
    if type(value) is not int or not 1 <= value <= _MAX_POSTPONE_DAYS:
        raise vol.Invalid("days must be an integer from 1 through 365")
    return value


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
        schema=vol.Schema({vol.Required(CONF_CONFIG_ENTRY_ID): _non_empty_string}),
        supports_response=core.SupportsResponse.ONLY,
    )


def _validation_error(message: str) -> Exception:
    exceptions = cast("_ExceptionsModule", import_module("homeassistant.exceptions"))
    return exceptions.ServiceValidationError(message)


def _runtime_for_action(runtimes: object, entry_id: str) -> VacuumPlannerRuntimeData:
    """Resolve one explicitly addressed loaded config entry."""
    runtime = cast("dict[str, VacuumPlannerRuntimeData]", runtimes).get(entry_id)
    if runtime is None:
        raise _validation_error("Vacuum Planner entry is not loaded")
    if runtime.coordinator is None:
        raise _validation_error("Vacuum Planner state is unavailable")
    return runtime


def _capture_runtime_command(runtime: VacuumPlannerRuntimeData) -> int:
    """Capture a runtime command generation as a public validation boundary."""
    try:
        return runtime.capture_command_generation()
    except RuntimeInactiveError as err:
        raise _validation_error(str(err)) from err


def _utcnow() -> datetime:
    """Return the current UTC time at an injectable application boundary."""
    return datetime.now(UTC)


def _resolve_command_vacuum(
    hass: HomeAssistant,
    runtime_data: VacuumPlannerRuntimeData,
) -> str:
    """Resolve the stable registry ID at command time and fail closed."""
    registry_id = runtime_data.vacuum_registry_id
    if registry_id is None:
        raise _validation_error("Configured vacuum has no stable registry identity")
    er = cast(
        "_EntityRegistryModule",
        import_module("homeassistant.helpers.entity_registry"),
    )
    registry_entry = er.async_get(hass).async_get(registry_id)
    entity_id = getattr(registry_entry, "entity_id", None)
    if (
        registry_entry is None
        or getattr(registry_entry, "id", None) != registry_id
        or getattr(registry_entry, "domain", None) != "vacuum"
        or getattr(registry_entry, "disabled", False)
        or getattr(registry_entry, "disabled_by", None) is not None
        or not isinstance(entity_id, str)
    ):
        failure_callback = runtime_data.topology_failure_callback
        if failure_callback is not None:
            failure_callback(MISSING_REGISTRY)
        elif runtime_data.topology_ready:
            runtime_data.topology_ready = False
            invalidate_observations(runtime_data)
            if runtime_data.coordinator is not None:
                runtime_data.coordinator.publish_runtime_projection()
            if runtime_data.config_entry_id is not None:
                async_create_entry_issue(hass, runtime_data.config_entry_id, MISSING_REGISTRY)
        raise _validation_error("Configured vacuum is no longer registered")
    return entity_id


def _resolve_command_cleaning_mode(
    hass: HomeAssistant,
    runtime_data: VacuumPlannerRuntimeData,
) -> str | None:
    """Resolve only the setup-bound selector and latch if required identity is lost."""
    if not runtime_data.requires_vacuum_and_mop:
        return None
    entity_id = resolve_bound_cleaning_mode_entity(
        hass,
        runtime_data.cleaning_mode_registry_id,
    )
    if entity_id is not None:
        return entity_id
    runtime_data.topology_ready = False
    invalidate_observations(runtime_data)
    if runtime_data.coordinator is not None:
        runtime_data.coordinator.publish_runtime_projection()
    if runtime_data.config_entry_id is not None:
        async_create_entry_issue(hass, runtime_data.config_entry_id, LOST_CAPABILITY)
    raise _validation_error("Configured cleaning mode selector is no longer available")


def _resolve_area_bindings(
    hass: HomeAssistant,
    runtime_data: VacuumPlannerRuntimeData,
) -> dict[str, AreaBinding]:
    """Resolve current HA registry data into vendor-neutral snapshot bindings."""
    er = cast(
        "_EntityRegistryModule",
        import_module("homeassistant.helpers.entity_registry"),
    )
    registry_entry = er.async_get(hass).async_get(
        runtime_data.vacuum_registry_id or runtime_data.vacuum_entity_id
    )
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
    supports_vacuum_and_mop = _resolve_command_cleaning_mode(hass, runtime_data) is not None
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
            supports_vacuum_and_mop=supports_vacuum_and_mop,
        )
    return bindings


@dataclass
class _NativeDispatchClaim:
    """Atomically record whether this caller claimed a sealed block."""

    block_id: str
    clock: Callable[[], datetime]
    claimed: bool = False

    def __call__(self, state: PlannerState) -> PlannerState:
        block = next((item for item in state.ledger.blocks if item.block_id == self.block_id), None)
        if block is None:
            raise KeyError(self.block_id)
        if block.state is not BlockState.SEALED:
            return state
        self.claimed = True
        return replace(
            state,
            ledger=begin_native_batch_commit(
                state.ledger,
                self.block_id,
                self.clock(),
            ),
        )


def _record_dispatch_acceptance(
    state: PlannerState,
    block_id: str,
    jobs: tuple[QueueJob, ...],
    accepted_at: datetime,
) -> PlannerState:
    """Apply the persisted acceptance transition for one native batch."""
    block = next(item for item in state.ledger.blocks if item.block_id == block_id)
    if block.state in {
        BlockState.RUNNING,
        BlockState.COMPLETED,
        BlockState.FAILED,
        BlockState.UNCERTAIN,
    }:
        return state
    ledger = state.ledger.replace_block_state(
        block_id,
        BlockState.COMMITTED,
        accepted_at,
    )
    for job in jobs:
        ledger = ledger.replace_job_state(
            job.job_id,
            JobState.ACCEPTED,
            accepted_at,
        )
    return replace(state, ledger=ledger)


async def _async_quarantine_dispatch(
    coordinator: PlannerCoordinator,
    block_id: str,
    clock: Callable[[], datetime],
    *,
    guard: Callable[[], None] | None = None,
) -> None:
    """Persist UNCERTAIN even if the caller is cancelled again while shielding."""
    reconciled_at = clock()

    def record_uncertain(state: PlannerState) -> PlannerState:
        block = next(item for item in state.ledger.blocks if item.block_id == block_id)
        if block.state in {
            BlockState.RUNNING,
            BlockState.COMPLETED,
            BlockState.FAILED,
            BlockState.UNCERTAIN,
        }:
            return state
        return replace(
            state,
            ledger=quarantine_block_dispatch(
                state.ledger,
                block_id,
                reconciled_at,
            ),
        )

    quarantine_task = asyncio.create_task(coordinator.async_command(record_uncertain, guard=guard))
    deferred_cancellation: asyncio.CancelledError | None = None
    while not quarantine_task.done():
        try:
            await asyncio.shield(quarantine_task)
        except asyncio.CancelledError as err:
            deferred_cancellation = err
    quarantine_task.result()
    if deferred_cancellation is not None:
        raise deferred_cancellation


async def _async_run_ambiguous_operation(
    operation: Awaitable[_T],
    quarantine: Callable[[], Awaitable[None]],
    failure_message: str,
) -> _T:
    """Quarantine a claimed dispatch whenever its outcome becomes ambiguous."""
    try:
        return await operation
    except TopologyNotReadyError as err:
        await quarantine()
        raise _validation_error(failure_message) from err
    except RuntimeInactiveError:
        raise
    except asyncio.CancelledError:
        await quarantine()
        raise
    except Exception as err:
        await quarantine()
        raise _validation_error(failure_message) from err


async def _async_dispatch_created_block(
    hass: HomeAssistant,
    runtime_data: VacuumPlannerRuntimeData,
    result: StartResult,
    context: Context,
    *,
    clock: Callable[[], datetime] = _utcnow,
    command_generation: int | None = None,
) -> PlannerState:
    """Persist the native batch boundary before and after its HA service call."""
    if result.block is None:
        raise RuntimeError("created start has no block")
    coordinator = runtime_data.coordinator
    if coordinator is None:
        raise RuntimeError("created start has no coordinator")
    if command_generation is None:
        command_generation = runtime_data.capture_command_generation()

    def guard() -> None:
        runtime_data.require_command_generation(command_generation)

    block_id = result.block.block_id
    vacuum_entity_id = _resolve_command_vacuum(hass, runtime_data)
    cleaning_mode_entity_id = _resolve_command_cleaning_mode(hass, runtime_data)
    adapter = NativeAreaAdapter(
        hass,
        vacuum_entity_id,
        cleaning_mode_entity_id=cleaning_mode_entity_id,
        before_side_effect=guard,
    )
    try:
        mode_option = adapter.preflight(tuple(job.mode for job in result.jobs))
    except Exception as err:
        raise _validation_error("Native area dispatch preflight failed") from err

    claim = _NativeDispatchClaim(block_id, clock)
    await coordinator.async_command(claim, guard=guard)
    if not claim.claimed:
        return coordinator.state

    async def quarantine() -> None:
        await _async_quarantine_dispatch(
            coordinator,
            block_id,
            clock,
            guard=lambda: runtime_data.require_runtime_generation(command_generation),
        )

    await _async_run_ambiguous_operation(
        adapter.async_dispatch_after_preflight(
            tuple(job.area_id for job in result.jobs),
            context,
            mode_option=mode_option,
        ),
        quarantine,
        "Native area dispatch failed",
    )
    accepted_at = clock()
    accepted_state = await _async_run_ambiguous_operation(
        coordinator.async_command(
            lambda state: _record_dispatch_acceptance(
                state,
                block_id,
                result.jobs,
                accepted_at,
            ),
            guard=guard,
        ),
        quarantine,
        "Native area dispatch acceptance could not be persisted",
    )
    guard()
    return accepted_state


def _register_start_next_action(hass: HomeAssistant) -> None:  # noqa: C901, PLR0915
    """Register safe, idempotent one-tap planning and optional native dispatch."""
    runtimes = hass.data[DOMAIN]

    async def async_start_next(  # noqa: C901 - atomic recovery/start boundary
        call: object,
    ) -> dict[str, object]:
        service_call = cast("_ServiceCall", call)
        call_data = service_call.data
        entry_id = cast("str", call_data[CONF_CONFIG_ENTRY_ID])
        runtime_data = cast("dict[str, VacuumPlannerRuntimeData]", runtimes).get(entry_id)
        if runtime_data is None:
            raise _validation_error("Vacuum Planner entry is not loaded")
        if runtime_data.coordinator is None:
            raise _validation_error("Vacuum Planner state is unavailable")
        command_generation = _capture_runtime_command(runtime_data)

        def guard() -> None:
            runtime_data.require_command_generation(command_generation)

        evaluated_at = _utcnow()
        result: StartResult | None = None
        dry_run_block_cancelled = False

        def command(state: PlannerState) -> PlannerState:
            nonlocal dry_run_block_cancelled, result
            if not runtime_data.planning_enabled:
                raise _validation_error("Vacuum Planner is paused")
            incompatible_dry_run_block = next(
                (
                    block
                    for block in state.ledger.blocks
                    if block.state is BlockState.SEALED
                    and block.dispatch_strategy is DispatchStrategy.PLANNER_SEQUENTIAL
                ),
                None,
            )
            if not runtime_data.dry_run and incompatible_dry_run_block is not None:
                dry_run_block_cancelled = True
                return cancel_pending_block(
                    state,
                    incompatible_dry_run_block.block_id,
                    evaluated_at,
                )
            recovery_block = next(
                (
                    block
                    for block in state.ledger.blocks
                    if block.state is BlockState.SEALED
                    and block.dispatch_strategy is DispatchStrategy.NATIVE_BATCH
                ),
                None,
            )
            if not runtime_data.dry_run and recovery_block is not None:
                jobs_by_id = {job.job_id: job for job in state.ledger.jobs}
                result = StartResult(
                    StartStatus.EXISTING,
                    state.ledger,
                    recovery_block,
                    tuple(jobs_by_id[job_id] for job_id in recovery_block.job_ids),
                )
                return state
            bindings = _resolve_area_bindings(hass, runtime_data)
            try:
                due_snapshot = build_due_snapshot(state.plan_revision, bindings, evaluated_at)
            except PlanningValidationError as err:
                raise _validation_error(str(err)) from err
            snapshot = PlanSnapshot(
                due_snapshot.plan_revision,
                due_snapshot.lane_id,
                due_snapshot.evaluated_at,
                due_snapshot.jobs[:1],
            )
            lane_id = snapshot.lane_id
            idempotency_key = call_data.get("idempotency_key")
            result = start_due_block(
                state.ledger,
                snapshot,
                lane_id,
                (
                    cast("str", idempotency_key)
                    if idempotency_key is not None
                    else f"start_next:{state.plan_revision.revision_id}:"
                    f"{evaluated_at.date().isoformat()}"
                ),
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

        try:
            updated = await runtime_data.coordinator.async_command(command, guard=guard)
        except RuntimeInactiveError as err:
            raise _validation_error(str(err)) from err
        if dry_run_block_cancelled:
            raise _validation_error(
                "Dry-run block cancelled safely; retry start_next to begin a live run"
            )
        if result is None:
            raise RuntimeError("start_next command returned no result")
        start_result = result

        if start_result.block is not None and not runtime_data.dry_run:
            try:
                updated = await _async_dispatch_created_block(
                    hass,
                    runtime_data,
                    result,
                    service_call.context,
                    command_generation=command_generation,
                )
            except RuntimeInactiveError as err:
                raise _validation_error(str(err)) from err
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
        schema=vol.Schema({vol.Required(CONF_CONFIG_ENTRY_ID): _non_empty_string}),
        supports_response=getattr(core.SupportsResponse, "OPTIONAL", core.SupportsResponse.ONLY),
    )


def _apply_queue_mutation(
    hass: HomeAssistant,
    name: str,
    data: dict[str, object],
    state: PlannerState,
    now: datetime,
) -> tuple[PlannerState, dict[str, object]]:
    """Apply one public mutation to coordinator-owned state."""
    if name == SERVICE_SKIP_AREA_TODAY:
        time_zone = getattr(getattr(hass, "config", None), "time_zone", "UTC")
        updated = skip_area_today(
            state,
            cast("str", data["area_id"]),
            now,
            time_zone,
            str(uuid4()),
        )
        return updated, {"status": "skipped_today"}
    if name == SERVICE_POSTPONE_AREA:
        updated = postpone_area(
            state,
            cast("str", data["area_id"]),
            now,
            cast("int", data["days"]),
            str(uuid4()),
        )
        return updated, {"status": "postponed"}
    if name == SERVICE_CANCEL_BLOCK:
        updated = cancel_pending_block(state, cast("str", data["block_id"]), now)
        return updated, {"status": "cancelled", "revision": updated.ledger.revision}
    if name == SERVICE_RESOLVE_UNCERTAIN_RUN:
        ledger = resolve_uncertain_job(
            state.ledger,
            cast("str", data["job_id"]),
            UncertainResolution(cast("str", data["resolution"])),
            now,
        )
        return replace(state, ledger=ledger), {
            "status": "resolved",
            "revision": ledger.revision,
        }
    raise ValueError(f"unsupported Vacuum Planner action: {name}")


def _register_queue_mutation_actions(hass: HomeAssistant) -> None:
    """Register safe public mutations on the shared coordinator command path."""
    runtimes = hass.data[DOMAIN]
    core = cast("_CoreModule", import_module("homeassistant.core"))

    def register(name: str, fields: dict[object, object]) -> None:
        async def handler(call: object) -> dict[str, object]:
            data = cast("_ServiceCall", call).data
            entry_id = cast("str", data[CONF_CONFIG_ENTRY_ID])
            runtime = _runtime_for_action(runtimes, entry_id)
            command_generation = _capture_runtime_command(runtime)
            coordinator = runtime.coordinator
            if coordinator is None:
                raise _validation_error("Vacuum Planner state is unavailable")
            now = _utcnow()
            response: dict[str, object] = {}

            def command(state: PlannerState) -> PlannerState:
                nonlocal response
                try:
                    updated, response = _apply_queue_mutation(hass, name, data, state, now)
                except (KeyError, ValueError) as err:
                    raise _validation_error(f"{name} rejected: {err}") from err
                return updated

            try:
                await coordinator.async_command(
                    command,
                    guard=lambda: runtime.require_command_generation(command_generation),
                )
            except RuntimeInactiveError as err:
                raise _validation_error(str(err)) from err
            return response

        schema_fields: dict[object, object] = {
            vol.Required(CONF_CONFIG_ENTRY_ID): _non_empty_string,
        }
        schema_fields.update(fields)
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=vol.Schema(schema_fields),
            supports_response=getattr(
                core.SupportsResponse, "OPTIONAL", core.SupportsResponse.ONLY
            ),
        )

    area: dict[object, object] = {vol.Required("area_id"): _non_empty_string}
    register(SERVICE_SKIP_AREA_TODAY, area)
    register(
        SERVICE_POSTPONE_AREA,
        {**area, vol.Required("days"): _postpone_days},
    )
    register(SERVICE_CANCEL_BLOCK, {vol.Required("block_id"): _non_empty_string})
    register(
        SERVICE_RESOLVE_UNCERTAIN_RUN,
        {
            vol.Required("job_id"): _non_empty_string,
            vol.Required("resolution"): vol.In([UncertainResolution.RETRY_SAFE.value]),
        },
    )


async def async_setup(hass: HomeAssistant, _config: object) -> bool:
    """Register integration actions independently of config-entry availability."""
    hass.data.setdefault(DOMAIN, {})
    _register_get_queue_action(hass)
    _register_start_next_action(hass)
    _register_queue_mutation_actions(hass)
    return True


def _resolve_configured_vacuum(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
    active_issue_conditions: set[str],
) -> str:
    """Resolve the stable registry identity and validate its current topology."""
    vacuum_entity_id = cast("str", entry.data[CONF_VACUUM_ENTITY_ID])
    if entry.unique_id is None:
        return vacuum_entity_id
    er = cast(
        "_EntityRegistryModule",
        import_module("homeassistant.helpers.entity_registry"),
    )
    registry_entry = er.async_get(hass).async_get(entry.unique_id)
    if registry_entry is None:
        active_issue_conditions.add(MISSING_REGISTRY)
        return vacuum_entity_id

    vacuum_entity_id = registry_entry.entity_id
    if vacuum_entity_id != entry.data[CONF_VACUUM_ENTITY_ID]:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_VACUUM_ENTITY_ID: vacuum_entity_id},
        )
    active_issue_conditions.update(
        _configured_topology_issues(
            hass,
            entry.unique_id,
            tuple(entry.data.get(CONF_AREA_IDS, ())),
            requires_vacuum_and_mop=_entry_requires_vacuum_and_mop(entry),
        )
    )
    return vacuum_entity_id


def _configured_topology_issues(
    hass: HomeAssistant,
    registry_id: str,
    configured_area_ids: tuple[str, ...],
    *,
    requires_vacuum_and_mop: bool = False,
    cleaning_mode_registry_id: str | None = None,
) -> set[str]:
    """Return fail-closed topology issues using the shared setup validator."""
    issues: set[str] = set()
    valid_entry, validation_error = async_get_valid_vacuum(hass, registry_id)
    if validation_error == "clean_area_unsupported":
        issues.add(LOST_CAPABILITY)
    elif validation_error is not None or valid_entry is None:
        issues.add(MISSING_REGISTRY)
    else:
        mapping = area_mapping(valid_entry)
        if not mapping:
            issues.add(MISSING_MAPPING)
        elif validate_area_ids(configured_area_ids, valid_entry) is not None:
            issues.add(REMOVED_AREAS)
    try:
        area_registry_module = import_module("homeassistant.helpers.area_registry")
    except ModuleNotFoundError:
        pass
    else:
        area_registry = area_registry_module.async_get(hass)
        if any(area_registry.async_get_area(area_id) is None for area_id in configured_area_ids):
            issues.add(REMOVED_AREAS)
    cleaning_mode_entity_id = (
        resolve_bound_cleaning_mode_entity(hass, cleaning_mode_registry_id)
        if cleaning_mode_registry_id is not None
        else find_dreame_mova_cleaning_mode_entity(hass, registry_id)
    )
    if requires_vacuum_and_mop and cleaning_mode_entity_id is None:
        issues.add(LOST_CAPABILITY)
    return issues


def _configured_area_plans(
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> dict[str, dict[str, object]]:
    """Return validated config-flow plans, or legacy-safe defaults."""
    configured = entry.data.get(CONF_AREA_PLANS)
    result: dict[str, dict[str, object]] = {}
    for index, area_id in enumerate(entry.data.get(CONF_AREA_IDS, ())):
        raw = configured.get(area_id) if isinstance(configured, Mapping) else None
        settings = raw if isinstance(raw, Mapping) else {}
        result[area_id] = {
            CONF_AREA_ACTIVE: settings.get(CONF_AREA_ACTIVE, True),
            CONF_VACUUM_INTERVAL_DAYS: settings.get(CONF_VACUUM_INTERVAL_DAYS, 7),
            CONF_MOP_INTERVAL_DAYS: settings.get(CONF_MOP_INTERVAL_DAYS, 7),
            CONF_PRIORITY: settings.get(CONF_PRIORITY, index),
            CONF_MODE: settings.get(CONF_MODE, PreferredMode.VACUUM.value),
        }
    return result


def _entry_requires_vacuum_and_mop(
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> bool:
    """Return whether configured plans can schedule vacuum-and-mop work."""
    return any(
        settings[CONF_MODE] == PreferredMode.VACUUM_AND_MOP.value
        for settings in _configured_area_plans(entry).values()
    )


def _state_requires_vacuum_and_mop(state: PlannerState | None) -> bool:
    """Return whether the authoritative plan can schedule vacuum-and-mop work."""
    return state is not None and any(
        plan.enabled
        and plan.vacuum_and_mop_interval_days is not None
        and plan.preferred_mode is PreferredMode.VACUUM_AND_MOP
        for plan in state.plan_revision.room_plans
    )


def _initial_planner_state(
    entry: ConfigEntry[VacuumPlannerRuntimeData | None], entry_id: str
) -> PlannerState:
    """Create initial persisted state from validated config-entry topology."""
    lane_id = entry.unique_id or entry_id
    area_plans = _configured_area_plans(entry)
    return PlannerState(
        plan_revision=PlanRevision(
            revision_id=str(uuid4()),
            created_at=datetime.now(UTC),
            room_plans=tuple(
                RoomPlan(
                    area_id=area_id,
                    lane_id=lane_id,
                    enabled=cast("bool", settings[CONF_AREA_ACTIVE]),
                    vacuum_interval_days=cast("int", settings[CONF_VACUUM_INTERVAL_DAYS]),
                    vacuum_and_mop_interval_days=cast("int", settings[CONF_MOP_INTERVAL_DAYS]),
                    preferred_mode=PreferredMode(cast("str", settings[CONF_MODE])),
                    priority=cast("int", settings[CONF_PRIORITY]),
                )
                for area_id, settings in area_plans.items()
            ),
        ),
        ledger=QueueLedger.empty(),
    )


async def _async_load_planner_state(
    planner_store: PlannerStore,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
    entry_id: str,
) -> PlannerState:
    """Load, initialize, or durably recover one entry's planner state."""
    planner_state = await planner_store.async_load()
    if planner_state is None:
        planner_state = _initial_planner_state(entry, entry_id)
        await planner_store.async_save(planner_state)
        return planner_state

    recovered_ledger = quarantine_ambiguous_dispatches(planner_state.ledger, datetime.now(UTC))
    if (
        recovered_ledger.blocks != planner_state.ledger.blocks
        or recovered_ledger.jobs != planner_state.ledger.jobs
    ):
        planner_state = replace(planner_state, ledger=recovered_ledger)
        await planner_store.async_save(planner_state)
    return planner_state


async def _async_initialize_planner(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
    entry_id: str,
    active_issue_conditions: set[str],
) -> tuple[PlannerStore, PlannerCoordinator]:
    """Initialize storage and convert durable data failures into Repairs issues."""
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
        planner_state = await _async_load_planner_state(planner_store, entry, entry_id)
    except (ValueError, KeyError, TypeError) as err:
        active_issue_conditions.add(store_issue_condition(err))
        async_reconcile_entry_issues(hass, entry_id, active_issue_conditions)
        exceptions = cast(
            "_ExceptionsModule",
            import_module("homeassistant.exceptions"),
        )
        raise exceptions.ConfigEntryNotReady("Unable to load stored Vacuum Planner state") from err
    except OSError as err:
        exceptions = cast(
            "_ExceptionsModule",
            import_module("homeassistant.exceptions"),
        )
        raise exceptions.ConfigEntryNotReady(
            "Unable to load or initialize stored Vacuum Planner state"
        ) from err
    if any(block.state is BlockState.UNCERTAIN for block in planner_state.ledger.blocks) or any(
        job.state is JobState.UNCERTAIN for job in planner_state.ledger.jobs
    ):
        active_issue_conditions.add(UNRESOLVED_EXTERNAL_RUN)
    async_reconcile_entry_issues(hass, entry_id, active_issue_conditions)
    return planner_store, PlannerCoordinator(planner_state, planner_store)


def _optional_area_names(
    hass: HomeAssistant, configured_area_ids: tuple[str, ...]
) -> dict[str, str] | None:
    """Resolve cosmetic area names without participating in topology validation."""
    if not configured_area_ids:
        return None
    try:
        area_registry_module = cast(
            "_AreaRegistryModule", import_module("homeassistant.helpers.area_registry")
        )
    except ModuleNotFoundError:
        return None
    area_registry = area_registry_module.async_get(hass)
    names = {
        area_id: area.name
        for area_id in configured_area_ids
        if (area := area_registry.async_get_area(area_id)) is not None
    }
    return names or None


def _subscribe_observer(  # noqa: C901, PLR0915 - owns coordinated HA subscriptions
    hass: HomeAssistant,
    runtime_data: VacuumPlannerRuntimeData,
) -> None:
    """Subscribe one runtime to HA state changes for its resolved entity."""
    event = import_module("homeassistant.helpers.event")

    state_unsubscribe: Callable[[], None] | None = None
    capability_state_unsubscribe: Callable[[], None] | None = None
    registry_unsubscribe: Callable[[], None] | None = None
    area_unsubscribe: Callable[[], None] | None = None
    active = True

    def detach_state_observers() -> None:
        """Detach state listeners after any required durable quarantine attempt."""
        nonlocal capability_state_unsubscribe, state_unsubscribe
        unsubscribe_state = state_unsubscribe
        state_unsubscribe = None
        if unsubscribe_state is not None:
            with suppress(Exception):
                unsubscribe_state()
        unsubscribe_capability = capability_state_unsubscribe
        capability_state_unsubscribe = None
        if unsubscribe_capability is not None:
            with suppress(Exception):
                unsubscribe_capability()

    def has_active_external_work() -> bool:
        state = runtime_data.state
        return state is not None and (
            any(
                block.state in {BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING}
                for block in state.ledger.blocks
            )
            or any(
                job.state in {JobState.DISPATCHING, JobState.ACCEPTED, JobState.RUNNING}
                for job in state.ledger.jobs
            )
        )

    def fail_closed(*conditions: str, observed_at: datetime | None = None) -> None:
        """Latch immediately, then quarantine active work before detaching listeners."""
        if not runtime_data.topology_ready:
            return
        runtime_data.topology_ready = False
        invalidate_observations(runtime_data)
        if runtime_data.coordinator is not None:
            runtime_data.coordinator.publish_runtime_projection()
        if runtime_data.config_entry_id is not None:
            for condition in conditions:
                async_create_entry_issue(hass, runtime_data.config_entry_id, condition)
        if not has_active_external_work():
            detach_state_observers()
            return

        async def quarantine_then_detach() -> None:
            try:
                await async_apply_observation(
                    runtime_data,
                    "unavailable",
                    {},
                    observed_at or _utcnow(),
                )
            finally:
                detach_state_observers()

        hass.async_create_task(quarantine_then_detach())

    runtime_data.topology_failure_callback = fail_closed

    def observed(state_event: object, generation: int) -> None:
        if not runtime_data.topology_ready:
            return
        event_data = getattr(state_event, "data", {})
        new_state = event_data.get("new_state") if isinstance(event_data, Mapping) else None
        if new_state is None:
            fail_closed(MISSING_REGISTRY)
            return
        state = getattr(new_state, "state", None)
        attributes = getattr(new_state, "attributes", None)
        if not isinstance(state, str) or not isinstance(attributes, Mapping):
            fail_closed(MISSING_REGISTRY)
            return
        if state in {"unknown", "unavailable"}:
            event_time = getattr(state_event, "time_fired", None)
            observed_at = event_time if isinstance(event_time, datetime) else _utcnow()
            fail_closed(MISSING_REGISTRY, observed_at=observed_at)
            return
        supported_features = attributes.get("supported_features")
        if "supported_features" in attributes and (
            type(supported_features) is not int or not supported_features & 16384
        ):
            fail_closed(LOST_CAPABILITY)
            return
        event_time = getattr(state_event, "time_fired", None)
        observed_at = event_time if isinstance(event_time, datetime) else _utcnow()
        hass.async_create_task(
            async_apply_observation(
                runtime_data,
                state,
                attributes,
                observed_at,
                observation_generation=generation,
            )
        )

    def unsubscribe() -> None:
        nonlocal active, area_unsubscribe, capability_state_unsubscribe
        nonlocal registry_unsubscribe, state_unsubscribe
        if not active:
            return
        active = False
        if runtime_data.topology_failure_callback is fail_closed:
            runtime_data.topology_failure_callback = None
        invalidate_observations(runtime_data)
        cleanup_errors: list[Exception] = []
        for unsubscribe_callback in (
            state_unsubscribe,
            capability_state_unsubscribe,
            registry_unsubscribe,
            area_unsubscribe,
        ):
            if unsubscribe_callback is None:
                continue
            try:
                unsubscribe_callback()
            except Exception as err:  # noqa: BLE001 - all nested listeners must be detached
                cleanup_errors.append(err)
        state_unsubscribe = None
        capability_state_unsubscribe = None
        registry_unsubscribe = None
        area_unsubscribe = None
        if len(cleanup_errors) == 1:
            raise cleanup_errors[0]
        if cleanup_errors:
            raise ExceptionGroup("Vacuum Planner observer cleanup failed", cleanup_errors)

    runtime_data.observer_unsubscribe = unsubscribe

    def bind_state(entity_id: str) -> None:
        nonlocal state_unsubscribe
        if not active:
            return
        previous_unsubscribe = state_unsubscribe
        generation = runtime_data.observation_generation + int(runtime_data.observation_active)
        new_unsubscribe = event.async_track_state_change_event(
            hass,
            [entity_id],
            lambda state_event: observed(state_event, generation),
        )
        invalidate_observations(runtime_data)
        if previous_unsubscribe is not None:
            previous_unsubscribe()
        state_unsubscribe = new_unsubscribe
        runtime_data.observation_active = True

    def capability_observed(state_event: object) -> None:
        if not runtime_data.topology_ready:
            return
        event_data = getattr(state_event, "data", {})
        new_state = event_data.get("new_state") if isinstance(event_data, Mapping) else None
        attributes = getattr(new_state, "attributes", {})
        options = attributes.get("options") if isinstance(attributes, Mapping) else None
        if (
            new_state is None
            or getattr(new_state, "state", None) in {"unknown", "unavailable"}
            or not isinstance(options, list)
            or not {"Vacuum", "Vacuum and Mop"}.issubset(options)
        ):
            fail_closed(LOST_CAPABILITY)

    def bind_capability_state(entity_id: str) -> None:
        nonlocal capability_state_unsubscribe
        previous_unsubscribe = capability_state_unsubscribe
        capability_state_unsubscribe = event.async_track_state_change_event(
            hass,
            [entity_id],
            capability_observed,
        )
        runtime_data.cleaning_mode_entity_id = entity_id
        if previous_unsubscribe is not None:
            previous_unsubscribe()

    try:
        bind_state(runtime_data.vacuum_entity_id)
        if runtime_data.requires_vacuum_and_mop:
            cleaning_mode_entity_id = resolve_bound_cleaning_mode_entity(
                hass,
                runtime_data.cleaning_mode_registry_id,
            )
            if cleaning_mode_entity_id is None:
                fail_closed(LOST_CAPABILITY)
            else:
                bind_capability_state(cleaning_mode_entity_id)
        registry_id = runtime_data.vacuum_registry_id
        if registry_id is not None and hasattr(hass, "bus"):
            registry_module = import_module("homeassistant.helpers.entity_registry")

            def registry_updated(_registry_event: object) -> None:
                if not runtime_data.topology_ready:
                    return
                registry_entry = registry_module.async_get(hass).async_get(registry_id)
                current_entity_id = getattr(registry_entry, "entity_id", None)
                configured_area_ids = runtime_data.configured_area_ids
                if not configured_area_ids and runtime_data.state is not None:
                    configured_area_ids = tuple(
                        plan.area_id for plan in runtime_data.state.plan_revision.room_plans
                    )
                if not isinstance(current_entity_id, str):
                    topology_issues = {MISSING_REGISTRY}
                else:
                    topology_issues = _configured_topology_issues(
                        hass,
                        registry_id,
                        configured_area_ids,
                        requires_vacuum_and_mop=runtime_data.requires_vacuum_and_mop,
                        cleaning_mode_registry_id=runtime_data.cleaning_mode_registry_id,
                    )
                if current_entity_id != runtime_data.vacuum_entity_id:
                    topology_issues.add(MISSING_REGISTRY)
                if topology_issues:
                    fail_closed(*topology_issues)
                    return
                if runtime_data.requires_vacuum_and_mop:
                    cleaning_mode_entity_id = resolve_bound_cleaning_mode_entity(
                        hass,
                        runtime_data.cleaning_mode_registry_id,
                    )
                    if cleaning_mode_entity_id is None:
                        fail_closed(LOST_CAPABILITY)
                        return
                    if cleaning_mode_entity_id != runtime_data.cleaning_mode_entity_id:
                        bind_capability_state(cleaning_mode_entity_id)

            registry_unsubscribe = hass.bus.async_listen(
                getattr(
                    registry_module,
                    "EVENT_ENTITY_REGISTRY_UPDATED",
                    "entity_registry_updated",
                ),
                registry_updated,
            )
            try:
                area_registry_module = import_module("homeassistant.helpers.area_registry")
            except ModuleNotFoundError:
                pass
            else:

                def area_updated(_area_event: object) -> None:
                    if not runtime_data.topology_ready:
                        return
                    topology_issues = _configured_topology_issues(
                        hass,
                        registry_id,
                        runtime_data.configured_area_ids,
                        requires_vacuum_and_mop=runtime_data.requires_vacuum_and_mop,
                        cleaning_mode_registry_id=runtime_data.cleaning_mode_registry_id,
                    )
                    if topology_issues:
                        fail_closed(*topology_issues)

                area_unsubscribe = hass.bus.async_listen(
                    getattr(
                        area_registry_module,
                        "EVENT_AREA_REGISTRY_UPDATED",
                        "area_registry_updated",
                    ),
                    area_updated,
                )
    except Exception:
        unsubscribe()
        runtime_data.observer_unsubscribe = None
        raise


def _subscribe_repairs(hass: HomeAssistant, runtime_data: VacuumPlannerRuntimeData) -> None:
    """Reconcile uncertain-run Repairs after every persisted coordinator publication."""
    coordinator = runtime_data.coordinator
    entry_id = runtime_data.config_entry_id
    if coordinator is None or entry_id is None:
        return

    def reconcile() -> None:
        state = coordinator.state
        active = any(block.state is BlockState.UNCERTAIN for block in state.ledger.blocks) or any(
            job.state is JobState.UNCERTAIN for job in state.ledger.jobs
        )
        async_reconcile_unresolved_external_run(hass, entry_id, active=active)

    runtime_data.repair_unsubscribe = coordinator.async_add_listener(reconcile)


def _rollback_setup_runtime(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
    runtime_data: VacuumPlannerRuntimeData,
) -> None:
    """Idempotently remove every partially published setup resource."""
    try:
        shutdown_runtime(runtime_data)
    finally:
        entry_id = getattr(entry, "entry_id", None)
        if entry_id and hasattr(hass, "data"):
            runtimes = hass.data.get(DOMAIN, {})
            if runtimes.get(entry_id) is runtime_data:
                runtimes.pop(entry_id, None)
        if getattr(entry, "runtime_data", None) is runtime_data:
            entry.runtime_data = None


def _resolve_required_cleaning_mode(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
    planner_state: PlannerState | None,
    active_issue_conditions: set[str],
) -> tuple[str | None, str | None, bool]:
    """Resolve the live selector required by configured vacuum-and-mop work."""
    requires_vacuum_and_mop = _state_requires_vacuum_and_mop(
        planner_state
    ) or _entry_requires_vacuum_and_mop(entry)
    cleaning_mode_entity_id = (
        find_dreame_mova_cleaning_mode_entity(hass, entry.unique_id)
        if requires_vacuum_and_mop and entry.unique_id is not None
        else None
    )
    cleaning_mode_registry_id: str | None = None
    if cleaning_mode_entity_id is not None:
        registry_module = import_module("homeassistant.helpers.entity_registry")
        cleaning_mode_entry = registry_module.async_get(hass).async_get(cleaning_mode_entity_id)
        candidate_registry_id = getattr(cleaning_mode_entry, "id", None)
        if isinstance(candidate_registry_id, str):
            cleaning_mode_registry_id = candidate_registry_id
    if requires_vacuum_and_mop and cleaning_mode_entity_id is None:
        active_issue_conditions.add(LOST_CAPABILITY)
        if entry.entry_id:
            async_create_entry_issue(hass, entry.entry_id, LOST_CAPABILITY)
    return cleaning_mode_entity_id, cleaning_mode_registry_id, requires_vacuum_and_mop


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> bool:
    """Set up Vacuum Planner from a config entry without device side effects."""
    entry_id = getattr(entry, "entry_id", None)
    active_issue_conditions: set[str] = set()
    vacuum_entity_id = _resolve_configured_vacuum(
        hass,
        entry,
        active_issue_conditions,
    )
    planner_store = None
    coordinator = None
    if entry_id:
        planner_store, coordinator = await _async_initialize_planner(
            hass,
            entry,
            entry_id,
            active_issue_conditions,
        )
    configured_area_ids = tuple(entry.data.get(CONF_AREA_IDS, ()))
    area_names = _optional_area_names(hass, configured_area_ids)
    cleaning_mode_entity_id, cleaning_mode_registry_id, requires_vacuum_and_mop = (
        _resolve_required_cleaning_mode(
            hass,
            entry,
            coordinator.state if coordinator is not None else None,
            active_issue_conditions,
        )
    )
    runtime_data = VacuumPlannerRuntimeData(
        vacuum_entity_id=vacuum_entity_id,
        planning_enabled=entry.options.get(CONF_PLANNING_ENABLED, True),
        dry_run=entry.options.get(CONF_DRY_RUN, True),
        store=planner_store,
        coordinator=coordinator,
        area_names=area_names,
        configured_area_ids=configured_area_ids,
        capability_tier="T1",
        topology_ready=not active_issue_conditions.intersection(
            {MISSING_REGISTRY, MISSING_MAPPING, LOST_CAPABILITY, REMOVED_AREAS}
        ),
        vacuum_registry_id=entry.unique_id,
        cleaning_mode_entity_id=cleaning_mode_entity_id,
        cleaning_mode_registry_id=cleaning_mode_registry_id,
        requires_vacuum_and_mop=requires_vacuum_and_mop,
        config_entry_id=entry_id,
    )
    entry.runtime_data = runtime_data

    def cleanup() -> None:
        _rollback_setup_runtime(hass, entry, runtime_data)

    if hasattr(entry, "async_on_unload"):
        entry.async_on_unload(cleanup)
    try:
        _subscribe_repairs(hass, runtime_data)
        if entry_id and hasattr(hass, "data") and hasattr(hass, "services"):
            hass.data.setdefault(DOMAIN, {})[entry_id] = runtime_data
        if coordinator is not None and hasattr(hass, "async_create_task"):
            with suppress(ModuleNotFoundError):
                _subscribe_observer(hass, runtime_data)
        if hasattr(getattr(hass, "config_entries", None), "async_forward_entry_setups"):
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as setup_error:
        try:
            cleanup()
        except Exception as cleanup_error:  # noqa: BLE001 - aggregate after complete rollback
            raise ExceptionGroup(
                "Vacuum Planner setup and rollback failed",
                [setup_error, cleanup_error],
            ) from None
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> bool:
    """Unload a Vacuum Planner config entry."""
    runtime_data = entry.runtime_data
    if runtime_data is not None:
        invalidate_commands(runtime_data)
    if hasattr(getattr(hass, "config_entries", None), "async_unload_platforms"):
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            if runtime_data is not None:
                activate_commands(runtime_data)
            return False
    if runtime_data is not None:
        _rollback_setup_runtime(hass, entry, runtime_data)
    return True


async def async_remove_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[VacuumPlannerRuntimeData | None],
) -> None:
    """Remove persistent state and Repairs after final config-entry deletion."""
    storage = cast(
        "_StorageModule",
        import_module("homeassistant.helpers.storage"),
    )
    entry_id = entry.entry_id
    store = PlannerStore(
        storage.Store(
            hass,
            1,
            f"{DOMAIN}.{entry_id}",
            atomic_writes=True,
        )
    )
    await store.async_remove()
    async_clear_entry_issues(hass, entry_id)
