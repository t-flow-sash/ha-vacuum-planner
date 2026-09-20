# HA Vacuum Planner

Herstellerneutraler, raumbasierter Planer für vorhandene Home-Assistant-Sauger – mit UI-Einrichtung, persistenter Queue und sicherem Dry-run als Standard.

> **Projektstatus: privater Release-Kandidat `v0.1.0-beta.2`.** Der primäre Installationsweg ist das authentifiziert bezogene, semantisch versionierte Release-ZIP mit SHA-256-Prüfung und anschließender Ordnerkopie. Das private Repository ist nicht über HACS installierbar; HACS kommt nur nach einer späteren öffentlichen Erreichbarkeit und ausdrücklichen Freigabe infrage. Es gibt noch keinen Tag oder Release. Der Config Flow wurde auf Home Assistant 2026.9.3 in einem beaufsichtigten Pilot erfolgreich bis zur Raumplanung geprüft; reale Reinigungsbefehle und unbeaufsichtigter Betrieb sind weiterhin nicht freigegeben. Dry-run bleibt Standard.

## Was der Beta-Kandidat liefert

- Config- und sichere Verhaltens-Options-Flows ohne YAML-Konfiguration
- Home-Assistant-Areas als öffentliche Raumidentität
- persistente, versionierte Plan-/Queue-Daten
- standardisierte Planner-Entities und Actions
- One-Tap über `vacuum_planner.start_next`
- Recovery-Zustand `uncertain` statt blindem Wiederholen
- Diagnostics und Repairs mit redigierten Daten
- importierbares Sections-Dashboard aus Standardkarten mit dynamischer, begrenzter Queue-Projektion unter [`dashboard/`](dashboard/README.md)

Die sichtbare Queue enthält nur geplante Räume. Erledigte Räume bleiben im Tageskontext sichtbar und können grau/dezent dargestellt werden. Unterstützte Modi sind Saugen und Saugen+Wischen – niemals ausschließlich Wischen.

## Sicherheitsgrenze der Beta

- **Dry-run ist standardmäßig aktiv.** Das Ausschalten kann reale Reinigungsbefehle auslösen.
- Shadow-/Dry-run-Validierung ist erlaubt; **Live-Steuerung ist noch nicht freigegeben**.
- Ein erfolgreicher Dispatch ist kein Beleg für eine abgeschlossene Reinigung.
- Bestehende Lovelace-Dashboards und interne Lovelace-Storage-Dateien werden nicht verändert.
- Vor Update, Downgrade oder Entfernung ist ein Home-Assistant-Backup erforderlich.

Siehe [Beta-Umfang](docs/beta-scope.md), [bekannte Grenzen](docs/limitations.md) und [Rollback](docs/rollback.md).

## Installation und Einrichtung

1. Nach [Installationsanleitung](docs/installation.md) das private Release-ZIP authentifiziert beziehen, SHA-256 prüfen und `custom_components/vacuum_planner` kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Vacuum Planner** öffnen.
4. Vorhandenen Sauger und die zu planenden Home-Assistant-Räume auswählen.
5. Dry-run aktiviert lassen und zunächst nur Zustände, Queue und Actions prüfen.
6. Optional die vollständige Standardkarten-Konfiguration nach der [Dashboard-Anleitung](dashboard/README.md) importieren.

Es sind weder `configuration.yaml` noch Packages, externe `input_number`-Helper, Helper-YAML oder Automations-YAML erforderlich. Raumbezogene Intervalle und Prioritäten stellt die Integration als native, übersetzte Number-Entitäten bereit.

## Dokumentation

### Betrieb und Release

- [Installation](docs/installation.md)
- [Beta-Umfang](docs/beta-scope.md)
- [Bekannte Grenzen](docs/limitations.md)
- [Rollback und Entfernung](docs/rollback.md)
- [Release Notes](RELEASE_NOTES.md)
- [Changelog](CHANGELOG.md)
- [Lizenzstatus](LICENSE)
- [Dashboard-Artefakt](dashboard/README.md)

### Verträge und Architektur

- [Produktanforderungen](docs/requirements.md)
- [Anforderungs-Nachverfolgung](docs/requirements-traceability.md)
- [Bekannter Ausgangszustand](docs/current-state.md)
- [Architekturentscheidung](docs/adr/0001-solution-shape.md) *(Accepted)*
- [Zielarchitektur und Implementierungsstatus](docs/architecture.md)
- [Config Flow und Dashboard-Bereitstellung](docs/config-flow-and-dashboard.md)
- [Queue- und Block-Semantik](docs/queue-semantics.md)
- [Universeller Entity-Vertrag](docs/entity-contract.md)
- [Capability- und Adaptermodell](docs/capabilities.md)
- [Hersteller-/Integrationsmatrix](docs/compatibility.md)
- [UX-Spezifikation](docs/ux-specification.md)
- [Roadmap](docs/roadmap.md)

## Entwicklung

```bash
python -m pytest -q
ruff check .
mypy . --strict
bandit -q -r custom_components/vacuum_planner
python -m compileall -q custom_components tests
```

Die dokumentierten RED-/GREEN-Läufe stehen unter [TDD evidence](docs/development/tdd-evidence.md). `v0.1.0-beta.2` bezeichnet hier den unveröffentlichten Kandidaten; es werden kein Tag und kein GitHub-Release angelegt.

## Lizenz

Vacuum Planner wird unter der [MIT-Lizenz](LICENSE) veröffentlicht.
