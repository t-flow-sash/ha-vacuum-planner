# Universeller Entity-Vertrag

Alle Entities besitzen stabile Unique IDs, `_attr_has_entity_name = True`, übersetzte Namen/Zustände und hängen an **einem Planner-Service-Device pro Config Entry**. Vorhandene Vacuum-Devices, HA-Areas und Queue-Jobs werden nicht dupliziert.

Entity-Zustände sind eine UI-/Automationsprojektion. Plan und Queue werden ausschließlich im versionierten Planner-Store persistiert.

## Planner-Service-Device

| Plattform | Entity | Semantik | Kategorie |
|---|---|---|---|
| `switch` | Planung | automatische Planung aktiv/pausiert | config |
| `sensor` | Status | `idle`, `ready`, `committing`, `running`, `paused`, `attention` | – |
| `sensor` | Nächste Aktion | lesbarer nächster Raum/Modus | – |
| `sensor` | Ausstehende Aufgaben | Anzahl offener Jobs | – |
| `sensor` | Aktuelle Phase | Block-/Jobphase | – |
| `sensor` | Nächster Start | Timestamp | – |
| `sensor` | Capability-Stufe | T0–T3 als UX-Kurzform | diagnostic |
| `binary_sensor` | Bereit | alle Mappings/Capabilities ausführbar | diagnostic |
| `binary_sensor` | Eingriff erforderlich | Repair/uncertain/Mappingproblem | diagnostic |
| `button` | Nächste fällige Aufgabe starten | kanonisches One-Tap über `vacuum_planner.start_next` | – |
| `button` | Aktuellen Block abbrechen | mit sicherer Bestätigungssemantik in UI | – |
| `event` | Lifecycle | normalisierte Block-/Jobereignisse | – |

Selten benötigte Diagnoseentities sind standardmäßig deaktiviert.

## Raumbezogene Entities

Diese Entities referenzieren eine HA-Area, bleiben aber am Planner-Service-Device. Es wird **kein künstliches Raumgerät** erzeugt.

| Plattform | Entity | Pflicht/Regel |
|---|---|---|
| `switch` | Raum im Plan aktiv | ja |
| `binary_sensor` | heute fällig | ja |
| `sensor` | Raumstatus | ja |
| `sensor` | nächste fällige Aufgabe/Zeit | ja |
| `number` | Saugintervall in Tagen | ja |
| `number` | Saugen+Wischen-Intervall | nur mit Capability |
| `number` | Priorität | ja |
| `select` | `automatic`, `vacuum`, `vacuum_and_mop` | Wischoption nur mit Capability |
| `button` | One-Tap fällige Aufgabe | ja |
| `button` | heute überspringen | ja |
| `button` | auf morgen verschieben | soll |
| `button` | Extra-Reinigung anhängen | soll |

`mop_only` ist kein Select-Wert. Wird eine Capability nachträglich verloren, wird die betroffene Entity unavailable/ausgeblendet und ein Repair erzeugt; ein Plan wird nicht still degradiert.

## Entity-Attribute

Attribute bleiben klein, stabil und recorderfreundlich. Beispiele:

```yaml
# sensor.<instance>_status
active_block_id: "2f3f..."
guarantee: planner_atomic
dispatch_strategy: native_batch
robot_lane_count: 1

# sensor.<instance>_next_action
area_id: kitchen
mode: vacuum_and_mop
due_at: "2026-09-16T08:00:00+02:00"
```

Keine vollständige Queue, History oder Mappingmatrix als dauerhaftes State-Attribut. Detaillierte Queue-Daten kommen über eine read-only Response-Action bzw. validierte WebSocket-API.

## Actions

| Action | Zweck | zentrale Felder |
|---|---|---|
| `start_next` | kanonische öffentliche One-Tap-Action; startet die nächste fällige Aufgabe | Planner-Ziel |
| `start_due_block` | technische Block-Action; fälligen Snapshot versiegeln und committen | Planner-Ziel, optional Idempotency-Key |
| `enqueue_area` | Area hinten anhängen | Planner-Ziel, `area_id`, Modus, Wiederholung bestätigen |
| `skip_area_today` | aktuelle Tagesfälligkeit überspringen | Planner-Ziel, `area_id` |
| `postpone_area` | Fälligkeit verschieben | Planner-Ziel, `area_id`, Datum/Tage |
| `cancel_block` | laufenden/offenen Block abbrechen | Planner-Ziel, `block_id` |
| `resolve_uncertain_run` | Recoveryentscheidung | Planner-Ziel, Run/Job, explizite Auflösung |
| `get_queue` | read-only Queue-Response | Planner-Ziel, optional Zeitraum |

Actions adressieren niemals implizit „den ersten Planner“. Öffentliche Felder verwenden HA-Area-IDs, nie rohe Segment-IDs. Mutationen laufen immer durch denselben Coordinator/Lock.

Buttons, Dashboard und normale Automationen verwenden für One-Tap ausschließlich `vacuum_planner.start_next`. `vacuum_planner.start_due_block` bleibt der internen bzw. fortgeschrittenen Blocksteuerung vorbehalten und ist kein Synonym für One-Tap.

## `get_queue`-Response (Beispiel)

```yaml
revision: 42
block:
  block_id: "2f3f..."
  state: running
  guarantee: planner_atomic
  jobs:
    - job_id: "8a12..."
      area_id: kitchen
      area_name: Küche
      mode: vacuum_and_mop
      state: completed
      position: 1
    - job_id: "19bc..."
      area_id: hallway
      area_name: Flur
      mode: vacuum
      state: running
      position: 2
appended_jobs: []
```

## Events

- `block_sealed`
- `block_committed`
- `block_completed`
- `job_started`
- `job_completed`
- `job_failed`
- `run_uncertain`

Events enthalten Planner-/Block-/Job-ID, Area-ID, normalisierten Modus und Ergebnis. Keine Credentials, Segment-IDs oder unredigierten Adapterpayloads.

## Dashboard-Vertrag

Das Standarddashboard liest ausschließlich diese Entities/Actions und die Queue-Response. Akku/Dockzustand kann bewusst über die im Config Entry gewählte Standard-`vacuum.*`-Entity angezeigt werden; herstellerspezifische Sensoren sind nicht Teil des Contracts.

Der Entity-Vertrag bleibt über Minor-Releases additiv. Umbenennungen oder Zustandsänderungen erfordern Migration und dokumentierte Deprecation.
