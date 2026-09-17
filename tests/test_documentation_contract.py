from pathlib import Path

DOCS = Path(__file__).parents[1] / "docs"
UX = (DOCS / "ux-specification.md").read_text(encoding="utf-8")
ENTITY_CONTRACT = (DOCS / "entity-contract.md").read_text(encoding="utf-8")
DASHBOARD = (DOCS / "config-flow-and-dashboard.md").read_text(encoding="utf-8")


def test_ux_public_contract_matches_canonical_entity_action_and_dashboard_docs() -> None:
    for action in (
        "start_next",
        "start_due_block",
        "enqueue_area",
        "skip_area_today",
        "postpone_area",
        "cancel_block",
        "resolve_uncertain_run",
        "get_queue",
    ):
        assert f"`vacuum_planner.{action}`" in UX

    for contradictory_contract in (
        "`vacuum.<planner>`",
        "`<domain>.start_due`",
        "automatisch bereitgestellten, verwalteten Dashboard",
        "zur Sidebar hinzufügen",
        "Eigene Kopie",
    ):
        assert contradictory_contract not in UX


def test_one_tap_uses_start_next_and_keeps_start_due_block_technical() -> None:
    for document in (UX, ENTITY_CONTRACT, DASHBOARD):
        assert "`vacuum_planner.start_next`" in document

    assert "One-Tap" in ENTITY_CONTRACT
    assert "technische Block-Action" in ENTITY_CONTRACT
    assert "One-Tap" in DASHBOARD
    assert "technische Block-Action" in UX
