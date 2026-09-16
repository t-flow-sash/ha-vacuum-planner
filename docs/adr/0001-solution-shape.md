# ADR 0001: Lösungsform

- Status: **In Review**
- Datum: 2026-09-16

## Kontext

Ein reiner Automation- oder Script-Blueprint kann Benutzerlogik wiederverwendbar machen, besitzt aber keinen vollständigen Config Flow, kann keinen stabilen Satz eigener Entitäten dynamisch verwalten und kann kein universelles Produkt-Onboarding oder robustes Adaptermodell bereitstellen. Außerdem sind automatisch erzeugte bzw. verlässlich referenzierbare Dashboard-Entitäten und persistente Queue-Zustände Kernanforderungen.

## Vorläufige Entscheidung

Eine **Custom Integration mit optionalen Blueprints/Beispielautomationen** ist der führende Lösungsweg.

Die aktuelle Home-Assistant-Vacuum-API stellt mit `vacuum.clean_area` bereits eine entscheidende native Basis bereit: Benutzer ordnen vom Roboter gemeldete Segmente in den Einstellungen HA-Areas zu; der Service akzeptiert mehrere Areas in einer vom Benutzer vorgegebenen Reihenfolge. Der Planner muss diese Zuordnung weder duplizieren noch rohe Segment-IDs zum primären Datenmodell machen. Er muss beim Onboarding aber prüfen, ob `VacuumEntityFeature.CLEAN_AREA` und ein vollständiges `area_mapping` vorhanden sind.

Ein einzelner `vacuum.clean_area`-Aufruf ist noch keine herstellerübergreifende Garantie für eine transaktionale Gerätequeue oder raumgenaue Abschlussbestätigung. Daher bleibt ein persistentes Planner-Ledger erforderlich.

Der Integration-Core verantwortet:

- Config Flow und Options Flow
- Auswahl der `vacuum.*`-Entität
- Auswahl und Validierung von HA-Areas
- persistentes Plan-/Queue-Modell
- herstellerunabhängige Sensoren, Buttons, Switches, Selects und Kalender-/Zeitinformationen
- Capability-Erkennung und Adapterauswahl
- Repairs und Diagnostik
- Dashboard-Vertrag und Dashboard-Artefakt

Optionale Blueprints können später Ereignisse des Planners mit Anwesenheit, Energiepreisen oder Haushaltsregeln verbinden. Sie sind Erweiterungspunkte, nicht das Produktfundament.

## Noch zu prüfen

- belastbare Grenzen der programmgesteuerten Dashboard-Bereitstellung in aktuellen HA-Versionen
- stabilste öffentliche Schnittstelle für Area-/Room-to-Segment-Mapping
- Semantik von Queue-Blöcken bei Plattformen ohne native Queue
- Mindestumfang eines generischen `vacuum.*`-Fallbacks
- Review durch Architektur-, Integrations- und UX-Workstreams

## Konsequenzen

### Positiv

- echte UI-first Einrichtung
- eigene universelle Entitäten
- saubere Migration, Diagnostik und Übersetzungen
- testbares Core-/Adaptermodell
- kontrollierte Degradierung nach Capability-Tier

### Negativ

- deutlich mehr Entwicklungs- und Wartungsaufwand als ein Blueprint
- HACS-/Custom-Repository-Verteilung bis zu einer möglichen Core-Aufnahme
- Home-Assistant-API-Änderungen müssen aktiv verfolgt werden
- Herstelleradapter bleiben aufgrund externer Integrationen wartungsintensiv
