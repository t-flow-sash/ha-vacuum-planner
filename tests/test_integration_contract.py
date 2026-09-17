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
        "version": "0.1.0",
    }


def test_hacs_metadata_identifies_an_integration_repository() -> None:
    hacs = load_json(REPOSITORY_ROOT / "hacs.json")

    assert hacs["name"] == "Vacuum Planner"
    assert hacs["render_readme"] is True


def test_hacs_brand_icon_is_a_256_pixel_png() -> None:
    icon = INTEGRATION_DIR / "brand" / "icon.png"
    content = icon.read_bytes()

    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", content[16:24])
    assert (width, height) == (256, 256)


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
        "config.error.entity_not_found",
        "config.step.user.data.vacuum_entity_id",
        "config.step.user.description",
        "config.step.user.title",
    }
    assert translation_keys(strings) == expected_keys
    assert english == strings
    assert translation_keys(german) == expected_keys
    assert german != english
