"""Normalize Home Assistant and vendor vacuum observations at the adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


class ObservationOutcome(StrEnum):
    """Vendor-neutral outcomes consumed by the planner observer."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    NO_CHANGE = "no_change"


@dataclass(frozen=True, slots=True)
class VacuumObservation:
    """One normalized state observation without raw vendor payloads."""

    outcome: ObservationOutcome
    observed_at: datetime | None = None


_RUNNING_STATES = frozenset({"cleaning", "zone_cleaning", "segment_cleaning"})
_INTERMEDIATE_STATES = frozenset(
    {
        "paused",
        "washing",
        "mop_washing",
        "drying",
        "returning",
        "returning_home",
        "docking",
    }
)
_FAILED_STATES = frozenset({"error", "failed"})
_UNCERTAIN_STATES = frozenset({"unknown", "unavailable"})
_COMPLETED_STATES = frozenset({"idle", "docked"})


def _normalized_text(value: object) -> str | None:
    if type(value) is not str or not value.strip():
        return None
    return value.strip().lower()


def normalize_observation(
    state: str,
    attributes: Mapping[str, object],
) -> VacuumObservation:
    """Normalize generic HA state plus Dreame/Mova-style detail attributes."""
    normalized_state = _normalized_text(state) or "unknown"
    details = tuple(
        value
        for key in ("activity", "status", "task_status")
        if (value := _normalized_text(attributes.get(key))) is not None
    )
    error_code = attributes.get("error_code")
    error_text = _normalized_text(attributes.get("error"))

    if (
        normalized_state in _FAILED_STATES
        or error_text in _FAILED_STATES
        or (type(error_code) is int and error_code != 0)
    ):
        return VacuumObservation(ObservationOutcome.FAILED)
    if normalized_state in _UNCERTAIN_STATES or any(
        detail in _UNCERTAIN_STATES for detail in details
    ):
        return VacuumObservation(ObservationOutcome.UNCERTAIN)
    if normalized_state in _RUNNING_STATES or any(detail in _RUNNING_STATES for detail in details):
        return VacuumObservation(ObservationOutcome.RUNNING)
    if normalized_state in _INTERMEDIATE_STATES or any(
        detail in _INTERMEDIATE_STATES for detail in details
    ):
        return VacuumObservation(ObservationOutcome.NO_CHANGE)
    if normalized_state in _COMPLETED_STATES and not details:
        return VacuumObservation(ObservationOutcome.COMPLETED)
    return VacuumObservation(ObservationOutcome.UNCERTAIN)
