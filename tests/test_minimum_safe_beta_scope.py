"""Negative inventory contracts for the Minimum Safe Beta surface."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "vacuum_planner"


class MinimumSafeBetaScopeTests(unittest.TestCase):
    """Prove removed public and topology-changing surfaces stay absent."""

    def test_ad_hoc_enqueue_surface_is_absent(self) -> None:
        forbidden = "enqueue" + "_area"
        paths = [
            COMPONENT / "__init__.py",
            COMPONENT / "const.py",
            COMPONENT / "services.yaml",
            COMPONENT / "domain" / "queue.py",
            COMPONENT / "strings.json",
            COMPONENT / "translations" / "de.json",
            COMPONENT / "translations" / "en.json",
            ROOT / "README.md",
            ROOT / "docs" / "architecture.md",
            ROOT / "docs" / "entity-contract.md",
            ROOT / "docs" / "queue-semantics.md",
            ROOT / "docs" / "ux-specification.md",
        ]
        for path in paths:
            assert forbidden not in path.read_text(encoding="utf-8"), path.as_posix()

    def test_ad_hoc_block_and_extra_clean_contracts_are_absent(self) -> None:
        model_source = (COMPONENT / "domain" / "models.py").read_text(encoding="utf-8")
        assert ("AD" + "HOC") not in model_source
        assert ("ad" + "hoc") not in model_source
        for path in (
            ROOT / "docs" / "architecture.md",
            ROOT / "docs" / "capabilities.md",
            ROOT / "docs" / "entity-contract.md",
            ROOT / "docs" / "queue-semantics.md",
            ROOT / "docs" / "ux-specification.md",
        ):
            text = path.read_text(encoding="utf-8")
            assert ("Extra-" + "Reinigung") not in text, path.as_posix()
            assert ("Zusatz" + "reinigung") not in text, path.as_posix()
            assert ("Ad-" + "hoc") not in text, path.as_posix()
            assert ("ad" + "hoc") not in text, path.as_posix()
            assert ("App" + "end") not in text, path.as_posix()
            assert ("app" + "end") not in text, path.as_posix()

    def test_removed_automatic_preferred_mode_is_absent(self) -> None:
        forbidden_enum = "AUTO" + "MATIC"
        forbidden_value = "auto" + "matic"
        for path in (
            COMPONENT / "domain" / "models.py",
            COMPONENT / "domain" / "planning.py",
            COMPONENT / "config_flow.py",
        ):
            text = path.read_text(encoding="utf-8")
            assert forbidden_enum not in text, path.as_posix()
            assert f'"{forbidden_value}"' not in text, path.as_posix()
        for path in (
            ROOT / "docs" / "architecture.md",
            ROOT / "docs" / "entity-contract.md",
            ROOT / "docs" / "queue-semantics.md",
            ROOT / "docs" / "ux-specification.md",
        ):
            assert f"`{forbidden_value}`" not in path.read_text(encoding="utf-8"), path.as_posix()

    def test_removed_ui_and_runtime_contract_claims_are_absent(self) -> None:
        forbidden_fragments = (
            "Web" + "Socket",
            "Dashboard " + "Strategy",
            "Dashboard-" + "Strategy",
            "Custom " + "Strategy",
            "Lifecycle-" + "`event`",
            "`event` | " + "Lifecycle",
            "raumbezogenen " + "Entities",
            "Re" + "configure",
            "re" + "configure",
            "Hot-" + "Recovery",
        )
        product_documents = [
            ROOT / "README.md",
            ROOT / "RELEASE_NOTES.md",
            *sorted((ROOT / "docs").rglob("*.md")),
            *sorted((ROOT / "dashboard").rglob("*.md")),
        ]
        for path in product_documents:
            if path.parts[-2:] == ("development", "tdd-evidence.md"):
                continue
            text = path.read_text(encoding="utf-8")
            for forbidden in forbidden_fragments:
                assert forbidden not in text, f"{path.as_posix()}: {forbidden}"

    def test_public_runtime_inventory_has_no_removed_platform_or_api(self) -> None:
        const_source = (COMPONENT / "const.py").read_text(encoding="utf-8")
        init_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        assert 'PLATFORMS = ("sensor", "switch", "binary_sensor", "button")' in const_source
        assert not (COMPONENT / "event.py").exists()
        assert not (COMPONENT / "websocket_api.py").exists()
        assert "websocket_api" not in init_source
        assert "async_register_command" not in init_source

    def test_public_entity_catalog_contains_only_planner_level_entities(self) -> None:
        catalog = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
        assert set(catalog["entity"]) == {"binary_sensor", "button", "sensor", "switch"}
        assert set(catalog["entity"]["binary_sensor"]) == {"attention", "ready"}
        assert set(catalog["entity"]["button"]) == {"cancel_current_block", "start_next"}
        assert set(catalog["entity"]["sensor"]) == {
            "capability_tier",
            "current_phase",
            "next_action",
            "pending_count",
            "queue",
            "status",
        }
        assert set(catalog["entity"]["switch"]) == {"planning"}

    def test_public_due_block_action_is_absent(self) -> None:
        forbidden = "start_" + "due_block"
        public_paths = (
            COMPONENT / "const.py",
            COMPONENT / "services.yaml",
            COMPONENT / "strings.json",
            COMPONENT / "translations" / "de.json",
            COMPONENT / "translations" / "en.json",
            ROOT / "README.md",
            ROOT / "docs" / "architecture.md",
            ROOT / "docs" / "config-flow-and-dashboard.md",
            ROOT / "docs" / "entity-contract.md",
            ROOT / "docs" / "queue-semantics.md",
            ROOT / "docs" / "ux-specification.md",
        )
        for path in public_paths:
            assert forbidden not in path.read_text(encoding="utf-8"), path.as_posix()

    def test_public_event_emission_is_absent(self) -> None:
        source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        assert "_fire_" + "lifecycle_event" not in source
        assert "async_" + "fire(" not in source

    def test_catalogs_have_no_public_enqueue_action(self) -> None:
        forbidden = "enqueue" + "_area"
        for path in (
            COMPONENT / "strings.json",
            COMPONENT / "translations" / "de.json",
            COMPONENT / "translations" / "en.json",
        ):
            catalog = json.loads(path.read_text(encoding="utf-8"))
            assert forbidden not in catalog.get("services", {}), path.as_posix()

    def test_topology_change_surface_is_absent(self) -> None:
        source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        assert "async_step_" + "reconfigure" not in source
        assert "migrate_" + "topology" not in source
        assert not (COMPONENT / ("topology_" + "migration.py")).exists()
        repair_source = (COMPONENT / "repairs.py").read_text(encoding="utf-8")
        assert "RECONFIGURE_" + "ROLLBACK_FAILED" not in repair_source

    def test_options_flow_only_exposes_safe_behavior_options(self) -> None:
        source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        options_class = source.split("class VacuumPlannerOptionsFlow", maxsplit=1)[1].split(
            "class VacuumPlannerConfigFlow", maxsplit=1
        )[0]
        assert "CONF_PLANNING_ENABLED" in options_class
        assert "CONF_DRY_RUN" in options_class
        assert "CONF_VACUUM_ENTITY_ID" not in options_class
        assert "CONF_AREA_IDS" not in options_class
        assert "CONF_AREA_PLANS" not in options_class

    def test_translation_catalogs_have_no_topology_change_ui(self) -> None:
        removed_step = "re" + "configure"
        for path in (
            COMPONENT / "strings.json",
            COMPONENT / "translations" / "de.json",
            COMPONENT / "translations" / "en.json",
        ):
            catalog = json.loads(path.read_text(encoding="utf-8"))
            config = catalog.get("config", {})
            assert removed_step not in config.get("step", {}), path.as_posix()
            assert f"{removed_step}_areas" not in config.get("step", {}), path.as_posix()
            assert f"{removed_step}_rollback_failed" not in catalog.get("issues", {})


if __name__ == "__main__":
    unittest.main()
