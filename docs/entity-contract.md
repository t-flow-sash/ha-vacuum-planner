# Universeller Entity-Vertrag

> Entwurf – wird gegen Architektur- und UX-Review geprüft.

Alle Entity-IDs entstehen aus einer Config Entry und stabilen Unique IDs. Das Dashboard referenziert keine Herstellerentitäten direkt.

## Planner-Gerät

| Plattform | Semantik | Pflicht |
|---|---|---|
| `switch` | Planner aktiv/pausiert | ja |
| `sensor` | Planner-Zustand | ja |
| `sensor` | nächste Aktion | ja |
| `sensor` | heutige Queue, Details als strukturierte Attribute | ja |
| `sensor` | Capability-Tier und erkannte Fähigkeiten | ja |
| `button` | fälligen Tagesblock starten | ja |
| `button` | nächste fällige Einzelaufgabe starten | ja |
| `button` | laufenden/ausstehenden Plan abbrechen | ja |
| `button` | Queue neu berechnen, solange noch nicht gestartet | ja |
| `event` | Job-/Block-Lifecycle für externe Automationen | soll |

## Raumgerät pro gewählter HA-Area

| Plattform | Semantik | Pflicht |
|---|---|---|
| `switch` | Raum im Plan aktiv | ja |
| `binary_sensor` | heute fällig | ja |
| `sensor` | lesbarer Raumstatus | ja |
| `sensor` | nächste fällige Aufgabe/Zeit | ja |
| `number` | Intervall Saugen in Tagen | ja |
| `number` | Intervall Saugen+Wischen in Tagen | bei Mop-Fähigkeit |
| `number` | Priorität | ja |
| `select` | bevorzugter Modus: Saugen / Saugen+Wischen / automatisch | bei Mop-Fähigkeit |
| `button` | One-Tap: fällige Aufgabe starten/anhängen | ja |
| `button` | heute überspringen | ja |
| `button` | auf morgen verschieben | soll |
| `button` | Extra-Reinigung anhängen | soll |

## Attribute des Queue-Sensors

```yaml
block_id: 2f3f...
block_state: running
created_at: 2026-09-16T08:00:00+02:00
jobs:
  - job_id: 8a12...
    area_id: kitchen
    area_name: Küche
    mode: vacuum_and_mop
    state: completed
    position: 1
  - job_id: 19bc...
    area_id: hallway
    area_name: Flur
    mode: vacuum
    state: running
    position: 2
```

Hinweis: Attribute sind für Anzeige und Diagnose gedacht, nicht als einziges Persistenzformat.

## Services

UI-Buttons decken Standardfälle ab. Für Automationen stehen zusätzlich stabile Services bereit:

- `vacuum_planner.start_due_block`
- `vacuum_planner.enqueue_room`
- `vacuum_planner.skip_room_today`
- `vacuum_planner.postpone_room`
- `vacuum_planner.cancel_block`
- `vacuum_planner.resolve_unknown_job`

Jeder Service adressiert die Config Entry bzw. das Planner-Gerät und verwendet `area_id`, niemals rohe Hersteller-Segment-IDs.

## Dashboard-Regel

Das mitgelieferte Dashboard liest ausschließlich diesen Vertrag. Herstellerstatus wie Akku oder Dockzustand wird über normalisierte Planner-Sensorattribute oder eine bewusst eingebettete Standard-`vacuum.*`-Karte angezeigt, nicht über Dreame-/Roborock-spezifische Sensoren.
