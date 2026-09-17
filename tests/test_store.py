import asyncio
from datetime import UTC, datetime
from typing import Any

from custom_components.vacuum_planner.domain.models import (
    PlannerState,
    PlanRevision,
    PreferredMode,
    QueueLedger,
    RoomPlan,
)
from custom_components.vacuum_planner.store import PlannerStore

NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


class MemoryStore:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data
        self.saved: list[dict[str, Any]] = []

    async def async_load(self) -> dict[str, Any] | None:
        return self.data

    async def async_save(self, data: dict[str, Any]) -> None:
        self.saved.append(data)
        self.data = data


def planner_state() -> PlannerState:
    return PlannerState(
        plan_revision=PlanRevision(
            revision_id="revision-1",
            created_at=NOW,
            room_plans=(
                RoomPlan(
                    area_id="kitchen",
                    lane_id="lane-1",
                    enabled=True,
                    vacuum_interval_days=2,
                    vacuum_and_mop_interval_days=7,
                    preferred_mode=PreferredMode.AUTOMATIC,
                    priority=10,
                ),
            ),
        ),
        ledger=QueueLedger.empty(),
    )


def test_store_saves_and_restores_the_atomic_planner_state() -> None:
    backend = MemoryStore()
    store = PlannerStore(backend)
    expected = planner_state()

    asyncio.run(store.async_save(expected))

    assert len(backend.saved) == 1
    assert asyncio.run(store.async_load()) == expected
