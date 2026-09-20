"""Persistent Home Assistant Repairs issues for Vacuum Planner."""

from __future__ import annotations

from importlib import import_module
from typing import Protocol, cast

from .const import DOMAIN
from .domain.serialization import SCHEMA_VERSION, SchemaVersionError

MISSING_REGISTRY = "missing_registry"
MISSING_MAPPING = "missing_mapping"
LOST_CAPABILITY = "lost_capability"
REMOVED_AREAS = "removed_areas"
UNRESOLVED_EXTERNAL_RUN = "unresolved_external_run"
CORRUPT_STORE = "corrupt_store"
FUTURE_STORE = "future_store"
ISSUE_CONDITIONS = (
    MISSING_REGISTRY,
    MISSING_MAPPING,
    LOST_CAPABILITY,
    REMOVED_AREAS,
    UNRESOLVED_EXTERNAL_RUN,
    CORRUPT_STORE,
    FUTURE_STORE,
)


class _IssueSeverity(Protocol):
    ERROR: object


class _IssueRegistryModule(Protocol):
    IssueSeverity: _IssueSeverity

    def async_create_issue(
        self,
        hass: object,
        domain: str,
        issue_id: str,
        **kwargs: object,
    ) -> None: ...

    def async_delete_issue(self, hass: object, domain: str, issue_id: str) -> None: ...


class _RepairFlow(Protocol):
    async def async_step_init(self, user_input: object = None) -> object: ...


def issue_id(entry_id: str, condition: str) -> str:
    """Return the stable per-entry, per-condition Repairs identity."""
    return f"{entry_id}_{condition}"


def _issue_registry() -> _IssueRegistryModule | None:
    """Load HA's issue registry, allowing minimal hermetic lifecycle stubs."""
    try:
        return cast(
            "_IssueRegistryModule",
            import_module("homeassistant.helpers.issue_registry"),
        )
    except ModuleNotFoundError:
        return None


def async_create_entry_issue(hass: object, entry_id: str, condition: str) -> None:
    """Create or update one deterministic, naturally deduplicated Repairs issue."""
    if condition not in ISSUE_CONDITIONS:
        raise ValueError("unsupported repair condition")
    issue_registry = _issue_registry()
    if issue_registry is None:
        return
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        issue_id(entry_id, condition),
        is_fixable=condition in {MISSING_REGISTRY, MISSING_MAPPING, LOST_CAPABILITY, REMOVED_AREAS},
        severity=issue_registry.IssueSeverity.ERROR,
        translation_key=condition,
        data={"entry_id": entry_id},
    )


def async_reconcile_entry_issues(hass: object, entry_id: str, active_conditions: set[str]) -> None:
    """Create active conditions and clear all stale conditions for one entry."""
    issue_registry = _issue_registry()
    if issue_registry is None:
        return
    for condition in ISSUE_CONDITIONS:
        if condition in active_conditions:
            async_create_entry_issue(hass, entry_id, condition)
        else:
            issue_registry.async_delete_issue(hass, DOMAIN, issue_id(entry_id, condition))


def async_reconcile_unresolved_external_run(hass: object, entry_id: str, *, active: bool) -> None:
    """Reconcile only the uncertain-run issue after one durable state transition."""
    issue_registry = _issue_registry()
    if issue_registry is None:
        return
    if active:
        async_create_entry_issue(hass, entry_id, UNRESOLVED_EXTERNAL_RUN)
    else:
        issue_registry.async_delete_issue(
            hass,
            DOMAIN,
            issue_id(entry_id, UNRESOLVED_EXTERNAL_RUN),
        )


def async_clear_entry_issue(hass: object, entry_id: str, condition: str) -> None:
    """Clear one resolved issue without changing unrelated Repairs state."""
    issue_registry = _issue_registry()
    if issue_registry is None:
        return
    issue_registry.async_delete_issue(hass, DOMAIN, issue_id(entry_id, condition))


def async_clear_entry_issues(hass: object, entry_id: str) -> None:
    """Attempt every known per-entry issue deletion before reporting failures."""
    issue_registry = _issue_registry()
    if issue_registry is None:
        return
    cleanup_errors: list[Exception] = []
    for condition in ISSUE_CONDITIONS:
        try:
            issue_registry.async_delete_issue(hass, DOMAIN, issue_id(entry_id, condition))
        except Exception as err:  # noqa: BLE001 - do not strand later per-entry issues
            cleanup_errors.append(err)
    if len(cleanup_errors) == 1:
        raise cleanup_errors[0]
    if cleanup_errors:
        raise ExceptionGroup("Vacuum Planner Repairs cleanup failed", cleanup_errors)


def store_issue_condition(error: Exception) -> str:
    """Classify durable store failures without exposing payload contents."""
    if isinstance(error, SchemaVersionError) and (
        isinstance(error.version, int) and error.version > SCHEMA_VERSION
    ):
        return FUTURE_STORE
    return CORRUPT_STORE


async def async_create_fix_flow(
    _hass: object, issue_id_value: str, data: dict[str, str | int | float | None]
) -> _RepairFlow:
    """Return a minimal flow directing topology repairs to reload or recreation."""
    repairs = import_module("homeassistant.components.repairs")
    base = repairs.RepairsFlow
    topology_issue = issue_id_value.endswith(
        (MISSING_REGISTRY, MISSING_MAPPING, LOST_CAPABILITY, REMOVED_AREAS)
    )

    class VacuumPlannerRepairFlow(base):  # type: ignore[misc, valid-type]
        async def async_step_init(self, _user_input: object = None) -> object:
            reason = (
                "reload_or_recreate_required" if topology_issue else "manual_store_repair_required"
            )
            return self.async_abort(reason=reason)

    del data
    return cast("_RepairFlow", VacuumPlannerRepairFlow())
