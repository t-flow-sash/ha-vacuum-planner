# Beta-Umfang und Freigabegates

## Ziel dieses Kandidaten (`v0.1.0-beta.2`)

Der Kandidat macht den vorhandenen Integrationsstand installierbar und prüfbar, ohne eine Produktionsfreigabe vorzutäuschen. Er dient für Installation, UI-Onboarding, Vertragsprüfung, persistente Zustände und Shadow-/Dry-run-Auswertung.

## Enthalten

- reproduzierbares semantisches Release-ZIP mit SHA256SUMS für eine autorisierte private Copy-Installation;
- Config Flow für vorhandene Sauger-Entität und geordnete Home-Assistant-Areas;
- Topologieänderungen ausschließlich durch Löschen und Neueinrichten des Entries;
- Options Flow für Planung und Dry-run;
- versionierter Store, Queue-/Blockmodell und Restart-Recovery;
- öffentliche Entities und Actions einschließlich `vacuum_planner.start_next` und read-only Queue-Abfrage;
- Diagnostics und Repairs;
- deutsche und englische UI-Texte;
- importierbare Lovelace-Standardkarten-Konfiguration mit Sections, dynamischer Queue-Entity und Mock-States;
- automatisierte Unit-, Integrationsvertrags-, Sicherheits- und Dokumentationstests.

## Standardbetrieb

- Dry-run/Shadow Mode: **aktiv**.
- Planung kann zur Beobachtung aktiviert oder pausiert werden.
- Keine automatische Änderung bestehender Dashboards.
- Keine automatische Store-Manipulation außerhalb der versionierten Integrationspersistenz.
- Kein Herstelleradapter oder Gerät gilt ohne eigenen Nachweis als hardwareverifiziert.
- Das private Repository ist nicht per HACS installierbar; HACS ist erst bei öffentlicher Erreichbarkeit ein möglicher späterer Weg.
- Repository-Zugriff oder ein privates Artefakt erteilen keine über [`LICENSE`](../LICENSE) hinausgehenden Rechte.

## Nicht enthalten / nicht freigegeben

- produktive Robotersteuerung oder unbeaufsichtigter Betrieb;
- Live-Pilot;
- Hardware-/Firmware-Kompatibilitätszusage;
- vollständiger visueller Wochenplaneditor;
- zusätzlicher dynamischer Frontend-Code;
- automatische Dashboard-Anlage;
- Migration eines installationsspezifischen Altsystems;
- garantierte Gerätequeue-Atomizität;
- Git-Tag oder GitHub-Release; `v0.1.0-beta.2` ist ein unveröffentlichter Kandidat.

## Eintrittskriterien für einen späteren beaufsichtigten Live-Pilot

1. Vollständiges Home-Assistant-Backup und getesteter Rollback liegen vor.
2. Shadow-/Dry-run zeigt über repräsentative Tage keine ungeklärten Abweichungen.
3. Gewählter Sauger, Areas und Capabilities sind in der konkreten Installation validiert.
4. Keine offenen Repairs oder `uncertain`-Läufe.
5. Pilotumfang ist auf einen Sauger und wenige Räume begrenzt.
6. Eine Person gibt den Pilot ausdrücklich frei und beaufsichtigt Start, Fehler und Abbruch.

Bis alle Kriterien erfüllt und die Freigabe dokumentiert sind, bleibt Dry-run aktiv.

## Beta-Abnahme

Der Dokumentations-/Release-Kandidat gilt als technisch geprüft, wenn Tests, Ruff, mypy, Bandit, Python-Kompilierung, JSON-/YAML-Parsing, lokaler Linkcheck und `git diff --check` grün sind. Das ist kein Ersatz für Home-Assistant- oder Hardwaretests.
