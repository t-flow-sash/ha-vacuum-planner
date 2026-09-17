"""Versioned Home Assistant Store boundary for authoritative planner state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .domain.serialization import deserialize_planner_state, serialize_planner_state

if TYPE_CHECKING:
    from .domain.models import PlannerState


class StoreBackend(Protocol):
    """Subset of the Home Assistant Store contract used by the planner."""

    async def async_load(self) -> dict[str, Any] | None:
        """Load the stored planner payload."""

    async def async_save(self, data: dict[str, Any]) -> None:
        """Atomically save the planner payload."""


class PlannerStore:
    """Persist and validate one planner state as a single atomic value."""

    def __init__(self, backend: StoreBackend) -> None:
        self._backend = backend

    async def async_load(self) -> PlannerState | None:
        """Load and validate planner state without replacing invalid data."""
        payload = await self._backend.async_load()
        if payload is None:
            return None
        return deserialize_planner_state(payload)

    async def async_save(self, state: PlannerState) -> None:
        """Save plan and queue together through the storage backend."""
        await self._backend.async_save(serialize_planner_state(state))
