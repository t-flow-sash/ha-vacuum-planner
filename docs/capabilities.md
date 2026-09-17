# Capability- und Adaptermodell

## Grundsatz

Kompatibilität wird anhand beobachtbarer Fähigkeiten, nicht anhand von Marken, bewertet. Der Core plant identisch; Adapter entscheiden, welche Ausführungsgarantie möglich ist. Eine Tierzahl ist nur eine verständliche Zusammenfassung der Feature-Matrix.

## Capability-Tiers

| Tier | Mindestfähigkeiten | Nutzbarer Modus | Queue-/Blockgarantie | UI-Payoff |
|---|---|---|---|---|
| **T0 – Gesamtfläche** | generisches Start/Pause/Stop | gesamte Fläche, keine Räume | keine Raumblockgarantie | „Raumplanung nicht verfügbar“; optional klar getrennter Gesamtflächenmodus |
| **T1 – Areas** | `CLEAN_AREA`, eindeutiges Area-Mapping, einzelner oder mehrfacher Area-Aufruf | raumbasierte Planung | Planner-Block atomar; Gerät ggf. sequentiell/emuliert | volle Planung, aber eingeschränkte Gerätequeue-/Fortschrittsanzeige |
| **T2 – Batch** | geordneter Mehrraumauftrag und Moduswahl | Saugen und ggf. Saugen+Wischen | ein Geräteauftrag für den Block; Append ggf. nur im Planner | „Tagesblock als ein Auftrag“, Fortschritt abhängig von Telemetrie |
| **T3 – Queue** | atomischer Batch-Commit, echtes Append, Queue-/Run-ID, Introspection | vollständiger Funktionsumfang | Planner- und Roboter-Atomizität belastbar | echte Gerätequeue, Recovery und Fortschritt mit hoher Sicherheit |

### Zwei getrennte Garantien

- **Planner-atomar:** Die Integration persistiert den unveränderlichen Tagesblock in einem Schritt; spätere Jobs stehen garantiert dahinter. Ab T1 lieferbar.
- **Robot-atomar:** Das Gerät bzw. seine Integration bestätigt den kompletten Block als unteilbaren Queue-Auftrag und erlaubt danach Append. Nur ausweisen, wenn Adapter/Contract dies tatsächlich belegt (typischerweise T3).

## Autoritative Capability-Matrix

```text
area_cleaning
ordered_multi_area
mode_vacuum
mode_vacuum_and_mop
atomic_device_commit
append_device_queue
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

Ein Aufruf enthält die geordnete Area-Liste. Das ist bevorzugt, beweist allein aber noch keine transaktionale Gerätequeue.

### `planner_sequential`

Der Planner sendet einen Raum nach bestätigtem Abschluss des vorherigen. Das bewahrt die logische Blockfolge, erzeugt aber keinen physischen Queueblock und kann zusätzliche Dock-/Startlatenz haben.

### `device_queue`

Der Adapter committed den Block atomar, erhält eine Run-/Queue-ID und kann danach Jobs anhängen. Nur diese Strategie darf in der UI als „in Gerätequeue übertragen“ bezeichnet werden.

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
- Commit-/Append-Ergebnisse werden korrekt normalisiert;
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
