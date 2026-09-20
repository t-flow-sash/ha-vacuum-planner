# Changelog

Alle wesentlichen Änderungen werden in dieser Datei dokumentiert. Es wurde noch kein Release veröffentlicht.

## v0.1.0-beta.2 – Release-Kandidat (unveröffentlicht)

> Kandidat zur Prüfung: kein Git-Tag, kein GitHub-Release und keine öffentliche Freigabe wurden durch diesen Stand erstellt.

### Fixed

- Config Flow akzeptiert Home Assistants native `VacuumEntityFeature`-Bitmaske für `CLEAN_AREA`, statt echte `IntFlag`-Werte fälschlich als nicht unterstützten Typ abzulehnen.
- Config Flow, Dispatch-Preflight und Laufzeit-Observer verwenden dieselbe fail-closed Capability-Prüfung, einschließlich Ablehnung von Bool-, negativen und malformed Werten.
- Das `area_plan`-Schema nutzt nur frontend-serialisierbare Validatoren; strikte Ganzzahlprüfung bleibt beim Submit erhalten.
- Die Raumplanung zeigt freundliche Area-Namen und den aktuellen Fortschritt sowie vollständige Standard-, deutsche und englische Übersetzungen.

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
