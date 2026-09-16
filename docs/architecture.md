# Zielarchitektur

## Entscheidung in einem Satz

HA Vacuum Planner wird eine **Custom Integration**, die Home Assistants native `vacuum.clean_area`- und Area-Zuordnung als bevorzugten Transport nutzt, darüber einen persistenten Planner-/Queue-Ledger legt und optionale Herstelleradapter ausschließlich für fehlende oder zusätzliche Fähigkeiten verwendet.

## Komponenten

```text
Config Flow / Options Flow
          │
          ▼
  Planner Coordinator ───────────────► Entity Contract / Events / Services
          │
          ├── Domain Core
          │     ├── Plan & due calculation
          │     ├── immutable block snapshots
          │     ├── queue state machine
          │     └── recovery / idempotency
          │
          ├── Persistent Store
          │     └── versioned plans, jobs, history, revisions
          │
          └── Execution Adapter
                ├── NativeAreaAdapter → vacuum.clean_area
                ├── GenericVacuumAdapter → whole-home fallback
                └── Vendor capability extensions

Frontend / Dashboard
          └── consumes only the universal entity and event contract
```

## Schicht 1 — Domain Core

Der Core ist reines Python und kennt weder Entity-IDs noch Herstellerdienste. Eingaben sind normalisierte Plan-, Area-, Capability- und Laufzeitdaten. Ausgaben sind geplante Zustandsübergänge und Adapterkommandos.

Verantwortung:

- Fälligkeit und Priorität
- unveränderliche Tages-Snapshots
- Block-/Job-Zustandsautomat
- Append-/Dedup-Regeln
- Recovery-Entscheidungen
- Historienaktualisierung erst nach bestätigtem Abschluss

## Schicht 2 — Home-Assistant-Grenze

Der Coordinator übersetzt zwischen HA und Domain Core.

- beobachtet die ausgewählte `vacuum.*`-Entität
- liest Entity Registry und native `vacuum.area_mapping`-Optionen
- serialisiert Queue-Mutationen je Config Entry
- ruft HA-Services mit blockierendem Fehlerpfad auf
- publiziert Entities, Events und Services
- verwaltet Repairs, Reconfigure und Diagnostics

## Schicht 3 — Ausführungsadapter

### NativeAreaAdapter

Standardpfad für Geräte mit `VacuumEntityFeature.CLEAN_AREA` und vollständiger Segment→Area-Zuordnung.

- erhält geordnete HA-`area_id`-Listen
- ruft `vacuum.clean_area` einmal pro Block oder einmal pro Raum auf, abhängig vom benötigten Fortschritts-/Recovery-Tier
- kennt keine rohen Segment-IDs

### GenericVacuumAdapter

Fallback für Geräte ohne Area Cleaning.

- kann nur Ganzflächenreinigung starten
- bildet mehrere geplante Areas nicht fälschlich als einzeln bestätigte Räume ab
- zeigt die Einschränkung bereits im Onboarding

### Vendor Extensions

Optionale Erweiterungen kapseln ausschließlich Fähigkeiten, die HA noch nicht standardisiert:

- Reinigungsmodus sicher setzen
- geordnete native Mehrraum-/Queue-Aufträge
- Raumfortschritt und Run-Korrelation
- robuste Abschlussdaten
- native Queue nachträglich erweitern

Adapter dürfen weder Planner-Persistenz schreiben noch UI-spezifische Zustände besitzen.

## Capability-Tiers

| Tier | Mindestfähigkeit | Verhalten |
|---|---|---|
| 0 | Standard-`vacuum.start` | Ganzfläche; keine raumgenaue Planungsausführung |
| 1 | `vacuum.clean_area` + vollständiges Mapping | geordnete Area-Reinigung über HA-native API |
| 2 | Tier 1 + Modussteuerung | Saugen bzw. Saugen+Wischen zuverlässig pro Job/Block |
| 3 | Tier 2 + Raum-/Run-Telemetrie | bestätigter Fortschritt und genaue Historie |
| 4 | Tier 3 + erweiterbare native Queue | echter Geräte-Queue-Block plus nachträgliches Append |

Wichtig: Der Planner garantiert auf allen Tiers die **logische** Blockreihenfolge in seinem Ledger. Nur Tier 4 darf behaupten, dass dieselbe Semantik auch als native Gerätequeue atomar umgesetzt wurde.

## Persistenz

- HA `Store` unter einem versionierten Schlüssel pro Config Entry
- atomare Speicherung nach jeder Queue-Mutation
- Schema-Migrationen für zukünftige Versionen
- kein Speichern von Herstellerzugangsdaten
- keine rohe Entity-State-Kopie als Datenmodell

Persistiert werden:

- Planrevisionen und Area-Konfiguration
- aktuelle Blöcke und Jobs
- letzte bestätigte erfolgreiche Reinigung je Area/Modus
- Idempotency-/Run-Korrelation
- minimale, begrenzte Historie für Diagnose und Migration

## Nebenläufigkeit

- genau ein Queue-Lock je Config Entry
- keine direkte Mutation aus Entity-Callbacks
- alle UI-, Service-, Timer- und Adapterereignisse laufen über Coordinator-Kommandos
- externe Roboterbedienung erzeugt, wenn erkennbar, `external_interference` statt stiller Fortschrittsannahmen
- mehrere Roboter/config entries dürfen unabhängig parallel laufen

## Onboarding-Gates

1. `vacuum.*` wählen.
2. unterstützte Features ermitteln.
3. falls `CLEAN_AREA`: gemeldete Segmente und `area_mapping` lesen.
4. unvollständige Zuordnung blockiert die raumgenaue Einrichtung mit Link/Anleitung zu „Map vacuum segments to areas“.
5. gewünschte Areas wählen und Planregeln setzen.
6. Capability-Tier und Einschränkungen vor Abschluss bestätigen.
7. universelle Entities anlegen; keine Helper-Flut erzeugen.

## Dashboard-Bereitstellung

Die Dashboard-Entscheidung muss unterstützte HA-Schnittstellen respektieren. Präferenzreihenfolge:

1. gebündelte Frontend-/Sidebar-Ansicht, wenn über stabile öffentliche APIs wartbar;
2. Lovelace Strategy bzw. eine mitgelieferte Planner-Card, die Entities dynamisch entdeckt;
3. generiertes YAML als dokumentierter Fallback.

Nicht zulässig ist das unkontrollierte Bearbeiten privater `.storage`-Dateien. Das Dashboard darf ausschließlich den universellen Entity-Vertrag konsumieren.

## Erweiterungspunkte

- Planner-Events für Anwesenheit, Energiepreis oder Nachtmodus
- optionale Automations-Blueprints als Trigger-/Policy-Schicht
- neue Adapter über Contract-Tests
- Importer für bestehende YAML-/Helper-Installationen
