"""Constants and runtime types for Vacuum Planner."""

from dataclasses import dataclass

DOMAIN = "vacuum_planner"
CONF_VACUUM_ENTITY_ID = "vacuum_entity_id"
DEFAULT_TITLE = "Vacuum Planner"


@dataclass(frozen=True, slots=True)
class VacuumPlannerRuntimeData:
    """Runtime state owned by one Vacuum Planner config entry."""

    vacuum_entity_id: str
