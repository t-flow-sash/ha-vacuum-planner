"""Strictly allowlisted diagnostics for Vacuum Planner config entries."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

from .const import CONF_AREA_IDS


class _StateValue(Protocol):
    value: str


class _StateItem(Protocol):
    state: _StateValue


class _DiagnosticEntry(Protocol):
    version: int
    minor_version: int
    unique_id: str | None
    data: Mapping[str, object]
    runtime_data: object


def _state_counts(items: Iterable[_StateItem]) -> dict[str, int]:
    """Count public enum state values without exposing item identities."""
    return dict(sorted(Counter(item.state.value for item in items).items()))


async def async_get_config_entry_diagnostics(
    _hass: object, entry: _DiagnosticEntry
) -> dict[str, object]:
    """Return aggregate operational facts from a fixed privacy allowlist."""
    runtime = getattr(entry, "runtime_data", None)
    state = getattr(runtime, "state", None)
    area_ids = entry.data.get(CONF_AREA_IDS, ())
    runtime_result: dict[str, object] = {
        "loaded": runtime is not None,
        "planning_enabled": getattr(runtime, "planning_enabled", None),
        "dry_run": getattr(runtime, "dry_run", None),
        "store_initialized": getattr(runtime, "store", None) is not None,
    }
    result: dict[str, object] = {
        "entry": {
            "version": getattr(entry, "version", None),
            "minor_version": getattr(entry, "minor_version", None),
            "registry_identity_configured": bool(getattr(entry, "unique_id", None)),
            "configured_area_count": len(area_ids) if isinstance(area_ids, (list, tuple)) else 0,
        },
        "runtime": runtime_result,
    }
    if state is not None:
        ledger = state.ledger
        runtime_result.update(
            {
                "plan_room_count": len(state.plan_revision.room_plans),
                "queue_revision": ledger.revision,
                "block_count": len(ledger.blocks),
                "job_count": len(ledger.jobs),
                "block_states": _state_counts(ledger.blocks),
                "job_states": _state_counts(ledger.jobs),
            }
        )
    return result
