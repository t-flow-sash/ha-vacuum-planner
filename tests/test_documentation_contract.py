from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from custom_components import vacuum_planner as integration
from custom_components.vacuum_planner.const import VacuumPlannerRuntimeData
from custom_components.vacuum_planner.public_actions import cancel_pending_block

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
UX = (DOCS / "ux-specification.md").read_text(encoding="utf-8")
ENTITY_CONTRACT = (DOCS / "entity-contract.md").read_text(encoding="utf-8")
QUEUE_SEMANTICS = (DOCS / "queue-semantics.md").read_text(encoding="utf-8")
DASHBOARD = (DOCS / "config-flow-and-dashboard.md").read_text(encoding="utf-8")


def _real_sensor_keys() -> set[str]:
    source = (ROOT / "custom_components" / "vacuum_planner" / "sensor.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name == "VacuumPlannerSensor":
            continue
        for child in node.body:
            if not isinstance(child, ast.FunctionDef) or child.name != "__init__":
                continue
            for call in (item for item in ast.walk(child) if isinstance(item, ast.Call)):
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "__init__"
                    and len(call.args) == 2
                    and isinstance(call.args[1], ast.Constant)
                    and isinstance(call.args[1].value, str)
                ):
                    keys.add(call.args[1].value)
    return keys


def _yaml_example_after(heading: str, document: str) -> object:
    section = document.split(heading, maxsplit=1)[1]
    match = re.search(r"```yaml\n(.*?)\n```", section, flags=re.DOTALL)
    assert match is not None
    return yaml.safe_load(match.group(1))


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    segment = ast.get_source_segment(source, function)
    assert segment is not None
    return segment


def test_ux_public_contract_matches_canonical_entity_action_and_dashboard_docs() -> None:
    for action in (
        "start_next",
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


def test_one_tap_uses_only_start_next() -> None:
    for document in (UX, ENTITY_CONTRACT, DASHBOARD):
        assert "`vacuum_planner.start_next`" in document

    assert "One-Tap" in ENTITY_CONTRACT
    assert "One-Tap" in DASHBOARD


def test_entity_table_matches_the_real_sensor_platform() -> None:
    documented = {
        "status": "Status",
        "next_action": "Nächste Aktion",
        "pending_count": "Ausstehende Aufgaben",
        "current_phase": "Aktuelle Phase",
        "capability_tier": "Capability-Stufe",
        "queue": "Queue",
    }

    assert set(documented) == _real_sensor_keys()
    for label in documented.values():
        assert f"| `sensor` | {label} |" in ENTITY_CONTRACT
    public_contract_docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in DOCS.rglob("*.md")
        if "development" not in path.parts
    )
    assert "Nächster Start" not in public_contract_docs


def test_status_sensor_docs_do_not_promise_undelivered_attributes() -> None:
    sensor_source = ast.parse(
        (ROOT / "custom_components" / "vacuum_planner" / "sensor.py").read_text(encoding="utf-8")
    )
    status_class = next(
        node
        for node in sensor_source.body
        if isinstance(node, ast.ClassDef) and node.name == "VacuumPlannerStatusSensor"
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "extra_state_attributes"
        for node in status_class.body
    )
    assert "Der Status-Sensor liefert keine zusätzlichen State-Attribute." in ENTITY_CONTRACT
    for undocumented_attribute in (
        "active_block_id",
        "dispatch_strategy",
        "robot_lane_count",
    ):
        assert undocumented_attribute not in ENTITY_CONTRACT


def test_get_queue_example_has_the_real_top_level_response_shape() -> None:
    actual = integration.get_queue_response(VacuumPlannerRuntimeData("vacuum.test"))
    example = _yaml_example_after("## `get_queue`-Response (Beispiel)", ENTITY_CONTRACT)

    assert isinstance(example, dict)
    assert set(example) == set(actual) == {"revision", "blocks", "jobs"}
    assert isinstance(example["blocks"], list)
    assert isinstance(example["jobs"], list)


def test_cancel_block_docs_match_the_real_fail_closed_boundary() -> None:
    source = inspect.getsource(cancel_pending_block)
    assert "BlockState.SEALED" in source
    assert "JobState.PENDING" in source
    assert "nur `sealed` mit ausschließlich `pending`-Jobs" in ENTITY_CONTRACT
    assert "Adapter-Cancel-Bestätigung ist nicht implementiert" in ENTITY_CONTRACT
    assert "möglicherweise externe Arbeit" in ENTITY_CONTRACT


def test_start_next_docs_match_the_real_single_job_materialization() -> None:
    source = _function_source(
        ROOT / "custom_components" / "vacuum_planner" / "__init__.py",
        "_register_start_next_action",
    )
    assert "due_snapshot.jobs[:1]" in source
    assert "genau eine nächste fällige Aufgabe" in ENTITY_CONTRACT
    assert "genau eine nächste fällige Aufgabe" in QUEUE_SEMANTICS
    for unsupported_claim in (
        "vollständigen Snapshot materialisieren",
        "halber Tagesblock",
        "Multi-Area-Aufruf",
        "Jobs des fälligen Tagesblocks",
    ):
        assert unsupported_claim not in QUEUE_SEMANTICS


def test_public_contract_docs_do_not_restore_day_block_or_multi_job_promises() -> None:
    documents = "\n".join(
        (DOCS / name).read_text(encoding="utf-8")
        for name in (
            "requirements.md",
            "architecture.md",
            "current-state.md",
            "ux-specification.md",
            "requirements-traceability.md",
            "capabilities.md",
            "adr/0001-solution-shape.md",
        )
    )
    for unsupported_claim in (
        "Tagesblock",
        "3 Räume jetzt reinigen",
        "Mehrere Räume in einer Reinigung",
        "Tagesplan wird beim Start logisch als geschlossener Block",
        "gestarteten Tagesplan als geschlossenen Block",
        "gestarteter Tagesplan ist ein zusammenhängender Queue-Block",
        "Liste aller aktuell startfähigen, offenen Tagesaufgaben",
        "alle offenen, startfähigen Tagesaufgaben werden als Block gestartet",
        "kompletten Block",
        "unveränderlichen Tagesblock",
        "vollständiges Sealing",
    ):
        assert unsupported_claim not in documents
