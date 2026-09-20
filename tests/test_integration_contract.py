import json
import struct
from pathlib import Path
from typing import cast

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "vacuum_planner"
REPOSITORY_ROOT = INTEGRATION_DIR.parents[1]


def load_json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_manifest_declares_installable_config_flow_integration() -> None:
    manifest = load_json(INTEGRATION_DIR / "manifest.json")

    assert manifest == {
        "codeowners": ["@t-flow-sash"],
        "config_flow": True,
        "documentation": "https://github.com/t-flow-sash/ha-vacuum-planner",
        "domain": "vacuum_planner",
        "integration_type": "service",
        "iot_class": "calculated",
        "issue_tracker": "https://github.com/t-flow-sash/ha-vacuum-planner/issues",
        "name": "Vacuum Planner",
        "version": "0.1.0-beta.1",
    }


def test_hacs_metadata_identifies_an_integration_repository() -> None:
    hacs = load_json(REPOSITORY_ROOT / "hacs.json")

    assert hacs["name"] == "Vacuum Planner"
    assert hacs["render_readme"] is True
    assert hacs["homeassistant"] == "2026.3.1"


def test_hacs_brand_icon_is_a_256_pixel_png() -> None:
    icon = INTEGRATION_DIR / "brand" / "icon.png"
    content = icon.read_bytes()

    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", content[16:24])
    assert (width, height) == (256, 256)


def test_public_actions_have_ui_descriptions_and_config_entry_selectors() -> None:
    services = (INTEGRATION_DIR / "services.yaml").read_text(encoding="utf-8")

    expected_actions = {
        "cancel_block",
        "get_queue",
        "postpone_area",
        "resolve_uncertain_run",
        "skip_area_today",
        "start_next",
    }
    declared_actions = {
        line.removesuffix(":")
        for line in services.splitlines()
        if line and not line.startswith(" ") and line.endswith(":")
    }
    assert declared_actions == expected_actions
    assert services.count("config_entry_id:") == len(expected_actions)
    assert services.count("integration: vacuum_planner") == 1
    assert services.count("*planner_entry") == len(expected_actions) - 1


def translation_keys(value: object, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix}
    return {
        key
        for name, child in value.items()
        for key in translation_keys(child, f"{prefix}.{name}" if prefix else name)
    }


def test_config_flow_has_complete_english_and_german_translations() -> None:
    strings = load_json(INTEGRATION_DIR / "strings.json")
    english = load_json(INTEGRATION_DIR / "translations" / "en.json")
    german = load_json(INTEGRATION_DIR / "translations" / "de.json")

    expected_keys = {
        "config.abort.already_configured",
        "config.abort.invalid_flow_state",
        "config.error.areas_duplicate",
        "config.error.areas_not_mapped",
        "config.error.areas_required",
        "config.error.clean_area_unsupported",
        "config.error.entity_not_found",
        "config.step.areas.data.area_ids",
        "config.step.areas.description",
        "config.step.areas.title",
        "config.step.user.data.vacuum_entity_id",
        "config.step.user.description",
        "config.step.user.title",
        "entity.sensor.status.name",
        "entity.sensor.status.state.attention",
        "entity.sensor.status.state.committing",
        "entity.sensor.status.state.idle",
        "entity.sensor.status.state.paused",
        "entity.sensor.status.state.ready",
        "entity.sensor.status.state.running",
        "entity.binary_sensor.attention.name",
        "entity.binary_sensor.ready.name",
        "entity.button.cancel_current_block.name",
        "entity.button.start_next.name",
        "entity.sensor.capability_tier.name",
        "entity.sensor.current_phase.name",
        "entity.sensor.next_action.name",
        "entity.sensor.pending_count.name",
        "entity.sensor.queue.name",
        "entity.switch.planning.name",
        "issues.corrupt_store.description",
        "issues.corrupt_store.title",
        "issues.future_store.description",
        "issues.future_store.title",
        "issues.lost_capability.fix_flow.abort.reload_or_recreate_required",
        "issues.lost_capability.fix_flow.step.init.description",
        "issues.lost_capability.fix_flow.step.init.title",
        "issues.lost_capability.title",
        "issues.missing_mapping.fix_flow.abort.reload_or_recreate_required",
        "issues.missing_mapping.fix_flow.step.init.description",
        "issues.missing_mapping.fix_flow.step.init.title",
        "issues.missing_mapping.title",
        "issues.missing_registry.fix_flow.abort.reload_or_recreate_required",
        "issues.missing_registry.fix_flow.step.init.description",
        "issues.missing_registry.fix_flow.step.init.title",
        "issues.missing_registry.title",
        "issues.removed_areas.fix_flow.abort.reload_or_recreate_required",
        "issues.removed_areas.fix_flow.step.init.description",
        "issues.removed_areas.fix_flow.step.init.title",
        "issues.removed_areas.title",
        "issues.unresolved_external_run.description",
        "issues.unresolved_external_run.title",
        "options.step.init.data.dry_run",
        "options.step.init.data.planning_enabled",
        "options.step.init.description",
        "options.step.init.title",
        "services.cancel_block.description",
        "services.cancel_block.fields.block_id.description",
        "services.cancel_block.fields.block_id.name",
        "services.cancel_block.fields.config_entry_id.description",
        "services.cancel_block.fields.config_entry_id.name",
        "services.cancel_block.name",
        "services.get_queue.description",
        "services.get_queue.fields.config_entry_id.description",
        "services.get_queue.fields.config_entry_id.name",
        "services.get_queue.name",
        "services.postpone_area.description",
        "services.postpone_area.fields.area_id.description",
        "services.postpone_area.fields.area_id.name",
        "services.postpone_area.fields.config_entry_id.description",
        "services.postpone_area.fields.config_entry_id.name",
        "services.postpone_area.fields.days.description",
        "services.postpone_area.fields.days.name",
        "services.postpone_area.name",
        "services.resolve_uncertain_run.description",
        "services.resolve_uncertain_run.fields.config_entry_id.description",
        "services.resolve_uncertain_run.fields.config_entry_id.name",
        "services.resolve_uncertain_run.fields.job_id.description",
        "services.resolve_uncertain_run.fields.job_id.name",
        "services.resolve_uncertain_run.fields.resolution.description",
        "services.resolve_uncertain_run.fields.resolution.name",
        "services.resolve_uncertain_run.name",
        "services.skip_area_today.description",
        "services.skip_area_today.fields.area_id.description",
        "services.skip_area_today.fields.area_id.name",
        "services.skip_area_today.fields.config_entry_id.description",
        "services.skip_area_today.fields.config_entry_id.name",
        "services.skip_area_today.name",
        "services.start_next.description",
        "services.start_next.fields.config_entry_id.description",
        "services.start_next.fields.config_entry_id.name",
        "services.start_next.name",
    }
    assert translation_keys(strings) == expected_keys
    assert english == strings
    assert translation_keys(german) == expected_keys
    assert german != english
