import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.vacuum_planner.domain.models import (
    BlockGuarantee,
    BlockState,
    DispatchStrategy,
    JobState,
    Mode,
    PlannerState,
    PlanRevision,
    PlanSnapshot,
    PreferredMode,
    QueueLedger,
    RoomPlan,
    SnapshotJob,
)
from custom_components.vacuum_planner.domain.queue import start_due_block
from custom_components.vacuum_planner.domain.serialization import (
    SchemaVersionError,
    deserialize_ledger,
    deserialize_plan_revision,
    deserialize_plan_snapshot,
    deserialize_planner_state,
    serialize_ledger,
    serialize_plan_revision,
    serialize_plan_snapshot,
    serialize_planner_state,
)

NOW = datetime(2026, 9, 17, 8, 0, 0, 123456, tzinfo=UTC)
Serializer = Callable[[Any], dict[str, Any]]
Deserializer = Callable[[dict[str, Any]], Any]


class IDs:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"id-{self.index}"


def revision() -> PlanRevision:
    return PlanRevision(
        "rev-1", NOW,
        (
            RoomPlan(
                "kitchen", "lane", True, 2, 7, PreferredMode.AUTOMATIC, 10,
                last_completed_vacuum_at=NOW,
            ),
        ),
    )


def snapshot() -> PlanSnapshot:
    return PlanSnapshot(
        "rev-1", "lane", NOW,
        (
            SnapshotJob(
                "kitchen",
                "Kitchen",
                {"segments": [4, 5]},  # type: ignore[dict-item]
                Mode.VACUUM,
                10,
                NOW,
            ),
        ),
    )


def ledger() -> QueueLedger:
    started = start_due_block(
        QueueLedger.empty(), snapshot(), "lane", "today", NOW, IDs(),
        DispatchStrategy.NATIVE_BATCH, BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    committing = started.replace_block_state("id-1", BlockState.COMMITTING, NOW)
    return committing.replace_block_state("id-1", BlockState.UNCERTAIN, NOW)


@pytest.mark.parametrize("missing", ["plan_revision", "ledger"])
def test_planner_state_rejects_torn_payload(missing: str) -> None:
    payload = serialize_planner_state(PlannerState(revision(), ledger()))
    payload["data"].pop(missing)

    with pytest.raises(ValueError, match=f"missing {missing}"):
        deserialize_planner_state(payload)


def test_planner_state_rejects_plan_for_another_queue_lane() -> None:
    current_revision = revision()
    other_lane_room = replace(current_revision.room_plans[0], lane_id="other-lane")

    with pytest.raises(ValueError, match="plan lane does not match ledger lane"):
        PlannerState(
            replace(current_revision, room_plans=(other_lane_room,)),
            ledger(),
        )


@pytest.mark.parametrize(
    ("value", "serialize", "deserialize"),
    [
        (revision(), serialize_plan_revision, deserialize_plan_revision),
        (snapshot(), serialize_plan_snapshot, deserialize_plan_snapshot),
        (ledger(), serialize_ledger, deserialize_ledger),
    ],
)
def test_versioned_models_survive_json_restart_roundtrip(
    value: object,
    serialize: Serializer,
    deserialize: Deserializer,
) -> None:
    encoded = serialize(value)
    restarted = json.loads(json.dumps(encoded))

    assert encoded["schema_version"] == 1
    assert deserialize(restarted) == value


def test_restart_preserves_order_identity_uncertain_state_and_adapter_target() -> None:
    restored = deserialize_ledger(json.loads(json.dumps(serialize_ledger(ledger()))))

    assert restored.blocks[0].job_ids == ("id-2",)
    assert restored.blocks[0].state is BlockState.UNCERTAIN
    assert restored.jobs[0].adapter_target_snapshot == {"segments": (4, 5)}
    assert restored.jobs[0].finished_at is None


def test_unknown_future_schema_is_rejected_instead_of_silently_reinterpreted() -> None:
    payload = serialize_ledger(ledger())
    payload["schema_version"] = 999

    with pytest.raises(SchemaVersionError, match="999"):
        deserialize_ledger(payload)


def test_legacy_ledger_schema_is_migrated_for_restart() -> None:
    expected = ledger()
    payload = serialize_ledger(expected)
    payload["schema_version"] = 0
    payload["data"].pop("active_block_id")
    payload["data"].pop("last_reconciled_at")
    payload["data"]["blocks"][0].pop("completed_at")
    payload["data"]["blocks"][0].pop("adapter_run_id")
    payload["data"]["jobs"][0].pop("adapter_token")
    payload["data"]["jobs"][0].pop("error_code")
    payload["data"]["jobs"][0].pop("error_detail")

    restored = deserialize_ledger(json.loads(json.dumps(payload)))

    assert restored == expected


def test_legacy_migration_does_not_reinterpret_another_payload_kind() -> None:
    payload = serialize_ledger(ledger())
    payload["schema_version"] = 0
    payload["kind"] = "plan_revision"

    with pytest.raises(ValueError, match="expected payload kind queue_ledger"):
        deserialize_ledger(payload)


@pytest.mark.parametrize("invalid_version", [False, 0.0])
def test_legacy_migration_requires_an_integer_schema_version(invalid_version: object) -> None:
    payload = serialize_ledger(ledger())
    payload["schema_version"] = invalid_version

    with pytest.raises(SchemaVersionError, match="unsupported schema version"):
        deserialize_ledger(payload)


def test_corrupt_enum_and_references_are_rejected() -> None:
    payload = serialize_ledger(ledger())
    payload["data"]["blocks"][0]["state"] = "invented"
    with pytest.raises(ValueError, match="invented"):
        deserialize_ledger(payload)

    payload = serialize_ledger(ledger())
    payload["data"]["blocks"][0]["job_ids"] = ["missing"]
    with pytest.raises(ValueError, match="unknown job_id"):
        deserialize_ledger(payload)


def test_deserialization_rejects_completed_job_without_completion_timestamp() -> None:
    current = start_due_block(
        QueueLedger.empty(), snapshot(), "lane", "today", NOW, IDs(),
        DispatchStrategy.NATIVE_BATCH, BlockGuarantee.PLANNER_ATOMIC,
    ).ledger
    for block_state in (BlockState.COMMITTING, BlockState.COMMITTED, BlockState.RUNNING):
        current = current.replace_block_state("id-1", block_state, NOW)
    for job_state in (
        JobState.DISPATCHING,
        JobState.ACCEPTED,
        JobState.RUNNING,
        JobState.COMPLETED,
    ):
        current = current.replace_job_state("id-2", job_state, NOW)
    current = current.replace_block_state("id-1", BlockState.COMPLETED, NOW)
    payload = serialize_ledger(current)
    payload["data"]["jobs"][0]["finished_at"] = None

    with pytest.raises(ValueError, match="finished_at is required"):
        deserialize_ledger(payload)


@pytest.mark.parametrize(
    ("payload", "deserialize"),
    [
        (
            {
                **serialize_plan_revision(revision()),
                "data": {
                    **serialize_plan_revision(revision())["data"],
                    "room_plans": [
                        {
                            **serialize_plan_revision(revision())["data"]["room_plans"][0],
                            "enabled": "false",
                        }
                    ],
                },
            },
            deserialize_plan_revision,
        ),
        (
            {
                **serialize_plan_snapshot(snapshot()),
                "data": {
                    **serialize_plan_snapshot(snapshot())["data"],
                    "jobs": [
                        {
                            **serialize_plan_snapshot(snapshot())["data"]["jobs"][0],
                            "priority": True,
                        }
                    ],
                },
            },
            deserialize_plan_snapshot,
        ),
        (
            {
                **serialize_plan_snapshot(snapshot()),
                "data": {**serialize_plan_snapshot(snapshot())["data"], "lane_id": 7},
            },
            deserialize_plan_snapshot,
        ),
        (
            {
                **serialize_ledger(ledger()),
                "data": {**serialize_ledger(ledger())["data"], "blocks": {}},
            },
            deserialize_ledger,
        ),
    ],
)
def test_deserialization_rejects_json_type_coercion(
    payload: dict[str, Any], deserialize: Deserializer
) -> None:
    with pytest.raises(ValueError, match="must be"):
        deserialize(payload)
