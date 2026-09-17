"""Constants and runtime types for Vacuum Planner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .domain.models import PlannerState
    from .store import PlannerStore

DOMAIN = "vacuum_planner"
CONF_VACUUM_ENTITY_ID = "vacuum_entity_id"
DEFAULT_TITLE = "Vacuum Planner"


@dataclass(frozen=True, slots=True)
class VacuumPlannerRuntimeData:
    """Runtime state owned by one Vacuum Planner config entry."""

    vacuum_entity_id: str
    store: PlannerStore | None = None
    state: PlannerState | None = None
