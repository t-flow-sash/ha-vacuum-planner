"""Serialized command path for authoritative Vacuum Planner state."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from .domain.models import PlannerState

_LOGGER = logging.getLogger(__name__)


class PlannerStateStore(Protocol):
    """Persistence boundary required by the command coordinator."""

    async def async_save(self, state: PlannerState) -> None:
        """Persist one complete planner state."""


class PlannerCoordinator:
    """Serialize state mutations and publish them only after persistence."""

    def __init__(self, state: PlannerState, store: PlannerStateStore) -> None:
        self._state = state
        self._store = store
        self._command_lock = asyncio.Lock()
        self._listeners: set[Callable[[], None]] = set()

    @property
    def state(self) -> PlannerState:
        """Return the current in-memory projection without performing I/O."""
        return self._state

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to successfully persisted state changes."""
        self._listeners.add(listener)

        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    async def async_update_projection(
        self,
        update: Callable[[], None],
        *,
        guard: Callable[[], None] | None = None,
    ) -> None:
        """Serialize and publish a non-ledger runtime preference update."""
        async with self._command_lock:
            if guard is not None:
                guard()
            update()
            if guard is not None:
                guard()
            self._publish()

    def _publish(self) -> None:
        """Notify listeners while isolating a faulty entity callback."""
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:
                _LOGGER.exception("Vacuum Planner state listener failed")

    def publish_runtime_projection(self) -> None:
        """Publish a runtime-only readiness change without persistence I/O."""
        self._publish()

    async def async_command(
        self,
        command: Callable[[PlannerState], PlannerState],
        *,
        guard: Callable[[], None] | None = None,
    ) -> PlannerState:
        """Apply and atomically persist one command under the shared lock."""
        async with self._command_lock:
            if guard is not None:
                guard()
            updated = command(self._state)
            if updated == self._state:
                return self._state
            if guard is not None:
                guard()
            await self._store.async_save(updated)
            if guard is not None:
                guard()
            self._state = updated
            self._publish()
            return updated
