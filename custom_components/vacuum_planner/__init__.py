"""Vacuum Planner custom integration package."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast
from uuid import uuid4

import voluptuous as vol

from .const import (
    CONF_AREA_IDS,
    CONF_CONFIG_ENTRY_ID,
    CONF_DRY_RUN,
    CONF_PLANNING_ENABLED,
    CONF_VACUUM_ENTITY_ID,
    DOMAIN,
    SERVICE_GET_QUEUE,
    VacuumPlannerRuntimeData,
)
from .coordinator import PlannerCoordinator
from .domain.models import PlannerState, PlanRevision, PreferredMode, QueueLedger, RoomPlan
from .domain.queue import quarantine_ambiguous_dispatches
from .store import PlannerStore, StoreBackend

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class _RegistryEntry(Protocol):
    entity_id: str


class _EntityRegistry(Protocol):
    def async_get(self, entity_id_or_uuid: str) -> _RegistryEntry | None: ...


class _EntityRegistryModule(Protocol):
    def async_get(self, hass: HomeAssistant) -> _EntityRegistry: ...


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


async def async_setup(hass: HomeAssistant, _config: object) -> bool:
    """Register integration actions independently of config-entry availability."""
    hass.data.setdefault(DOMAIN, {})
    _register_get_queue_action(hass)
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
