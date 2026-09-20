# Roadmap

## Phase 0 — Entscheidungen und Verträge

**Ziel:** Produktgrenzen und öffentliche Verträge stabilisieren, bevor HA-spezifischer Code entsteht.

- [x] Ausgangssystem read-only erfassen
- [x] Custom Integration als führende Lösungsform bestimmen
- [x] Queue-/Block-Invarianten dokumentieren
- [x] ersten universellen Entity-Vertrag definieren
- [x] Kompatibilitätsmatrix und Capability-Tiers reviewen
- [x] UX-Flow und Standardkarten-Dashboard freigeben
- [x] ADR 0001 auf `Accepted` setzen

**Gate:** Architektur-, UX- und Integrationsreview widersprechen sich nicht; offene Annahmen sind markiert.

## Phase 1 — Testbarer Planner-Core

**Ziel:** Reine Python-Domainlogik ohne Home-Assistant-Laufzeit.

- Plan-, Block- und Jobmodelle
- Fälligkeitsberechnung für Saugen und Saugen+Wischen
- Priorisierung und unveränderliche Snapshot-Blöcke
- ausschließlich fällige Jobs aus konfigurierten Area-Plänen
- Zustandsautomat einschließlich Fehler/`uncertain`
- versioniertes Persistenzschema und Migrationen
- Unit- und Property-Tests

**Stand Beta-Kandidat:** Domainmodell, Planung, Queue, Zustandsautomat, Serialisierung,
Recovery und Unit-Tests sind implementiert. Das Gate bleibt für eine spätere formale
Release-Freigabe anhand der vollständigen Abdeckung zu bestätigen.

**Gate:** vollständige Testabdeckung der Invarianten; kein Hersteller- oder HA-Import im Core.

## Phase 2 — Home-Assistant-Integration, generischer Pfad

**Ziel:** Installierbare Custom Integration mit UI-Onboarding.

- Manifest, Config Flow, Options Flow, Übersetzungen
- Auswahl einer `vacuum.*`-Entität
- Erkennung von `VacuumEntityFeature.CLEAN_AREA`
- Prüfung der nativen Segment→Area-Zuordnung
- Auswahl aktivierter Areas und Planparameter
- Coordinator, Store, Device-/Entity-Modell
- normalisierte Sensoren, Switches, Buttons, Numbers und Selects
- Versand über `vacuum.clean_area` mit geordneter Area-Liste
- Repairs und Diagnostics

**Stand Beta-Kandidat:** installierbare Shell, UI-Flows, nativer Area-Pfad, Coordinator,
Store, öffentliche Plattformen, Repairs und Diagnostics sind vorhanden und mit simulierten
HA-Schnittstellen getestet. Der vollständige Zielumfang einzelner Planparameter bleibt offen.

**Gate:** Integrationstests mit simulierten HA-Entities; noch keine reale Robotersteuerung.

## Phase 3 — UX und Dashboard

**Ziel:** familienfähige Bedienung ohne YAML.

- Onboarding-Copy und progressive Capability-Anzeige
- Planner-Übersicht, Queue und Raumkonfiguration
- Standarddashboard oder unterstützte Sidebar-/Frontend-Strategie
- responsive Tablet-/Desktop-/Mobile-Layouts
- Accessibility, Fokusführung, Touch-Ziele und Fehlerzustände
- kein direktes Referenzieren von Herstellerentitäten

**Stand Beta-Kandidat:** Standardkarten-Template, einmaliger visueller UI-Schritt und
Mock-States sind unter [`dashboard/`](../dashboard/README.md) vorhanden. Dynamische Strategy,
vollständiger Planeditor sowie Screenshot-/DOM-Abnahme bleiben offen.

**Gate:** statischer UX-Review und Screenshot-/DOM-Tests gegen Mockdaten; keine Live-Instanz.

## Phase 4 — Adapter und Capability-Tiers

**Ziel:** Zusatznutzen ohne Herstellerkopplung des Cores.

Priorität:

1. nativer `vacuum.clean_area`-Pfad (u. a. Roborock, Ecovacs, Matter, MQTT/Valetudo und kompatible Custom Integrations)
2. Dreame/Mova-Erweiterung für Modus, Sequenz und Telemetrie
3. Xiaomi-Miio-Segmentadapter
4. Eufy-Erweiterung/Fallback für modellabhängige Raumfunktionen
5. Valetudo-Erweiterung nur für Iterationen/Custom Order
6. Long Tail: Narwal, Shark2MQTT und bewusst eingeschränkte Ganzflächenplattformen

Adapter dürfen nur normalisierte Fähigkeiten bereitstellen:

- Modus Saugen / Saugen+Wischen setzen
- geordneten Mehrraumauftrag senden
- Raum-/Segmentfortschritt beobachten
- Run-ID oder zuverlässige Abschlusskorrelation
- native Queue erweitern

**Gate:** Contract-Tests pro Adapter; kein Adapter darf Planner-Persistenz direkt ändern.

## Phase 5 — Migration und kontrollierter Shadow Mode

**Ziel:** Saschas bestehende Planung ohne Big Bang ablösen.

- read-only Import der Räume, Intervalle, Prioritäten und Zeitstempel
- Alt- und Neusystem parallel vergleichen, aber nur Alt-System steuert den Roboter
- berechnete Tagesblöcke und Statusübergänge vergleichen
- Abweichungen klassifizieren und beheben
- expliziter Cutover mit Backup und Rollback

**Gate:** mehrere repräsentative Planungstage ohne unerklärte Differenzen.

## Phase 6 — Live-Pilot

Erst nach ausdrücklicher Freigabe:

- ein Roboter, wenige Räume, beaufsichtigte Läufe
- zunächst generischer `vacuum.clean_area`-Pfad
- danach Adapterfunktionen einzeln aktivieren
- Fehler-, Neustart- und Interferenzfälle testen
- Altlogik erst nach stabiler Pilotphase entfernen

**Aktueller Status:** nicht freigegeben. Dry-run/Shadow Mode bleibt Standard; siehe
[Beta-Umfang](beta-scope.md) und [bekannte Grenzen](limitations.md).

## Release-Kriterien für v1.0

- vollständig UI-konfigurierbar
- stabiler universeller Entity-Vertrag
- dokumentierte Capability-Tiers
- sichere Recovery ohne stilles Doppelstarten
- Dashboard ohne installationsspezifische Anpassung nutzbar
- Migration dokumentiert
- CI für Tests, Typprüfung, Lint und HACS-/HA-Strukturprüfung grün
