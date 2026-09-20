# Capability- und Adaptermodell

## Grundsatz

Kompatibilität wird anhand beobachtbarer Fähigkeiten, nicht anhand von Marken, bewertet. Der Core plant identisch; Adapter entscheiden, welche Ausführungsgarantie möglich ist. Eine Tierzahl ist nur eine verständliche Zusammenfassung der Feature-Matrix.

## Capability-Tiers

| Tier | Mindestfähigkeiten | Nutzbarer Modus | Queue-/Blockgarantie | UI-Payoff |
|---|---|---|---|---|
| **T0 – Gesamtfläche** | generisches Start/Pause/Stop | gesamte Fläche, keine Räume | keine Raumblockgarantie | „Raumplanung nicht verfügbar“; optional klar getrennter Gesamtflächenmodus |
| **T1 – Areas** | `CLEAN_AREA`, eindeutiges Area-Mapping | raumbasierte Planung | Ein-Job-Block vor Dispatch persistiert | öffentliche Beta-Basis |
| **T2 – Batch** | zusätzliche Batch- und Modusfähigkeiten | nicht Teil des öffentlichen Beta-Vertrags | keine zusätzliche Zusage | reservierte Capability-Stufe |
| **T3 – Queue** | Queue-/Run-ID und Introspection | nicht Teil des öffentlichen Beta-Vertrags | keine zusätzliche Zusage | reservierte Capability-Stufe |

### Zwei getrennte Garantien

- **Planner-atomar:** Die Integration persistiert den unveränderlichen Ein-Job-Block vor dem externen Dispatch in einem Schritt. Ab T1 lieferbar.
- **Robot-atomar:** Diese stärkere Gerätequeue-Garantie ist im ausgelieferten öffentlichen Beta-Pfad nicht belegt und wird dort nicht zugesagt.

## Autoritative Capability-Matrix

```text
area_cleaning
ordered_multi_area
mode_vacuum
mode_vacuum_and_mop
atomic_device_commit

queue_introspection
per_area_progress
run_correlation
idempotent_dispatch
cancel_current
```

Capabilities haben neben `true/false` optional eine Herkunft (`native_feature`, `service_schema`, `adapter`, `configured`) und eine Begründung. Namen oder Entity-Präfixe allein sind kein verlässlicher Capability-Beweis.

## Adapterauflösung

Priorität:

1. nativer HA-Area-Adapter über `vacuum.clean_area`;
2. explizit unterstützter Adapter einer vorhandenen Herstellerintegration;
3. optionaler, klar markierter Gesamtflächen-Fallback.

Ein Vendor-Adapter darf nur den fehlenden Transport/Beobachtungsteil ergänzen. Er darf weder Planlogik duplizieren noch direkt Store, Entities oder Dashboard verändern.

## Dispatch-Strategien

### `native_batch`

Der Live-Pfad verwendet diesen internen Strategiewert auch für den einzelnen Job. Daraus folgt kein öffentlicher Batch- oder Gerätequeue-Vertrag.

### `planner_sequential`

Der öffentliche Beta-Pfad verwendet diesen Wert im Dry-run für den einzelnen materialisierten Job. Er verspricht keine automatische Folgeausführung.

### `device_queue`

Dieser Wert ist im Domainmodell reserviert, wird vom öffentlichen Beta-Pfad aber nicht gewählt. Die Dokumentation leitet daraus keine Gerätequeue-Funktion ab.

## Modusregeln

- erlaubte Domainwerte: `vacuum`, `vacuum_and_mop`;
- `mop_only` wird nie modelliert oder angeboten;
- fehlt `mode_vacuum_and_mop`, bleibt Saugen nutzbar und Wischintervall/-Auswahl wird verborgen;
- ein fälliger Wischvorgang wird nie still auf reines Saugen reduziert;
- Moduswahl muss vor dem Commit validiert werden, damit kein Teilblock entsteht.

## Fortschritts-Payoffs

| Telemetrie | Darstellung |
|---|---|
| `per_area_progress` | einzelner Raum wird nach bestätigtem Abschluss grau |
| nur globaler Run-Abschluss | während Lauf alle betroffenen Räume „läuft“/„Fortschritt nicht verfügbar“, danach gemeinsam grau |
| keine sichere Korrelation | Status `uncertain`, keine Erfolgstimestamps, Benutzerhinweis |

## Mindest-Contract-Tests je Adapter

- Probe liefert deterministisches CapabilityProfile;
- unbekannte oder doppelte Area-Bindings werden abgewiesen;
- keine partielle Übertragung nach Validierungsfehler;
- geordnete Jobs bleiben geordnet;
- `vacuum_and_mop` wird nur bei bestätigter Capability gesendet;
- Commit-Ergebnisse werden korrekt normalisiert;
- Timeout und temporäre Nichtverfügbarkeit beschädigen den Ledger nicht;
- Neustart/Observation führt nie zu blindem Doppelstart;
- fremde/manuelle Läufe werden als Interferenz behandelt;
- Adapter schreibt nicht selbst in Domainstore oder HA-Entities.

## Initiale Adapterreihenfolge

1. nativer `vacuum.clean_area`-Pfad als herstellerneutraler Baseline-Adapter;
2. Dreame/Mova für Modus, Sequenz und Telemetrie;
3. Eufy anhand verfügbarer öffentlicher HA-Funktionen;
4. weitere Adapter nur nach Contract-Test und dokumentiertem Payoff.

Markenpriorität ist Roadmap, nicht Teil des öffentlichen Contracts.
