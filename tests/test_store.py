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
from custom_components.vacuum_planner.domain.serialization import serialize_planner_state
from custom_components.vacuum_planner.store import PlannerStore

NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


class MemoryStore:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data
        self.saved: list[dict[str, Any]] = []
        self.remove_calls = 0

    async def async_load(self) -> dict[str, Any] | None:
        return self.data

    async def async_save(self, data: dict[str, Any]) -> None:
        self.saved.append(data)
        self.data = data

    async def async_remove(self) -> None:
        self.remove_calls += 1
        self.data = None


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
                    preferred_mode=PreferredMode.VACUUM,
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


def test_store_durably_rewrites_a_migrated_legacy_root() -> None:
    expected = planner_state()
    legacy = serialize_planner_state(expected)
    legacy["schema_version"] = 0
    legacy["data"]["ledger"]["schema_version"] = 0
    legacy["data"]["ledger"]["data"].pop("active_block_id")
    legacy["data"]["ledger"]["data"].pop("last_reconciled_at")
    backend = MemoryStore(legacy)

    restored = asyncio.run(PlannerStore(backend).async_load())

    assert restored == expected
    assert backend.saved == [serialize_planner_state(expected)]


def test_store_removal_is_delegated_idempotently_when_payload_is_missing() -> None:
    backend = MemoryStore()
    store = PlannerStore(backend)

    asyncio.run(store.async_remove())
    asyncio.run(store.async_remove())

    assert backend.remove_calls == 2
