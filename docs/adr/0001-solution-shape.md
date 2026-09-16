# ADR 0001: Lösungsform

- Status: **In Review**
- Datum: 2026-09-16

## Kontext

Ein reiner Automation- oder Script-Blueprint kann Benutzerlogik wiederverwendbar machen, besitzt aber keinen vollständigen Config Flow, kann keinen stabilen Satz eigener Entitäten dynamisch verwalten und kann kein universelles Produkt-Onboarding oder robustes Adaptermodell bereitstellen. Außerdem sind automatisch erzeugte bzw. verlässlich referenzierbare Dashboard-Entitäten und persistente Queue-Zustände Kernanforderungen.

## Vorläufige Entscheidung

Eine **Custom Integration mit optionalen Blueprints/Beispielautomationen** ist der führende Lösungsweg.

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
