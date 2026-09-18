from datetime import UTC, datetime

from custom_components import vacuum_planner
from custom_components.vacuum_planner.const import VacuumPlannerRuntimeData
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    DispatchStrategy,
    Mode,
    PlannerState,
    PlanRevision,
    PlanSnapshot,
    QueueLedger,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import start_due_block

NOW = datetime(2026, 9, 18, 8, tzinfo=UTC)


class NoOpStore:
    async def async_save(self, _state: PlannerState) -> None:
        pass


def test_get_queue_response_exposes_public_identifiers_without_adapter_targets() -> None:
    ids = iter(("block-1", "job-1"))
    result = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot(
            "revision-1",
            "lane-1",
            NOW,
            (
                SnapshotJob(
                    "kitchen",
                    "Kitchen",
                    {"vendor_segment": "secret-42"},
                    Mode.VACUUM,
                    4,
                    NOW,
                ),
            ),
        ),
        "lane-1",
        "2026-09-18",
        NOW,
        lambda: next(ids),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    state = PlannerState(PlanRevision("revision-1", NOW, ()), result.ledger)
    runtime = VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.downstairs",
        coordinator=PlannerCoordinator(state, NoOpStore()),
    )

    response = vacuum_planner.get_queue_response(runtime)

    assert response == {
        "revision": 1,
        "blocks": [
            {
                "block_id": "block-1",
                "kind": "scheduled",
                "state": "sealed",
                "guarantee": "planner_atomic",
                "job_ids": ["job-1"],
            }
        ],
        "jobs": [
            {
                "job_id": "job-1",
                "block_id": "block-1",
                "area_id": "kitchen",
                "area_name": "Kitchen",
                "mode": "vacuum",
                "state": "pending",
                "position": 0,
            }
        ],
    }
    assert "secret-42" not in str(response)
