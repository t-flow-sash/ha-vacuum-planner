import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from custom_components.vacuum_planner.const import VacuumPlannerRuntimeData
from custom_components.vacuum_planner.coordinator import PlannerCoordinator
from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockKind,
    BlockState,
    DispatchStrategy,
    JobState,
    Mode,
    PlannerState,
    PlanRevision,
    PlanSnapshot,
    PreferredMode,
    QueueBlock,
    QueueJob,
    QueueLedger,
    RoomPlan,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import start_due_block
from custom_components.vacuum_planner.entity import (
    attention_required,
    capability_tier,
    current_phase,
    next_action,
    pending_count,
    planner_ready,
    planner_status,
    queue_projection,
)

NOW = datetime(2026, 9, 19, 8, tzinfo=UTC)


class NullStore:
    async def async_save(self, _state: PlannerState) -> None:
        pass


def runtime_with_state(
    state: PlannerState,
    *,
    area_names: dict[str, str] | None = None,
) -> VacuumPlannerRuntimeData:
    return VacuumPlannerRuntimeData(
        vacuum_entity_id="vacuum.test",
        coordinator=PlannerCoordinator(state, NullStore()),
        area_names=area_names,
    )


def due_state() -> PlannerState:
    plan = RoomPlan(
        area_id="kitchen",
        lane_id="lane",
        enabled=True,
        vacuum_interval_days=1,
        vacuum_and_mop_interval_days=None,
        preferred_mode=PreferredMode.VACUUM,
        priority=2,
    )
    return PlannerState(PlanRevision("revision", NOW, (plan,)), QueueLedger.empty())


def sealed_state() -> PlannerState:
    ids = iter(("block", "job"))
    result = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot(
            "revision",
            "lane",
            NOW,
            (SnapshotJob("kitchen", "Kitchen", "vendor-secret", Mode.VACUUM, 2, NOW),),
        ),
        "lane",
        "key",
        NOW,
        lambda: next(ids),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    )
    return PlannerState(PlanRevision("revision", NOW, ()), result.ledger)


def test_public_projection_exposes_due_work_without_adapter_data() -> None:
    runtime = runtime_with_state(due_state(), area_names={"kitchen": "Kitchen"})

    assert next_action(runtime, NOW) == {
        "area_id": "kitchen",
        "area_name": "Kitchen",
        "mode": "vacuum",
        "due_at": NOW.isoformat(),
    }
    assert pending_count(runtime) == 0
    assert current_phase(runtime) == "idle"
    assert capability_tier(runtime) == "T1"
    assert planner_ready(runtime) is True
    assert attention_required(runtime) is False
    assert "vendor" not in str(next_action(runtime, NOW))


def test_public_projection_uses_ledger_and_flags_uncertainty() -> None:
    state = sealed_state()
    runtime = runtime_with_state(state)
    assert pending_count(runtime) == 1
    assert current_phase(runtime) == "sealed"

    uncertain = replace(
        state,
        ledger=replace(
            state.ledger,
            blocks=(replace(state.ledger.blocks[0], state=BlockState.UNCERTAIN),),
        ),
    )
    runtime = runtime_with_state(uncertain)
    assert planner_ready(runtime) is False
    assert attention_required(runtime) is True


def test_topology_failure_projects_blocked_remediation_instead_of_due_work() -> None:
    runtime = runtime_with_state(due_state(), area_names={"kitchen": "Kitchen"})
    runtime.topology_ready = False

    assert planner_ready(runtime) is False
    assert attention_required(runtime) is True
    assert planner_status(runtime) == "attention"
    assert next_action(runtime, NOW) == {
        "status": "blocked",
        "remediation": "Repair topology issue and reload config entry",
    }


def test_queue_projection_is_ordered_bounded_and_excludes_private_adapter_data() -> None:
    jobs = tuple(
        SnapshotJob(
            f"area-{index}",
            f"Room {index} <unsafe>",
            {"segment_id": index, "token": "private"},
            Mode.VACUUM,
            30 - index,
            NOW,
        )
        for index in range(22)
    )
    ids = iter(("block", *(f"job-{index}" for index in range(22))))
    result = start_due_block(
        QueueLedger.empty(),
        PlanSnapshot("revision", "lane", NOW, jobs),
        "lane",
        "key",
        NOW,
        lambda: next(ids),
        DispatchStrategy.PLANNER_SEQUENTIAL,
        BlockGuarantee.PLANNER_ATOMIC,
    )

    projection = queue_projection(
        runtime_with_state(PlannerState(PlanRevision("revision", NOW, ()), result.ledger))
    )

    assert projection["total_count"] == 22
    assert projection["projected_count"] == 20
    assert projection["truncated"] is True
    assert [item["position"] for item in projection["items"]] == list(range(20))
    assert projection["items"][0] == {
        "area_name": "Room 0 <unsafe>",
        "mode": "vacuum",
        "position": 0,
        "status": "pending",
    }
    serialized = str(projection)
    assert "segment_id" not in serialized
    assert "token" not in serialized
    assert "job-" not in serialized
    assert "area-" not in serialized


def test_queue_projection_prioritizes_running_job_over_more_than_twenty_old_jobs() -> None:
    history = tuple(
        QueueJob(
            job_id=f"history-{index}",
            block_id=f"history-block-{index}",
            area_id=f"old-{index}",
            area_name_snapshot=f"Old room {index}",
            adapter_target_snapshot="private",
            mode=Mode.VACUUM,
            position=0,
            state=JobState.COMPLETED,
            attempt=1,
            planned_at=NOW,
            sent_at=NOW,
            started_at=NOW,
            finished_at=NOW,
        )
        for index in range(25)
    )
    running = QueueJob(
        job_id="running",
        block_id="running-block",
        area_id="current",
        area_name_snapshot="Current room",
        adapter_target_snapshot="private",
        mode=Mode.VACUUM,
        position=0,
        state=JobState.RUNNING,
        attempt=1,
        planned_at=NOW,
        sent_at=NOW,
        started_at=NOW,
    )
    blocks = tuple(
        QueueBlock(
            block_id=f"history-block-{index}",
            kind=BlockKind.SCHEDULED,
            lane_id="lane",
            plan_revision="revision",
            idempotency_key=f"history-key-{index}",
            created_at=NOW,
            sealed_at=NOW,
            state=BlockState.COMPLETED,
            job_ids=(f"history-{index}",),
            dispatch_strategy=DispatchStrategy.NATIVE_BATCH,
            guarantee=BlockGuarantee.PLANNER_ATOMIC,
            committed_at=NOW,
            completed_at=NOW,
        )
        for index in range(25)
    )
    running_block = QueueBlock(
        block_id="running-block",
        kind=BlockKind.SCHEDULED,
        lane_id="lane",
        plan_revision="revision",
        idempotency_key="running-key",
        created_at=NOW,
        sealed_at=NOW,
        state=BlockState.RUNNING,
        job_ids=("running",),
        dispatch_strategy=DispatchStrategy.NATIVE_BATCH,
        guarantee=BlockGuarantee.PLANNER_ATOMIC,
        committed_at=NOW,
    )
    ledger = QueueLedger(
        schema_version=1,
        revision=26,
        blocks=(*blocks, running_block),
        jobs=(*history, running),
    )

    projection = queue_projection(
        runtime_with_state(PlannerState(PlanRevision("revision", NOW, ()), ledger))
    )

    assert projection["projected_count"] == 20
    assert projection["total_count"] == 26
    assert projection["truncated"] is True
    assert projection["items"][0]["area_name"] == "Current room"
    assert projection["items"][0]["status"] == "running"
    assert [item["area_name"] for item in projection["items"][1:]] == [
        f"Old room {index}" for index in range(24, 5, -1)
    ]


def test_planning_preference_mutation_is_serialized_and_published() -> None:
    async def exercise() -> tuple[bool, int]:
        runtime = runtime_with_state(due_state())
        writes = 0

        def listener() -> None:
            nonlocal writes
            writes += 1

        assert runtime.coordinator is not None
        runtime.coordinator.async_add_listener(listener)
        await runtime.async_set_planning_enabled(enabled=False)
        return runtime.planning_enabled, writes

    enabled, writes = asyncio.run(exercise())
    assert enabled is False
    assert writes == 1
