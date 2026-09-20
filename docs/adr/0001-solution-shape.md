# ADR 0001: Hybridarchitektur mit Custom-Integration-Kern

- Status: **Accepted**
- Datum: 2026-09-16
- Entscheider: Projektteam

## Kontext

Der Planner soll ohne YAML oder Programmierung eingerichtet werden, native HA-Areas verwenden, pro One-Tap genau die nächste fällige Aufgabe als Ein-Job-Block behandeln und einen stabilen, herstellerneutralen Entity-/Dashboard-Vertrag bereitstellen. Die Beta erzeugt Queue-Aufgaben ausschließlich aus fälligen Area-Plänen. Hersteller unterscheiden sich deutlich bei Raumreinigung, Moduswahl, Gerätequeue, Telemetrie und Run-Korrelation.

Zu entscheiden ist zwischen:

1. Automation Blueprint;
2. Script Blueprint;
3. Custom Integration;
4. Hybrid aus Custom Integration und optionalen Blueprints/Frontend.

## Entscheidungstreiber

- UI-only Config und sichere Verhaltens-Options;
- persistentes, versioniertes Domain- und Queue-Modell;
- zentraler Lock, Idempotenz und Recovery nach HA-Neustart;
- eigene stabile Entities, Actions, Repairs und Diagnostics;
- native HA-Areas als Raumidentität;
- Capability-Erkennung und isolierte Herstelleradapter;
- dynamisch bereitstellbares Standarddashboard;
- testbare, ehrliche Block-/Queue-Garantien.

## Bewertete Optionen

| Kriterium | Automation Blueprint | Script Blueprint | Custom Integration | Hybrid |
|---|---:|---:|---:|---:|
| UI-Onboarding ohne YAML | teilweise | teilweise | **ja** | **ja** |
| persistentes Domainmodell | nein | nein | **ja** | **ja** |
| eigener Entity-Vertrag | nein | nein | **ja** | **ja** |
| globales Lock/Recovery | schwach | schwach | **stark** | **stark** |
| Capability-/Adaptermodell | unwartbar | begrenzt | **sauber** | **sauber** |
| Dashboard-Artefakt/Repairs | nein | nein | **ja** | **ja** |
| einfache Verteilung | **stark** | **stark** | mittel | mittel |
| Trigger-/Automationskomposition | **stark** | stark | mittel | **stark** |

### Automation Blueprint

Geeignet, um Zeit-, Präsenz- oder Haushaltsregeln an eine Planner-Action zu koppeln. Nicht geeignet als Kern: `mode: queued` serialisiert nur Runs dieser Automation, ist keine Gerätequeue-Transaktion, kein globaler Lock und keine robuste Neustartpersistenz.

### Script Blueprint

Geeignet als optionale Aktionshülle. Auch `mode: queued` garantiert weder Robot-Atomizität noch Recovery oder Schutz vor anderen Serviceaufrufen. Komplexe Adapter-/Capability-Logik würde in schwer testbare Jinja-Verzweigungen ausufern.

### Reine Custom Integration

Erfüllt die Kernanforderungen, lässt jedoch die gute Wiederverwendbarkeit von HA-Triggern ungenutzt.

## Entscheidung

Wir wählen eine **Hybridarchitektur mit einer schlanken Custom Integration als verbindlichem Kern**.

Der Kern verantwortet:

- initialer Config Flow und sichere Verhaltens-Options;
- Plan-, Snapshot-, Queue- und Run-Domainmodell;
- versionierte Persistenz, Locking, Idempotenz und Recovery;
- Capability-Probe und Adapterauswahl;
- HA-Area-Validierung und Mapping-Gates;
- universelle Entities und Actions;
- Repairs und Diagnostics.

Optionale Schichten:

- Automation Blueprints ausschließlich als Zeit-/Präsenz-/Energie-Trigger;
- Script Blueprint höchstens als Komfortwrapper um öffentliche Actions;
- importierbares Dashboard aus Home-Assistant-Standardkarten;
- Vendor-Adapter nur dort, wo öffentliche HA-Abstraktionen fehlen.

Kritische Zustandslogik und Queue-Semantik dürfen **nie** in Blueprint und Integration doppelt existieren.

## Native HA-Basis

Der bevorzugte generische Pfad nutzt `VacuumEntityFeature.CLEAN_AREA`, das native Segment-zu-Area-Mapping und `vacuum.clean_area` für die vom einzelnen Job adressierte HA-Area. HA-Area-IDs sind die öffentliche Raumidentität. Rohe Segment-IDs bleiben Adapterdetails.

Ein einzelner `vacuum.clean_area`-Aufruf beweist jedoch weder eine transaktionale Gerätequeue noch raumgenauen Fortschritt. Deshalb führt der Planner ein eigenes persistentes Ledger.

## Verbindliche Garantiegrenze

Wir unterscheiden:

1. **Planner-Atomizität:** Genau der von `start_next` ausgewählte Job wird als unveränderlicher Ein-Job-Block in einem kritischen Abschnitt vor dem Dispatch persistiert. Diese Garantie liefert der Kern.
2. **Robot-Atomizität:** Eine stärkere Garantie für Gerätequeues wird nur bei expliziter Adapter-Capability angezeigt; der ausgelieferte öffentliche Beta-Pfad sagt sie nicht zu.

Bei Geräten ohne native Queue emuliert der Planner die Reihenfolge. Die UI darf dies nicht als „atomar in Gerätequeue übertragen“ bezeichnen.

## Konsequenzen

### Positiv

- vollständige UI-first Einrichtung;
- testbarer herstellerneutraler Core;
- robuste Queue/Recovery und universelle Entities;
- Capability-Tiers erlauben inkrementelle Adapterentwicklung;
- Blueprints bleiben nützliche, aber ungefährliche Erweiterungspunkte;
- Dashboard kann ohne installationsspezifische IDs generiert werden.

### Negativ

- höherer Entwicklungs-, Test- und Wartungsaufwand;
- HACS-/Custom-Repository-Verteilung bis zu möglicher Core-Aufnahme;
- Frontend- und HA-API-Kompatibilität müssen gepflegt werden;
- starke Robot-Atomizität bleibt herstellerabhängig;
- „Dashboard vollautomatisch installieren“ wird auf einen bestätigten Anlegeschritt reduziert.

## Verworfene Annahmen

- HA-Script-/Automation-`queued` ist **keine** Roboterqueue.
- Ein Mehrraum-Serviceaufruf ist **nicht automatisch** transaktional.
- Entity-State/Recorder ist **kein** Queue-Persistenzlayer.
- Herstellername oder Entity-ID-Präfix ist **kein** Capability-Beweis.

## Folgeentscheidungen

- Domain-/Komponentenmodell: [Technische Zielarchitektur](../architecture.md)
- Queue-Invarianten: [Queue- und Block-Semantik](../queue-semantics.md)
- Adapter/Tiers: [Capability- und Adaptermodell](../capabilities.md)
- Hersteller-/Integrationsmatrix: [Kompatibilitätsrecherche](../compatibility.md)
- Config Flow/Dashboard: [Config Flow und Dashboard](../config-flow-and-dashboard.md)
- Entitäten: [Universeller Entity-Vertrag](../entity-contract.md)
- Umsetzung: [Roadmap](../roadmap.md)
