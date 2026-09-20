# Universeller Entity-Vertrag

Alle Entities besitzen stabile Unique IDs, `_attr_has_entity_name = True`, übersetzte Namen/Zustände und hängen an **einem Planner-Service-Device pro Config Entry**. Vorhandene Vacuum-Devices, HA-Areas und Queue-Jobs werden nicht dupliziert.

Entity-Zustände sind eine UI-/Automationsprojektion. Plan und Queue werden ausschließlich im versionierten Planner-Store persistiert.

## Planner-Service-Device

| Plattform | Entity | Semantik | Kategorie |
|---|---|---|---|
| `switch` | Planung | automatische Planung aktiv/pausiert | config |
| `number` | Saugintervall `<Raum>` | autoritatives Saugintervall, 1–365 Tage, Schritt 1 | config |
| `number` | Saugen+Wischen-Intervall `<Raum>` | autoritatives Kombiintervall, 1–365 Tage, Schritt 1 | config |
| `number` | Priorität `<Raum>` | autoritative Planungspriorität, Ganzzahl ab 0 | config |
| `sensor` | Status | `idle`, `ready`, `committing`, `running`, `paused`, `attention` | – |
| `sensor` | Nächste Aktion | lesbarer nächster Raum/Modus | – |
| `sensor` | Ausstehende Aufgaben | Anzahl offener Jobs | – |
| `sensor` | Aktuelle Phase | Block-/Jobphase | – |
| `sensor` | Capability-Stufe | T0–T3 als UX-Kurzform | diagnostic |
| `sensor` | Queue | Gesamtzahl der Jobs; begrenzte sichere Projektion in den Attributen | – |
| `binary_sensor` | Bereit | alle Mappings/Capabilities ausführbar | diagnostic |
| `binary_sensor` | Eingriff erforderlich | Repair/uncertain/Mappingproblem | diagnostic |
| `button` | Nächste fällige Aufgabe starten | kanonisches One-Tap über `vacuum_planner.start_next` | – |
| `button` | Aktuellen Block abbrechen | mit sicherer Bestätigungssemantik in UI | – |


Selten benötigte Diagnoseentities sind standardmäßig deaktiviert.

Für jeden konfigurierten Raum stellt die Integration genau diese drei nativen
`number`-Entitäten selbst bereit. Es werden keine externen `input_number`-Helper und kein
YAML-Package erzeugt oder benötigt. Ihre Werte sind direkte Projektionen der autoritativen
`PlannerState.plan_revision`. Jeder Schreibzugriff erzeugt eine vollständige neue
`PlanRevision`, läuft unter demselben Coordinator-Lock wie Actions und Worker und folgt
**persist-before-publish**: Erst nach erfolgreichem Speichern werden Runtime und Entities
aktualisiert. Bei einem Speicherfehler bleiben Revision und sichtbare Werte unverändert.

## Entity-Attribute

Attribute bleiben klein, stabil und recorderfreundlich. Der Status-Sensor liefert keine zusätzlichen State-Attribute. Der Sensor „Nächste Aktion“ liefert ausschließlich:

```yaml
# sensor.<instance>_next_action
area_id: kitchen
area_name: Küche
mode: vacuum_and_mop
due_at: "2026-09-16T08:00:00+02:00"
```

Der Queue-Sensor liefert als Zustand die Gesamtzahl der Jobs. Seine Attribute sind
`items`, `projected_count`, `revision`, `total_count` und `truncated`; jede Zeile in
`items` enthält nur `area_name`, `mode`, `position` und `status`. Die Projektion ist auf
20 sichere Zeilen begrenzt. Vollständige read-only Queue-Daten kommen ausschließlich
über die Response-Action `get_queue`; History und Mappingmatrix werden nicht als
dauerhafte State-Attribute veröffentlicht.

## Actions

| Action | Zweck | zentrale Felder |
|---|---|---|
| `start_next` | kanonische öffentliche One-Tap-Action; materialisiert und startet genau eine nächste fällige Aufgabe | Planner-Ziel |

| `skip_area_today` | aktuelle Tagesfälligkeit überspringen | Planner-Ziel, `area_id` |
| `postpone_area` | Fälligkeit verschieben | Planner-Ziel, `area_id`, Datum/Tage |
| `cancel_block` | nur `sealed` mit ausschließlich `pending`-Jobs sicher abbrechen | Planner-Ziel, `block_id` |
| `resolve_uncertain_run` | Recoveryentscheidung | Planner-Ziel, Run/Job, explizite Auflösung |
| `get_queue` | read-only Queue-Response | Planner-Ziel |

Actions adressieren niemals implizit „den ersten Planner“. Öffentliche Felder verwenden HA-Area-IDs, nie rohe Segment-IDs. Mutationen laufen immer durch denselben Coordinator/Lock.

`cancel_block` ist bewusst eng begrenzt: Sobald ein Block oder Job möglicherweise externe Arbeit ausgelöst hat, wird die Action abgelehnt. Eine Adapter-Cancel-Bestätigung ist nicht implementiert; laufende, bestätigte oder unsichere externe Arbeit wird daher nicht als erfolgreich abgebrochen dargestellt.

Buttons, Dashboard und normale Automationen verwenden für One-Tap ausschließlich `vacuum_planner.start_next`.

## `get_queue`-Response (Beispiel)

```yaml
revision: 42
blocks:
  - block_id: "2f3f..."
    kind: scheduled
    state: running
    guarantee: planner_atomic
    job_ids: ["8a12..."]
jobs:
  - job_id: "8a12..."
    block_id: "2f3f..."
    area_id: kitchen
    area_name: Küche
    mode: vacuum_and_mop
    state: running
    position: 0
```

## Statusquelle

Entities und der persistente Store sind die alleinigen Statusquellen der Beta.

## Dashboard-Vertrag

Das Standarddashboard liest ausschließlich diese Entities/Actions und die Queue-Response. Akku/Dockzustand kann bewusst über die im Config Entry gewählte Standard-`vacuum.*`-Entity angezeigt werden; herstellerspezifische Sensoren sind nicht Teil des Contracts.

Der Entity-Vertrag bleibt über Minor-Releases additiv. Umbenennungen oder Zustandsänderungen erfordern Migration und dokumentierte Deprecation.
