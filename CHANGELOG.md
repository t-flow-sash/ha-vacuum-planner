# Changelog

Alle wesentlichen Änderungen werden in dieser Datei dokumentiert. Es wurde noch kein Release veröffentlicht.

## v0.1.0-beta.1 – Release-Kandidat (unveröffentlicht)

> Kandidat zur Prüfung: kein Git-Tag, kein GitHub-Release, kein Commit und keine öffentliche Freigabe wurden durch diesen Stand erstellt.

### Added

- installierbare Custom Integration mit UI-basiertem Config- und sicherem Options-Flow;
- persistenter Planner-Core, Queue-/Blockzustände und Recovery für unsichere Läufe;
- öffentliche Standard-Entities und Actions sowie Diagnostics und Repairs;
- stabile, auf 20 Einträge begrenzte Queue-Sensorprojektion ohne private Adapterdaten oder Persistenz-IDs;
- importierbare Lovelace-Konfiguration mit `views`, Sections und ausschließlich Home-Assistant-Standardkarten;
- dynamische Statusdarstellung einschließlich klar grau/dezent markierter Completed-Einträge und mindestens 48 px großer Touch-Ziele;
- reproduzierbarer Release-ZIP-Builder mit deterministischer Reihenfolge, festen Zeitstempeln, korrektem `custom_components/vacuum_planner`-Layout und `SHA256SUMS`;
- Installations-, Rollback-, Limitations- und Beta-Scope-Dokumentation;
- Release- und Dokumentationsvertragstests einschließlich Link-, Dashboard- und Reproduzierbarkeitsregeln.

### Changed

- privates, authentifiziert bezogenes semantisches Release-ZIP als primären Copy-Installationsweg dokumentiert;
- HACS ausdrücklich auf einen möglichen späteren Zeitpunkt mit öffentlich erreichbarem Repository begrenzt;
- nicht unterstützte Python-Paket-Installationsbehauptungen entfernt;
- README, Architektur, Roadmap und Traceability an den implementierten Beta-Stand angeglichen;
- Shadow-/Dry-run als Standard und fehlende Live-Pilot-Freigabe ausdrücklich dokumentiert.

### Security

- Queue-Attribute sind mengen- und textbegrenzt und enthalten keine Adapterziele, Tokens, internen IDs oder Fehlerdetails;
- Release-ZIP wird mit SHA-256-Prüfsumme ausgeliefert;
- Rollback verlangt ein Backup; direkte `.storage`-Bearbeitung ist nur bei vollständig gestopptem Home Assistant und niemals automatisch zulässig.

### Known blockers

- keine Live-/Hardwarevalidierung;
- kein veröffentlichter Tag oder Release;
- privates Repository ist nicht über HACS installierbar;
- keine Open-Source-Lizenz durch den Repository-Eigentümer festgelegt.
