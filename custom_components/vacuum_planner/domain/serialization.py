"""Versioned JSON-compatible persistence codecs for phase-1 domain state."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, cast

from .models import (
    BlockGuarantee,
    BlockKind,
    BlockState,
    DispatchStrategy,
    JobState,
    JsonValue,
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
    thaw_json,
)

SCHEMA_VERSION = 1
Payload = dict[str, Any]


class SchemaVersionError(ValueError):
    """The payload cannot be safely interpreted by this codec."""

    def __init__(self, version: object) -> None:
        self.version = version
        super().__init__(f"unsupported schema version: {version}")


def _envelope(kind: str, data: Payload) -> Payload:
    return {"schema_version": SCHEMA_VERSION, "kind": kind, "data": data}


def _data(payload: Payload, kind: str) -> Payload:
    version = payload.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise SchemaVersionError(version)
    if payload.get("kind") != kind:
        raise ValueError(f"expected payload kind {kind}")
    data = payload.get("data")
    if type(data) is not dict:
        raise ValueError("payload data must be an object")
    return data


def _string(value: object, field: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field} must be a string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


def _array(value: object, field: str) -> list[Any]:
    if type(value) is not list:
        raise ValueError(f"{field} must be an array")
    return value


def _object(value: object, field: str) -> Payload:
    if type(value) is not dict:
        raise ValueError(f"{field} must be an object")
    if any(type(key) is not str for key in value):
        raise ValueError(f"{field} keys must be strings")
    return value


def _json_value(value: object, field: str) -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{field} must contain finite JSON numbers")
        return value
    if type(value) is list:
        return [_json_value(item, field) for item in value]
    if type(value) is dict:
        obj = _object(value, field)
        return {key: _json_value(item, field) for key, item in obj.items()}
    raise ValueError(f"{field} must be a JSON value")


def _dt(value: object) -> datetime | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("timestamp must be an ISO-8601 string")
    return datetime.fromisoformat(value)


def _dt_required(value: object) -> datetime:
    parsed = _dt(value)
    if parsed is None:
        raise ValueError("required timestamp is missing")
    return parsed


def _dt_dump(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _room_dump(room: RoomPlan) -> Payload:
    return {
        "area_id": room.area_id,
        "lane_id": room.lane_id,
        "enabled": room.enabled,
        "vacuum_interval_days": room.vacuum_interval_days,
        "vacuum_and_mop_interval_days": room.vacuum_and_mop_interval_days,
        "preferred_mode": room.preferred_mode.value,
        "priority": room.priority,
        "skip_until": _dt_dump(room.skip_until),
        "last_completed_vacuum_at": _dt_dump(room.last_completed_vacuum_at),
        "last_completed_vacuum_and_mop_at": _dt_dump(room.last_completed_vacuum_and_mop_at),
    }


def _room_load(data: Payload) -> RoomPlan:
    raw_preferred_mode = _string(data["preferred_mode"], "preferred_mode")
    # Internal legacy restart migration: the removed automatic policy is
    # canonicalized to the conservative retained vacuum policy.
    preferred_mode = (
        PreferredMode.VACUUM
        if raw_preferred_mode == "automatic"
        else PreferredMode(raw_preferred_mode)
    )
    return RoomPlan(
        area_id=_string(data["area_id"], "area_id"),
        lane_id=_string(data["lane_id"], "lane_id"),
        enabled=_boolean(data["enabled"], "enabled"),
        vacuum_interval_days=_integer(data["vacuum_interval_days"], "vacuum_interval_days"),
        vacuum_and_mop_interval_days=_optional_integer(
            data["vacuum_and_mop_interval_days"], "vacuum_and_mop_interval_days"
        ),
        preferred_mode=preferred_mode,
        priority=_integer(data["priority"], "priority"),
        skip_until=_dt(data.get("skip_until")),
        last_completed_vacuum_at=_dt(data.get("last_completed_vacuum_at")),
        last_completed_vacuum_and_mop_at=_dt(data.get("last_completed_vacuum_and_mop_at")),
    )


def serialize_plan_revision(revision: PlanRevision) -> Payload:
    """Serialize a plan revision with an explicit schema envelope."""
    return _envelope(
        "plan_revision",
        {
            "revision_id": revision.revision_id,
            "created_at": _dt_dump(revision.created_at),
            "room_plans": [_room_dump(room) for room in revision.room_plans],
        },
    )


def deserialize_plan_revision(payload: Payload) -> PlanRevision:
    """Deserialize and validate a plan revision."""
    data = _data(payload, "plan_revision")
    return PlanRevision(
        _string(data["revision_id"], "revision_id"),
        _dt_required(data["created_at"]),
        tuple(
            _room_load(_object(item, "room_plan"))
            for item in _array(data["room_plans"], "room_plans")
        ),
    )


def _snapshot_job_dump(job: SnapshotJob) -> Payload:
    return {
        "area_id": job.area_id,
        "area_name_snapshot": job.area_name_snapshot,
        "adapter_target_snapshot": thaw_json(job.adapter_target_snapshot),
        "mode": job.mode.value,
        "priority": job.priority,
        "due_at": _dt_dump(job.due_at),
    }


def _snapshot_job_load(data: Payload) -> SnapshotJob:
    return SnapshotJob(
        area_id=_string(data["area_id"], "area_id"),
        area_name_snapshot=_string(data["area_name_snapshot"], "area_name_snapshot"),
        adapter_target_snapshot=cast(
            "JsonValue",
            _json_value(data["adapter_target_snapshot"], "adapter_target_snapshot"),
        ),
        mode=Mode(_string(data["mode"], "mode")),
        priority=_integer(data["priority"], "priority"),
        due_at=_dt_required(data["due_at"]),
    )


def serialize_plan_snapshot(snapshot: PlanSnapshot) -> Payload:
    """Serialize an immutable due snapshot."""
    return _envelope(
        "plan_snapshot",
        {
            "plan_revision": snapshot.plan_revision,
            "lane_id": snapshot.lane_id,
            "evaluated_at": _dt_dump(snapshot.evaluated_at),
            "jobs": [_snapshot_job_dump(job) for job in snapshot.jobs],
        },
    )


def deserialize_plan_snapshot(payload: Payload) -> PlanSnapshot:
    """Deserialize and validate an immutable due snapshot."""
    data = _data(payload, "plan_snapshot")
    return PlanSnapshot(
        _string(data["plan_revision"], "plan_revision"),
        _string(data["lane_id"], "lane_id"),
        _dt_required(data["evaluated_at"]),
        tuple(
            _snapshot_job_load(_object(item, "snapshot job"))
            for item in _array(data["jobs"], "jobs")
        ),
    )


def _block_dump(block: QueueBlock) -> Payload:
    return {
        "block_id": block.block_id,
        "kind": block.kind.value,
        "lane_id": block.lane_id,
        "plan_revision": block.plan_revision,
        "idempotency_key": block.idempotency_key,
        "created_at": _dt_dump(block.created_at),
        "sealed_at": _dt_dump(block.sealed_at),
        "committed_at": _dt_dump(block.committed_at),
        "completed_at": _dt_dump(block.completed_at),
        "state": block.state.value,
        "job_ids": list(block.job_ids),
        "dispatch_strategy": block.dispatch_strategy.value,
        "adapter_run_id": block.adapter_run_id,
        "guarantee": block.guarantee.value,
    }


def _block_load(data: Payload) -> QueueBlock:
    raw_kind = _string(data["kind"], "kind")
    # Internal legacy restart migration: removed ad-hoc blocks remain recoverable,
    # but are canonicalized into the only retained scheduled block kind.
    kind = BlockKind.SCHEDULED if raw_kind == "adhoc" else BlockKind(raw_kind)
    return QueueBlock(
        block_id=_string(data["block_id"], "block_id"),
        kind=kind,
        lane_id=_string(data["lane_id"], "lane_id"),
        plan_revision=_string(data["plan_revision"], "plan_revision"),
        idempotency_key=_string(data["idempotency_key"], "idempotency_key"),
        created_at=_dt_required(data["created_at"]),
        sealed_at=_dt(data.get("sealed_at")),
        state=BlockState(_string(data["state"], "state")),
        job_ids=tuple(_string(item, "job_id") for item in _array(data["job_ids"], "job_ids")),
        dispatch_strategy=DispatchStrategy(_string(data["dispatch_strategy"], "dispatch_strategy")),
        guarantee=BlockGuarantee(_string(data["guarantee"], "guarantee")),
        committed_at=_dt(data.get("committed_at")),
        completed_at=_dt(data.get("completed_at")),
        adapter_run_id=_optional_string(data.get("adapter_run_id"), "adapter_run_id"),
    )


def _job_dump(job: QueueJob) -> Payload:
    return {
        "job_id": job.job_id,
        "block_id": job.block_id,
        "area_id": job.area_id,
        "area_name_snapshot": job.area_name_snapshot,
        "adapter_target_snapshot": thaw_json(job.adapter_target_snapshot),
        "mode": job.mode.value,
        "position": job.position,
        "state": job.state.value,
        "attempt": job.attempt,
        "adapter_token": job.adapter_token,
        "planned_at": _dt_dump(job.planned_at),
        "sent_at": _dt_dump(job.sent_at),
        "started_at": _dt_dump(job.started_at),
        "finished_at": _dt_dump(job.finished_at),
        "error_code": job.error_code,
        "error_detail": job.error_detail,
    }


def _job_load(data: Payload) -> QueueJob:
    return QueueJob(
        job_id=_string(data["job_id"], "job_id"),
        block_id=_string(data["block_id"], "block_id"),
        area_id=_string(data["area_id"], "area_id"),
        area_name_snapshot=_string(data["area_name_snapshot"], "area_name_snapshot"),
        adapter_target_snapshot=cast(
            "JsonValue",
            _json_value(data["adapter_target_snapshot"], "adapter_target_snapshot"),
        ),
        mode=Mode(_string(data["mode"], "mode")),
        position=_integer(data["position"], "position"),
        state=JobState(_string(data["state"], "state")),
        attempt=_integer(data["attempt"], "attempt"),
        planned_at=_dt_required(data["planned_at"]),
        adapter_token=_optional_string(data.get("adapter_token"), "adapter_token"),
        sent_at=_dt(data.get("sent_at")),
        started_at=_dt(data.get("started_at")),
        finished_at=_dt(data.get("finished_at")),
        error_code=_optional_string(data.get("error_code"), "error_code"),
        error_detail=_optional_string(data.get("error_detail"), "error_detail"),
    )


def serialize_ledger(ledger: QueueLedger) -> Payload:
    """Serialize the authoritative queue ledger for durable restart."""
    return _envelope(
        "queue_ledger",
        {
            "revision": ledger.revision,
            "blocks": [_block_dump(block) for block in ledger.blocks],
            "jobs": [_job_dump(job) for job in ledger.jobs],
            "active_block_id": ledger.active_block_id,
            "last_reconciled_at": _dt_dump(ledger.last_reconciled_at),
        },
    )


def _migrate_ledger_payload(payload: Payload) -> Payload:
    """Upgrade supported legacy ledger payloads without mutating stored input."""
    version = payload.get("schema_version")
    if type(version) is not int or version != 0:
        return payload
    if payload.get("kind") != "queue_ledger":
        raise ValueError("expected payload kind queue_ledger")
    data = _object(payload.get("data"), "payload data")
    blocks = [
        {
            **_object(item, "block"),
            "completed_at": _object(item, "block").get("completed_at"),
            "adapter_run_id": _object(item, "block").get("adapter_run_id"),
        }
        for item in _array(data.get("blocks"), "blocks")
    ]
    jobs = [
        {
            **_object(item, "job"),
            "adapter_token": _object(item, "job").get("adapter_token"),
            "error_code": _object(item, "job").get("error_code"),
            "error_detail": _object(item, "job").get("error_detail"),
        }
        for item in _array(data.get("jobs"), "jobs")
    ]
    return _envelope(
        "queue_ledger",
        {
            **data,
            "blocks": blocks,
            "jobs": jobs,
            "active_block_id": data.get("active_block_id"),
            "last_reconciled_at": data.get("last_reconciled_at"),
        },
    )


def deserialize_ledger(payload: Payload) -> QueueLedger:
    """Deserialize and fully revalidate an authoritative queue ledger."""
    data = _data(_migrate_ledger_payload(payload), "queue_ledger")
    return QueueLedger(
        schema_version=SCHEMA_VERSION,
        revision=_integer(data["revision"], "revision"),
        blocks=tuple(
            _block_load(_object(item, "block")) for item in _array(data["blocks"], "blocks")
        ),
        jobs=tuple(_job_load(_object(item, "job")) for item in _array(data["jobs"], "jobs")),
        active_block_id=_optional_string(data.get("active_block_id"), "active_block_id"),
        last_reconciled_at=_dt(data.get("last_reconciled_at")),
    )


def serialize_planner_state(state: PlannerState) -> Payload:
    """Serialize the plan and ledger as one atomic persistence value."""
    return _envelope(
        "planner_state",
        {
            "plan_revision": serialize_plan_revision(state.plan_revision),
            "ledger": serialize_ledger(state.ledger),
        },
    )


def _migrate_planner_state_payload(payload: Payload) -> Payload:
    """Upgrade the legacy atomic-root envelope without mutating stored input."""
    version = payload.get("schema_version")
    if type(version) is not int or version != 0:
        return payload
    if payload.get("kind") != "planner_state":
        raise ValueError("expected payload kind planner_state")
    data = _object(payload.get("data"), "payload data")
    return _envelope("planner_state", dict(data))


def deserialize_planner_state(payload: Payload) -> PlannerState:
    """Deserialize the complete persisted planner root."""
    data = _data(_migrate_planner_state_payload(payload), "planner_state")
    for required in ("plan_revision", "ledger"):
        if required not in data:
            raise ValueError(f"missing {required}")
    return PlannerState(
        deserialize_plan_revision(_object(data["plan_revision"], "plan_revision")),
        deserialize_ledger(_object(data["ledger"], "ledger")),
    )
