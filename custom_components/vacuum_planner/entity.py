"""In-memory entity projections for Vacuum Planner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .domain.models import BlockState

if TYPE_CHECKING:
    from .const import VacuumPlannerRuntimeData


def planner_status(runtime_data: VacuumPlannerRuntimeData) -> str:
    """Return the public planner status without performing I/O."""
    if not runtime_data.planning_enabled:
        return "paused"
    state = runtime_data.state
    if state is not None and any(
        block.state in {BlockState.REJECTED, BlockState.UNCERTAIN}
        for block in state.ledger.blocks
    ):
        return "attention"
    if state is not None and any(
        block.state is BlockState.COMMITTING for block in state.ledger.blocks
    ):
        return "committing"
    if state is not None and any(
        block.state in {BlockState.COMMITTED, BlockState.RUNNING}
        for block in state.ledger.blocks
    ):
        return "running"
    if state is not None and any(
        block.state is BlockState.SEALED for block in state.ledger.blocks
    ):
        return "ready"
    return "idle"
