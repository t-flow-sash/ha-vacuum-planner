# Importierbares Standardkarten-Dashboard

[`vacuum-planner.yaml`](vacuum-planner.yaml) ist eine vollständige Lovelace-Raw-Konfiguration mit `views` und einer Sections-Ansicht. Sie verwendet ausschließlich Home-Assistant-Standardkarten (`heading`, `tile`, `button`, `conditional`, `markdown`, `entities`) und ändert bestehende Dashboards nicht automatisch.

## Voraussetzung: stabile Entity-IDs einmalig setzen

Home Assistant vergibt Entity-IDs beim Anlegen eines Config Entry. Damit dieselbe Datei installationsübergreifend importierbar bleibt, benenne die erzeugten Planner-Entities unter **Einstellungen → Geräte & Dienste → Entitäten** einmalig exakt wie folgt um:

- `sensor.vacuum_planner_status`
- `sensor.vacuum_planner_next_action`
- `sensor.vacuum_planner_pending_tasks`
- `sensor.vacuum_planner_queue`
- `sensor.vacuum_planner_current_phase`
- `switch.vacuum_planner_planning`
- `binary_sensor.vacuum_planner_ready`
- `binary_sensor.vacuum_planner_attention_required`
- `button.vacuum_planner_start_next_due_task`
- `button.vacuum_planner_cancel_current_block`

Das sind ausschließlich Entities der Integration; keine Sauger-, Hersteller- oder Segment-ID wird in das Dashboard eingetragen. Falls eine ID bereits belegt ist, muss sie zuerst bereinigt werden. Ohne diese eindeutige Zuordnung zeigt Home Assistant die betroffenen Karten als nicht verfügbar an.

## Import

1. Ein neues leeres Dashboard **Saugplanung** anlegen; kein bestehendes Dashboard überschreiben.
2. Im Dashboard-Menü **Raw-Konfigurationseditor** öffnen.
3. Den vollständigen Inhalt von [`vacuum-planner.yaml`](vacuum-planner.yaml) einfügen, speichern und die Ansicht neu laden.
4. Status, Queue und Buttons zunächst bei aktiviertem Dry-run prüfen.

Die Datei ist als vollständige Raw-Konfiguration (`title` plus `views`) importierbar. Wer YAML-Dashboards in `configuration.yaml` verwaltet, kann dieselbe Datei auch als eigenes Dashboard referenzieren; die Aktivierung dieses allgemeinen Home-Assistant-Modus gehört nicht zur Integration.

## Dynamische Queue

Die Markdown-Standardkarte liest bei jeder Zustandsänderung das begrenzte Attribut `items` der realen Integration-Entity `sensor.vacuum_planner_queue`. Die Entity wird durch Coordinator-Publikationen aktualisiert; es gibt keine statischen Raumzeilen und keine Action-Response-Zwischenspeicherung.

Die Projektion:

- behält die autoritative Queue-Reihenfolge bei;
- zeigt höchstens 20 Einträge und meldet eine Kürzung;
- enthält nur Anzeigename, Modus, Position und Status;
- enthält keine Job-/Block-/Area-ID, Adapterziele, Tokens oder Fehlerdetails;
- aktualisiert Pending, Running, Completed, Failed und Uncertain dynamisch.

Completed bleibt sichtbar und wird mit Haken, Klartext **Erledigt** und `--disabled-text-color` eindeutig grau/dezent dargestellt. Farbe ist nie das einzige Signal. Failed und Uncertain besitzen getrennte Symbole und Texte.

## Bedienbarkeit

Alle interaktiven Tile- und Button-Karten belegen mindestens zwei Sections-Zeilen. Die nativen Bedienelemente halten dadurch die Home-Assistant-Mindestgröße von **48 px** für Touch-Ziele ein; es gibt keine per CSS verkleinerten Ziele. Kritische Buttons haben zusätzlich eine Hold-Aktion für Details.

## Weitere Artefakte

- [`vacuum-planner.yaml`](vacuum-planner.yaml): kanonische importierbare Dashboard-Konfiguration;
- [`mock-states.json`](mock-states.json): Review-Daten für Empty, Paused, Running, Completed, Failed und Uncertain.

Die Integration legt oder verändert nie selbst Lovelace-Dashboards oder interne Dashboard-Storage-Dateien.
