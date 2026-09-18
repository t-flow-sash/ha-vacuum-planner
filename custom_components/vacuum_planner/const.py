"""Constants and runtime types for Vacuum Planner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import PlannerCoordinator
    from .domain.models import PlannerState
    from .store import PlannerStore

DOMAIN = "vacuum_planner"
CONF_VACUUM_ENTITY_ID = "vacuum_entity_id"
CONF_AREA_IDS = "area_ids"
CONF_DRY_RUN = "dry_run"
CONF_PLANNING_ENABLED = "planning_enabled"
CONF_CONFIG_ENTRY_ID = "config_entry_id"
SERVICE_GET_QUEUE = "get_queue"
DEFAULT_TITLE = "Vacuum Planner"


@dataclass(frozen=True, slots=True)
class VacuumPlannerRuntimeData:
    """Runtime state owned by one Vacuum Planner config entry."""

    vacuum_entity_id: str
    planning_enabled: bool = True
    dry_run: bool = True
    store: PlannerStore | None = None
    coordinator: PlannerCoordinator | None = None

    @property
    def state(self) -> PlannerState | None:
        """Return the current coordinator-owned planner state."""
        if self.coordinator is None:
            return None
        return self.coordinator.state
