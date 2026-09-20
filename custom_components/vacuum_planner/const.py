"""Constants and runtime types for Vacuum Planner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .coordinator import PlannerCoordinator
    from .domain.models import PlannerState
    from .store import PlannerStore

DOMAIN = "vacuum_planner"
CONF_VACUUM_ENTITY_ID = "vacuum_entity_id"
CONF_AREA_IDS = "area_ids"
CONF_AREA_PLANS = "area_plans"
CONF_AREA_ACTIVE = "active"
CONF_VACUUM_INTERVAL_DAYS = "vacuum_interval_days"
CONF_MOP_INTERVAL_DAYS = "mop_interval_days"
CONF_PRIORITY = "priority"
CONF_MODE = "mode"
CONF_DRY_RUN = "dry_run"
CONF_PLANNING_ENABLED = "planning_enabled"
CONF_CONFIG_ENTRY_ID = "config_entry_id"
SERVICE_GET_QUEUE = "get_queue"
SERVICE_START_NEXT = "start_next"
SERVICE_SKIP_AREA_TODAY = "skip_area_today"
SERVICE_POSTPONE_AREA = "postpone_area"
SERVICE_CANCEL_BLOCK = "cancel_block"
SERVICE_RESOLVE_UNCERTAIN_RUN = "resolve_uncertain_run"
PLATFORMS = ("sensor", "switch", "binary_sensor", "button")
DEFAULT_TITLE = "Vacuum Planner"


class RuntimeInactiveError(RuntimeError):
    """Raised when work belongs to a detached runtime generation."""


class TopologyNotReadyError(RuntimeInactiveError):
    """Raised when a loaded runtime has latched an invalid topology."""


@dataclass(slots=True)
class VacuumPlannerRuntimeData:
    """Runtime state owned by one Vacuum Planner config entry."""

    vacuum_entity_id: str
    planning_enabled: bool = True
    dry_run: bool = True
    store: PlannerStore | None = None
    coordinator: PlannerCoordinator | None = None
    area_names: Mapping[str, str] | None = None
    configured_area_ids: tuple[str, ...] = ()
    capability_tier: str = "T1"
    topology_ready: bool = True
    vacuum_registry_id: str | None = None
    cleaning_mode_entity_id: str | None = None
    cleaning_mode_registry_id: str | None = None
    requires_vacuum_and_mop: bool = False
    config_entry_id: str | None = None
    observer_unsubscribe: Callable[[], None] | None = None
    repair_unsubscribe: Callable[[], None] | None = None
    topology_failure_callback: Callable[[str], None] | None = None
    observation_generation: int = 0
    observation_active: bool = False
    command_generation: int = 0
    command_active: bool = True

    @property
    def state(self) -> PlannerState | None:
        """Return the current coordinator-owned planner state."""
        if self.coordinator is None:
            return None
        return self.coordinator.state

    async def async_set_planning_enabled(
        self,
        *,
        enabled: bool,
        commit: Callable[[], None] | None = None,
        rollback: Callable[[], None] | None = None,
    ) -> None:
        """Update the runtime planning preference through the shared coordinator lock."""
        if self.coordinator is None:
            raise RuntimeError("Vacuum Planner state is unavailable")

        command_generation = self.capture_command_generation()

        def update() -> None:
            previous = self.planning_enabled
            try:
                if commit is not None:
                    commit()
            except Exception:
                try:
                    if rollback is not None:
                        rollback()
                except Exception as rollback_error:
                    self.planning_enabled = False
                    raise RuntimeError(
                        "Planning option update and rollback failed; planner is fail-closed"
                    ) from rollback_error
                self.planning_enabled = previous
                raise
            self.planning_enabled = enabled

        await self.coordinator.async_update_projection(
            update,
            guard=lambda: self.require_command_generation(command_generation),
        )

    def capture_command_generation(self) -> int:
        """Capture the active runtime generation at command resolution."""
        if not self.command_active:
            raise RuntimeInactiveError("Vacuum Planner runtime is no longer active")
        if not self.topology_ready:
            raise TopologyNotReadyError(
                "Vacuum Planner topology is not ready; repair the reported issue and reload "
                "the config entry"
            )
        return self.command_generation

    def require_runtime_generation(self, generation: int) -> None:
        """Reject work from a detached runtime while allowing safe quarantine."""
        if not self.command_active or self.command_generation != generation:
            raise RuntimeInactiveError("Vacuum Planner runtime is no longer active")

    def require_command_generation(self, generation: int) -> None:
        """Reject work captured from a detached, superseded, or latched runtime."""
        self.require_runtime_generation(generation)
        if not self.topology_ready:
            raise TopologyNotReadyError(
                "Vacuum Planner topology is not ready; repair the reported issue and reload "
                "the config entry"
            )


def invalidate_observations(runtime_data: VacuumPlannerRuntimeData) -> None:
    """Invalidate already queued observations for the current state binding."""
    if getattr(runtime_data, "observation_active", False):
        runtime_data.observation_generation = getattr(runtime_data, "observation_generation", 0) + 1
    runtime_data.observation_active = False


def invalidate_commands(runtime_data: VacuumPlannerRuntimeData) -> None:
    """Invalidate every command already resolved against this runtime."""
    if runtime_data.command_active:
        runtime_data.command_generation += 1
    runtime_data.command_active = False


def activate_commands(runtime_data: VacuumPlannerRuntimeData) -> None:
    """Activate a fresh generation without reviving previously captured commands."""
    runtime_data.command_generation += 1
    runtime_data.command_active = True


def shutdown_runtime(runtime_data: VacuumPlannerRuntimeData) -> None:
    """Invalidate observations and detach every runtime-owned listener."""
    invalidate_commands(runtime_data)
    invalidate_observations(runtime_data)
    runtime_data.topology_failure_callback = None
    cleanup_errors: list[Exception] = []
    for attribute in ("observer_unsubscribe", "repair_unsubscribe"):
        unsubscribe = getattr(runtime_data, attribute, None)
        setattr(runtime_data, attribute, None)
        if unsubscribe is None:
            continue
        try:
            unsubscribe()
        except Exception as err:  # noqa: BLE001 - finish all cleanup before propagating
            cleanup_errors.append(err)
    if len(cleanup_errors) == 1:
        raise cleanup_errors[0]
    if cleanup_errors:
        raise ExceptionGroup("Vacuum Planner runtime cleanup failed", cleanup_errors)
