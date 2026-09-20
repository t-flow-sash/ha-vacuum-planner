"""Release-candidate documentation and universal dashboard contracts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "dashboard"
REQUIRED_RELEASE_FILES = (
    ROOT / "CHANGELOG.md",
    ROOT / "LICENSE",
    ROOT / "RELEASE_NOTES.md",
    ROOT / "docs" / "installation.md",
    ROOT / "docs" / "rollback.md",
    ROOT / "docs" / "limitations.md",
    ROOT / "docs" / "beta-scope.md",
    DASHBOARD / "README.md",
    DASHBOARD / "vacuum-planner.yaml",
    DASHBOARD / "mock-states.json",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_candidate_has_all_required_documents() -> None:
    assert all(path.is_file() for path in REQUIRED_RELEASE_FILES)


def test_local_markdown_links_resolve() -> None:
    missing: list[str] = []
    for document in sorted(ROOT.rglob("*.md")):
        if any(part in {".git", ".venv"} for part in document.parts):
            continue
        for raw_target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", _text(document)):
            target = raw_target.strip().split()[0].strip("<>")
            parsed = urlparse(target)
            if parsed.scheme or target.startswith(("#", "mailto:")):
                continue
            relative_path = unquote(target.split("#", maxsplit=1)[0])
            if relative_path and not (document.parent / relative_path).resolve().exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    assert missing == []


def test_installation_is_honest_for_private_beta_and_ui_only() -> None:
    installation = _text(ROOT / "docs" / "installation.md").lower()
    readme = _text(ROOT / "README.md").lower()
    assert "authentifiziert" in installation
    assert "v0.1.0-beta.2" in installation
    assert "release-zip" in installation
    assert "privat" in installation
    assert "hacs" in installation
    assert "öffentlich erreichbar" in installation
    assert "wheel" not in installation
    assert "wheel" not in readme
    assert "einstellungen" in installation
    assert "geräte & dienste" in installation
    assert "keine yaml-konfiguration" in installation
    assert "dry-run" in installation


def test_rollback_requires_backup_and_stopped_home_assistant_for_store_edits() -> None:
    rollback = _text(ROOT / "docs" / "rollback.md").lower()
    assert "backup" in rollback
    assert "downgrade" in rollback
    assert "entfernen" in rollback
    assert "home assistant vollständig stoppen" in rollback
    assert "niemals automatisch" in rollback
    assert ".storage" in rollback
    assert "zukünftige öffentliche veröffentlichung" in rollback
    assert "private copy-/release-zip-installation" in rollback


def test_license_file_records_blocker_without_claiming_mit() -> None:
    pyproject = _text(ROOT / "pyproject.toml").lower()
    license_text = _text(ROOT / "LICENSE").lower()
    assert "license" not in pyproject
    assert "keine open-source-lizenz" in license_text
    assert "mit license" not in license_text


def test_dashboard_artifacts_are_parseable_and_vendor_neutral() -> None:
    dashboard = yaml.safe_load(_text(DASHBOARD / "vacuum-planner.yaml"))
    mock_states = json.loads(_text(DASHBOARD / "mock-states.json"))

    assert isinstance(dashboard, dict)
    assert isinstance(mock_states, dict)

    dashboard_text = "\n".join(
        _text(path) for path in DASHBOARD.rglob("*") if path.is_file()
    ).lower()
    forbidden_vendors = ("dreame", "mova", "roborock", "eufy", "xiaomi", "ecovacs")
    assert not any(vendor in dashboard_text for vendor in forbidden_vendors)
    assert "vacuum." not in dashboard_text
    assert re.search(r"\bsegment(?:_id)?\s*[:=]\s*[0-9]+", dashboard_text) is None


def test_importable_dashboard_uses_only_standard_cards_and_sections() -> None:
    dashboard = yaml.safe_load(_text(DASHBOARD / "vacuum-planner.yaml"))

    assert dashboard["views"]
    view = dashboard["views"][0]
    assert view["type"] == "sections"
    assert view["sections"]
    serialized = _text(DASHBOARD / "vacuum-planner.yaml")
    assert "custom:" not in serialized
    assert "sensor.vacuum_planner_queue" in serialized
    assert "state_attr('sensor.vacuum_planner_queue', 'items')" in serialized


def test_dashboard_uses_native_planner_numbers_without_external_helpers() -> None:
    dashboard = _text(DASHBOARD / "vacuum-planner.yaml").lower()
    dashboard_readme = _text(DASHBOARD / "README.md").lower()
    entity_contract = _text(ROOT / "docs" / "entity-contract.md").lower()

    assert "input_number" not in dashboard
    assert "input_number" in dashboard_readme
    assert "keine externen helper" in dashboard_readme
    assert "`number`" in entity_contract
    assert "saugintervall" in entity_contract
    assert "saugen+wischen-intervall" in entity_contract
    assert "priorität" in entity_contract
    assert "persist-before-publish" in entity_contract


def test_dashboard_completed_rows_are_grey_labeled_and_controls_are_large() -> None:
    dashboard = yaml.safe_load(_text(DASHBOARD / "vacuum-planner.yaml"))
    serialized = _text(DASHBOARD / "vacuum-planner.yaml")
    cards = [card for section in dashboard["views"][0]["sections"] for card in section["cards"]]
    controls = [card for card in cards if card["type"] in {"button", "tile"}]

    assert "--disabled-text-color" in serialized
    assert "Erledigt" in serialized
    assert "✓" in serialized
    assert controls
    assert all(card.get("grid_options", {}).get("rows", 0) >= 2 for card in controls)
    assert "48 px" in _text(DASHBOARD / "README.md")


def test_dashboard_button_entities_use_button_press_action_contract() -> None:
    dashboard = yaml.safe_load(_text(DASHBOARD / "vacuum-planner.yaml"))
    cards = [card for section in dashboard["views"][0]["sections"] for card in section["cards"]]
    buttons = [card for card in cards if card.get("type") == "button"]

    assert len(buttons) == 2
    for card in buttons:
        assert card["tap_action"] == {
            "action": "perform-action",
            "perform_action": "button.press",
            "target": {"entity_id": card["entity"]},
        }


def test_release_candidate_version_and_status_are_consistent() -> None:
    manifest = json.loads(_text(ROOT / "custom_components" / "vacuum_planner" / "manifest.json"))
    release_notes = _text(ROOT / "RELEASE_NOTES.md").lower()
    changelog = _text(ROOT / "CHANGELOG.md").lower()

    assert manifest["version"] == "0.1.0-beta.2"
    assert "v0.1.0-beta.2" in release_notes
    assert "release-kandidat" in release_notes
    assert "kein tag" in release_notes
    assert "v0.1.0-beta.2" in changelog
    assert "kandidat" in changelog


def test_release_zip_builder_is_reproducible_and_has_expected_layout(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "build_release.py"
    first = tmp_path / "first"
    second = tmp_path / "second"
    command = [sys.executable, str(script), "--version", "0.1.0-beta.2"]

    subprocess.run([*command, "--output-dir", str(first)], cwd=ROOT, check=True)  # noqa: S603
    subprocess.run([*command, "--output-dir", str(second)], cwd=ROOT, check=True)  # noqa: S603

    archive_name = "vacuum_planner-v0.1.0-beta.2.zip"
    first_zip = first / archive_name
    second_zip = second / archive_name
    assert first_zip.read_bytes() == second_zip.read_bytes()
    digest = sha256(first_zip.read_bytes()).hexdigest()
    assert _text(first / "SHA256SUMS") == f"{digest}  {archive_name}\n"
    assert _text(first / "SHA256SUMS") == _text(second / "SHA256SUMS")
    with zipfile.ZipFile(first_zip) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert names == sorted(names)
        assert names
        assert all(name.startswith("custom_components/vacuum_planner/") for name in names)
        assert "custom_components/vacuum_planner/manifest.json" in names
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        component = "custom_components/vacuum_planner/"
        assert not any(
            name in names
            for name in (
                f"{component}event.py",
                f"{component}topology_migration.py",
                f"{component}websocket_api.py",
            )
        )
        const_source = archive.read(f"{component}const.py").decode()
        services = archive.read(f"{component}services.yaml").decode()
        models = archive.read(f"{component}domain/models.py").decode()
        init_source = archive.read(f"{component}__init__.py").decode()
        config_flow = archive.read(f"{component}config_flow.py").decode()
        assert "SERVICE_START_" + "DUE_BLOCK" not in const_source
        assert "start_" + "due_block:" not in services
        assert "AD" + "HOC =" not in models
        assert "AUTO" + "MATIC =" not in models
        assert "async_" + "fire(" not in init_source
        assert "async_register_" + "command" not in init_source
        assert "async_step_" + "reconfigure" not in config_flow
