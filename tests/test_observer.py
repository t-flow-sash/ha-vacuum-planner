from datetime import UTC, datetime

import pytest

from custom_components.vacuum_planner.adapters.observation import (
    ObservationOutcome,
    normalize_observation,
)


@pytest.mark.parametrize(
    ("state", "attributes", "outcome"),
    [
        ("cleaning", {}, ObservationOutcome.RUNNING),
        ("idle", {}, ObservationOutcome.COMPLETED),
        ("docked", {}, ObservationOutcome.COMPLETED),
        ("paused", {}, ObservationOutcome.NO_CHANGE),
        ("returning", {}, ObservationOutcome.NO_CHANGE),
        ("error", {}, ObservationOutcome.FAILED),
        ("unknown", {}, ObservationOutcome.UNCERTAIN),
        ("unavailable", {}, ObservationOutcome.UNCERTAIN),
        ("mystery_vendor_state", {}, ObservationOutcome.UNCERTAIN),
        ("idle", {"status": "zone_cleaning"}, ObservationOutcome.RUNNING),
        ("idle", {"task_status": "cleaning"}, ObservationOutcome.RUNNING),
        ("idle", {"error_code": 7}, ObservationOutcome.FAILED),
    ],
)
def test_adapter_normalizes_generic_and_vendor_observations(
    state: str,
    attributes: dict[str, object],
    outcome: ObservationOutcome,
) -> None:
    assert normalize_observation(state, attributes).outcome is outcome


@pytest.mark.parametrize(
    "vendor_state",
    ["washing", "mop_washing", "drying", "returning", "returning_home", "docking"],
)
def test_washing_and_dock_transitions_are_never_completion(vendor_state: str) -> None:
    observation = normalize_observation("idle", {"status": vendor_state})

    assert observation.outcome is ObservationOutcome.NO_CHANGE


def test_empty_or_malformed_attributes_do_not_invent_vendor_completion() -> None:
    at = datetime(2026, 9, 19, tzinfo=UTC)

    observation = normalize_observation("idle", {"status": None, "error_code": False})

    assert observation.outcome is ObservationOutcome.COMPLETED
    assert observation.observed_at is None
    assert at.tzinfo is UTC
