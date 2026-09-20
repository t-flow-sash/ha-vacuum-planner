# Technische Zielarchitektur

> **Statusabgrenzung:** Dieses Dokument beschreibt weiterhin die Zielarchitektur. Der
> installierbare Beta-Kandidat implementiert den generischen Integration-Shell-/Core-Pfad,
> persistente Zustände, öffentliche Entities/Actions, Diagnostics und Repairs. Der
> vollständige Planeditor, Mehrroboter-Lanes und Hardwarefreigaben sind noch nicht
> enthalten. Maßgeblich für den aktuellen Lieferumfang
> sind [Beta-Umfang](beta-scope.md) und [bekannte Grenzen](limitations.md).

## 1. Architekturziel

Der HA Vacuum Planner ist ein kleiner Workflow-Orchestrator **oberhalb** vorhandener Home-Assistant-Integrationen. Er ersetzt weder Herstellerintegration noch `vacuum.*`-Entity, sondern plant raumbezogene Aufgaben, hält den fachlichen Queue-Zustand und delegiert die Ausführung über Capability-Adapter.

```text
HA UI / Standard-Dashboard / Automationen
                 |
      stabile Entities + Actions
                 |
         Planner Application Core
  Planer | Scheduler | Queue | Recovery | Repairs
                 |
         Capability-/Adapter-Layer
       /             |                \
 native clean_area  Vendor-Adapter   Whole-home fallback
       \             |                /
       vorhandene vacuum.*-Entitäten und Services
```

### Leitprinzipien

1. **HA-Area-ID ist die fachliche Raumidentität.** Anzeigenamen dürfen geändert werden; Segment-IDs bleiben Adapterdetails.
2. **Core kennt keine Herstellernamen.** Herstellerwissen liegt ausschließlich in Adaptern.
3. **Ein gestarteter Plan ist ein unveränderlicher Snapshot.** Spätere Konfigurationsänderungen betreffen nur neue Blöcke.
4. **Planner-Atomizität und Roboter-Atomizität werden getrennt ausgewiesen.** Die UI verspricht nie mehr als der Adapter leisten kann.
5. **Kein stilles Downgrade.** Fehlende Raum- oder Wischfähigkeit führt zu erklärtem Gate/Payoff, nicht zu unbemerkter Ganzflächen- oder Nur-Saug-Reinigung.
6. **Nur `vacuum` und `vacuum_and_mop`.** `mop_only` existiert weder im Domainmodell noch in der UI.
7. **Eigene Persistenz ist autoritativ.** Entity-Zustände und Recorder sind Projektionen, nicht Queue-Datenbank.

## 2. Komponenten

### 2.1 Integration Shell

Home-Assistant-spezifische Schicht:

- `manifest.json`, initialer Config Flow und sicherer Options Flow;
- Registry-Zugriff und Event-/State-Subscriptions;
- Service-/Action-Registrierung;
- Entities, Übersetzungen, Repairs und Diagnostics;
- Laden/Migrieren des versionierten Stores;
- Lifecycle von Coordinator, Worker und Adaptern.

### 2.2 Domain Core

Reine, asynchronitätsarme Python-Logik ohne HA- oder Herstellerimporte:

- `PlannerConfig`, `RoomPlan`, `PlanRevision`;
- Fälligkeitsberechnung und Priorisierung;
- `PlanSnapshot`, `QueueBlock`, `QueueJob`;
- Zustandsautomaten und Invarianten;
- Dedup-/Skip-Regeln;
- normalisierte Fehler und Recovery-Entscheidungen.

Der Core ist deterministisch testbar: Uhr, IDs und Adapterresultate werden injiziert.

### 2.3 Application/Coordinator

Ein Coordinator pro Config Entry:

- serialisiert alle Mutationen mit einem `asyncio.Lock`;
- materialisiert und versiegelt Tagesblöcke;
- persistiert vor externen Seiteneffekten;
- steuert den Worker;
- korreliert Adapterstatus mit Jobs;
- aktualisiert Entity-Projektionen;
- erzeugt Repairs bei dauerhaft lösbaren Problemen.

Mehrere Roboter können getrennte Execution Lanes besitzen. Innerhalb einer Lane existiert höchstens ein Commit bzw. aktiver Job.

### 2.4 Adapter Registry

Adapter implementieren einen kleinen Contract, z. B.:

```python
class VacuumAdapter(Protocol):
    async def async_probe(self) -> CapabilityProfile: ...
    async def async_validate(self, jobs: tuple[ResolvedJob, ...]) -> ValidationResult: ...
    async def async_commit_block(self, block: ResolvedBlock) -> CommitResult: ...

    async def async_observe(self, run: ActiveRun) -> ExecutionObservation: ...
    async def async_cancel(self, run: ActiveRun) -> CancelResult: ...
```

`ResolvedJob` enthält die HA-Area und das im Probe-Schritt aufgelöste Adapterziel. Der persistierte Snapshot speichert beides, damit spätere Mappingänderungen einen laufenden Block nicht mutieren.

Adapter dürfen nie direkt den Store oder Entity-Zustände ändern. Sie liefern typisierte Ergebnisse; nur der Coordinator vollzieht Domainübergänge.

### 2.5 Persistenz

- `ConfigEntry.data`: notwendige Topologie/Identität (gewählte Vacuum-Entities, Area-Freigaben, Adapterbindung).
- `ConfigEntry.options`: optionale Laufzeitpräferenzen.
- `entry.runtime_data`: Coordinator, Locks, Tasks, Adapterinstanzen.
- versionierter `homeassistant.helpers.storage.Store`: Planrevisionen, Queueblöcke, Jobs, History/Recovery-Marken.

Kritische Queue-Übergänge werden unmittelbar und atomar gespeichert. Verzögertes Speichern ist nur für unkritische Statistiken zulässig.

## 3. Domainmodell

```text
PlannerInstance
 ├── 1..n RobotLane
 │    ├── selected vacuum entity
 │    ├── CapabilityProfile
 │    └── 0..n AreaBinding(area_id -> adapter target)
 ├── 1..n RoomPlan(area_id, lane_id, intervals, priority, enabled)
 ├── PlanRevision
 └── QueueLedger
      ├── QueueBlock (sealed snapshot)
      └── QueueJob
```

### `RoomPlan`

- `area_id` (stabiler Schlüssel)
- `lane_id`
- `enabled`
- `vacuum_interval_days`
- `vacuum_and_mop_interval_days` (nur bei Capability)
- `preferred_mode`: `vacuum | vacuum_and_mop`
- `priority`
- `skip_until`
- `last_completed_vacuum_at`
- `last_completed_vacuum_and_mop_at`

Ein `vacuum_and_mop`-Abschluss erfüllt zugleich die Saugfälligkeit.

### `CapabilityProfile`

Keine einzelne Tierzahl ersetzt die Feature-Matrix. Die Matrix ist autoritativ; ein Tier ist nur UX-Kurzform.

- `area_cleaning`
- `ordered_multi_area`
- `mode_vacuum`
- `mode_vacuum_and_mop`
- `atomic_device_commit`

- `queue_introspection`
- `per_area_progress`
- `run_correlation`
- `idempotent_dispatch`
- `cancel_current`

### `QueueBlock` und `QueueJob`

Das vollständige Schema und die Zustandsübergänge stehen in [Queue- und Block-Semantik](queue-semantics.md). Entscheidend sind stabile IDs, eine unveränderliche Jobfolge und die Trennung zwischen Commit- und Execution-Zustand.

## 4. Area- und Mapping-Modell

### Native Basis

Wenn die gewählte Vacuum-Integration `CLEAN_AREA` plus natives Area-Mapping anbietet, verwendet der generische Adapter `vacuum.clean_area` für die vom einzelnen Job adressierte HA-Area. Der Planner führt kein zweites benutzerseitiges Segmentregister.

### Onboarding-Gate

Für jede ausgewählte Area wird geprüft:

1. Area existiert in der Area Registry;
2. Vacuum-Entity existiert und ist verfügbar konfiguriert;
3. Adapter kann die Area eindeutig auflösen;
4. gewünschter Modus wird unterstützt;
5. kein ausgewählter Raum bleibt ungemappt.

Fehlerbeispiel:

> „Küche ist diesem Roboter noch keinem Kartensegment zugeordnet. Öffne die Einstellungen der Sauger-Entität, wähle ‚Map vacuum segments to areas‘ und ordne Küche zu. Kehre danach hierher zurück und drücke ‚Erneut prüfen‘.“

Ein von `start_next` erzeugter Ein-Job-Block wird **nicht teilweise** versiegelt. Entfernte Areas, verlorene Entities oder veraltete Bindings erzeugen deduplizierte Repairs und blockieren nur die betroffene Lane.

### Herstelleradapter

Ein Herstelleradapter darf Segment-IDs oder vendor-spezifische Services nutzen, wenn die öffentliche HA-Abstraktion eine benötigte Capability nicht ausdrückt. Diese IDs bleiben hinter `AreaBinding`; Dashboard, Domain Core und öffentliche Actions akzeptieren ausschließlich `area_id`.

## 5. Öffentliche Schnittstellen

### Actions

- `vacuum_planner.start_next` (kanonische öffentliche One-Tap-Action)
- `vacuum_planner.skip_area_today`
- `vacuum_planner.postpone_area`
- `vacuum_planner.cancel_block`
- `vacuum_planner.resolve_uncertain_run`
- optional read-only `vacuum_planner.get_queue` mit Response-Daten

Mutierende Actions adressieren explizit eine Planner-Instanz und laufen über denselben Coordinator/Lock. Die Action-Schemas werden auch ohne geladenen Config Entry registriert, damit Automationen editierbar bleiben.

### Statusquelle

Entities und persistenter Store sind die Statusquelle der Beta.

### Entities

Der detaillierte Vertrag steht in [Universeller Entity-Vertrag](entity-contract.md). Ein Planner-Service-Device bündelt die Entitäten; bestehende Vacuum-Devices und HA-Areas werden nicht dupliziert.

## 6. Nebenläufigkeit und Recovery

- ein Lock pro Robot Lane; optional zusätzlicher kurzer Ledger-Lock über lane-übergreifende Mutationen;
- wiederholtes One-Tap liefert denselben offenen Ein-Job-Block zurück, statt einen zweiten zu erzeugen;

- direkte externe Roboterbedienung wird, soweit beobachtbar, als Interferenz ausgewiesen;
- nach Neustart wird nie blind erneut gesendet;
- ohne sichere Korrelation geht ein Commit in `uncertain`, mit Benutzerentscheidung statt vermutetem Erfolg;
- „exactly once“ gegenüber externen Geräten wird nicht behauptet; angestrebt wird idempotentes Planner-Verhalten plus bestmögliche Adapterkorrelation.

## 7. Dashboard-Architektur

Die Backend-Integration liefert Planner-Entities und Actions für HA-Automationen,
Geräteansicht und manuelle Standardkarten. Zusätzlich enthält der Beta-Kandidat das
herstellerneutrale [Standardkarten-Dashboard](../dashboard/README.md). Weil Standardkarten
die von HA vergebenen Entity-IDs nicht dynamisch auflösen, werden die dokumentierten
stabilen Entity-IDs einmalig gesetzt und die Raw-Konfiguration bewusst importiert.

Nicht zulässig sind ungefragte Änderungen an bestehenden Dashboards, direkte Manipulation interner Lovelace-Storage-Dateien oder private APIs. Daher bedeutet „möglichst automatisch“: **ein bestätigter Anlegeschritt, anschließend dynamisch**, nicht heimliche Installation als Hauptdashboard.

UX-Hierarchie:

1. Hero „Nächste Reinigung“ + Robot/Planner-Status;
2. One-Tap „Fällige Aufgabe starten“;
3. tatsächlich materialisierte Queue-Jobs aus fälligen Planaufgaben;
4. erledigte Räume grau, laufender Raum betont, keine ungeplanten Räume;
5. Raumpläne und Intervalle unterhalb der Primäraktionen;
6. Capability-Payoff in verständlicher Sprache, nicht als technische Featureliste.

Die öffentliche Queue bleibt eine begrenzte, recorderfreundliche Sensorprojektion; die
vollständige read-only Abfrage erfolgt ausschließlich über `vacuum_planner.get_queue`.

## 8. Nichtfunktionale Anforderungen

- Übersetzungen mindestens Deutsch/Englisch;
- Diagnostics redigieren Entity-/Area-IDs, Namen, Mapping und Historie;
- keine Hersteller-Credentials im Planner;
- Store- und Config-Entry-Migrationen sind versioniert und getestet;
- kein Netzwerk- oder Service-I/O in Entity-Properties;
- Adapter-Contract-Tests, State-Machine-Tests und Restart/Concurrency-Tests;
- Feature Payoffs sind explizit: `available`, `degraded`, `blocked`, jeweils mit Begründung.

## 9. Bewusste Grenzen

- Der Core kann keine Gerätequeue-Atomizität erzeugen, die die Zielintegration nicht anbietet.
- Raumgenaue Fortschrittsanzeige ist ohne per-Area-Telemetrie nicht belastbar; dann werden Räume erst bei Gesamtabschluss gemeinsam abgeschlossen.
- Ganzflächen-Fallback ist ein separater, sichtbar eingeschränkter Betriebsmodus und kein Ersatz für ausgewählte Raumplanung.
- Direkte Aktionen aus Hersteller-App oder anderen Automationen können nur erkannt, nicht verhindert werden.
