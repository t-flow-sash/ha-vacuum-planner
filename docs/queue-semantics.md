# Queue- und Block-Semantik

## Begriffe

- **Plan:** dauerhafte Regeln pro HA-Area.
- **Snapshot:** unveränderliche Auswertung einer Planrevision zu einem Zeitpunkt.
- **Block:** geordnete Jobmenge aus einem Snapshot.
- **Job:** atomare fachliche Raumaufgabe `vacuum` oder `vacuum_and_mop`.

- **Ledger:** autoritative persistente Plannerqueue.
- **Robot Queue:** externe Geräte-/Herstellerqueue, falls vorhanden.

## Garantien

### Planner-Persistenzgrenze (verbindlich)

Bei jedem Aufruf von `start_next` geschieht innerhalb einer Serialisierungsgrenze:

1. fällige Aufgaben berechnen und validieren;
2. genau die nächste Aufgabe auswählen;
3. für diese eine Aufgabe `block_id`, Job-ID und Snapshot erzeugen;
4. den Ein-Job-Block als `sealed` atomar persistieren;
5. erst danach den externen Commit starten.

Die öffentliche Beta materialisiert pro `start_next` genau eine nächste fällige Aufgabe. Sie verspricht weder die Materialisierung eines kompletten Tagesplans noch einen Mehrraum-Commit. In die Queue gelangen ausschließlich fällige Planaufgaben.

### Robot-Atomizität (capability-abhängig)

Nur ein Adapter mit `atomic_device_commit` dürfte eine unteilbare Übernahme in eine Gerätequeue bestätigen. Der ausgelieferte Standardpfad gibt für den einzelnen Job keine weitergehende Gerätequeue-Garantie ab; Serviceannahme ist insbesondere kein Reinigungserfolg.

## Persistenzschema

### QueueLedger

| Feld | Bedeutung |
|---|---|
| `schema_version` | Storage-Migration |
| `revision` | monoton steigende Queue-Revision |
| `blocks` | geordnete Blockreferenzen |
| `active_block_id` | aktuell ausgeführter Block |
| `last_reconciled_at` | Recovery/Audit |

### QueueBlock

| Feld | Bedeutung |
|---|---|
| `block_id` | stabile UUID |
| `kind` | ausschließlich `scheduled` |
| `lane_id` | ausführender Roboter |
| `plan_revision` | Quellrevision |
| `idempotency_key` | Deduplizierung des Startaufrufs |
| `created_at`, `sealed_at`, `committed_at`, `completed_at` | Auditzeiten |
| `state` | Blockzustand |
| `job_ids` | unveränderliche Reihenfolge |
| `dispatch_strategy` | `native_batch`, `planner_sequential`, `device_queue` |
| `adapter_run_id` | optionale externe Korrelation |
| `guarantee` | `planner_atomic` oder `robot_atomic` |

### QueueJob

| Feld | Bedeutung |
|---|---|
| `job_id` | stabile UUID |
| `block_id` | Elternblock |
| `area_id` | native HA-Area-ID |
| `area_name_snapshot` | Anzeige/Audit, nicht Identität |
| `adapter_target_snapshot` | beim Sealing aufgelöstes Ziel |
| `mode` | `vacuum` oder `vacuum_and_mop` |
| `position` | Position im Block |
| `state` | Jobzustand |
| `attempt` | Dispatchversuch |
| `adapter_token` | optionale Run-/Task-Korrelation |
| `planned_at`, `sent_at`, `started_at`, `finished_at` | Auditzeiten |
| `error_code`, `error_detail` | normalisierter Fehler |

## Blockzustandsautomat

```text
draft -> validating -> sealed -> committing -> committed -> running -> completed
              |          |          |            |          |
              v          v          v            v          v
            rejected   cancelled  failed       uncertain   partial/failed
```

- `draft` ist rein lokal und nicht im sichtbaren Ledger.
- `sealed` bedeutet: Plannerblock vollständig und unveränderlich persistiert.
- `committed` bedeutet: Adapter hat den Auftrag akzeptiert; die tatsächliche Robot-Atomizität folgt separat aus `guarantee`.
- `uncertain` bedeutet: Externer Seiteneffekt kann stattgefunden haben, ist aber nicht sicher korrelierbar.
- `partial` ist nur nach tatsächlichen gemischten terminalen Jobresultaten erlaubt.

## Jobzustandsautomat

```text
pending -> dispatching -> accepted -> running -> completed
             |              |          |
             v              v          v
           failed        uncertain   failed
pending -> skipped/cancelled
accepted/running -> cancelled (nur nach bestätigtem Adapterresultat)
```

### Invarianten

1. Reihenfolge und Jobs eines `sealed` Blocks werden nicht mutiert.
2. Jobs entstehen ausschließlich aus fälligen Plänen.
3. `last_completed_vacuum*` wird ausschließlich nach `completed` aktualisiert.
4. Versand/Akzeptanz ist kein Reinigungserfolg.
5. `vacuum_and_mop` erfüllt bei Erfolg zugleich die Saugfälligkeit.
6. `uncertain` wird niemals automatisch als Erfolg gewertet.
7. Retry verwendet dieselbe Job-ID, erhöht `attempt` und setzt eine idempotente Adapterkorrelation, sofern möglich.
8. Kein partielles Sealing: Ein ungültiges Mapping oder ein unzulässiger Modus weist den gesamten Block vor Commit ab.

## Startprotokoll

### Interne Materialisierung durch `start_next`

Unter Lane-Lock:

1. vorhandenen offenen Block mit gleichem Idempotency-Key zurückgeben;
2. einen offenen Block derselben Lane mit anderem Key mit `LaneAlreadyOpenError` ablehnen;
3. Snapshot berechnen und validieren;
4. leeren Snapshot als `no_work` melden, ohne Block zu erzeugen;
5. aus `jobs[:1]` genau eine nächste fällige Aufgabe materialisieren;
6. den Ein-Job-Block versiegeln und synchron atomar speichern;
7. Adaptercommit für diesen Job ausführen;
8. Ergebnis persistieren (`committed`, `failed` oder `uncertain`).


## Dispatch-Strategien

### `native_batch`

Im ausgelieferten Live-Pfad der Beta der Dispatch-Strategiewert für den einzelnen von `start_next` materialisierten Job. Der Name begründet keinen öffentlichen Mehrraumvertrag und keine Robot-Atomizität.

### `planner_sequential`

Im Dry-run verwendeter Strategiewert. Da `start_next` nur einen Job materialisiert, behauptet die Beta damit keine selbsttätige Abarbeitung mehrerer Räume.

### `device_queue`

Im Domainmodell reservierter Strategiewert. Der öffentliche Beta-Pfad wählt ihn nicht und dokumentiert daher keine daraus abgeleitete Gerätequeue-Funktion.

### Gesamtflächen-Fallback

Kein Raumblock: Ein aggregierter Whole-home-Job in sichtbar eingeschränktem Modus. Ausgewählte Areas dürfen nicht als einzeln erledigt dargestellt werden.

## Nebenläufigkeit

- ein `asyncio.Lock` pro Robot Lane schützt jede Mutation und Commitentscheidung;
- ein kurzer Ledger-Lock schützt lane-übergreifende Revisionen;
- alle Buttons, Actions, Worker- und Adaptercallbacks laufen über den Coordinator;
- One-Tap ist idempotent;
- direkte Hersteller-/Vacuum-Services liegen außerhalb dieses Locks und werden soweit möglich als `external_interference` erkannt;
- mehrere Lanes dürfen parallel arbeiten.

## Recovery

Beim Setup:

1. Store laden, migrieren und Schema prüfen;
2. Adapter/Entity/Area-Bindings validieren;
3. `committing`, `committed` und `running` gegen Queue-/Run-ID und Vacuumzustand abgleichen;
4. sicher korrelierte Runs fortsetzen;
5. eindeutig nicht versandte Jobs wieder freigeben;
6. bei uneindeutiger Korrelation den ganzen Block und alle extern aktiven Jobs konsistent auf `uncertain` setzen; noch nicht versandte `pending`-Jobs bleiben ausführbar, sobald alle Unsicherheiten des Blocks einzeln aufgelöst sind;
7. Repair/Recovery-Flow mit Benutzerentscheidung anbieten;
8. nie blind erneut senden.

„Exactly once“ gegenüber externen Geräten wird nicht garantiert. Ziel sind idempotente Planner-Aufrufe und „at most once retry unless safely correlated“.

## Fortschrittsprojektion

- `per_area_progress`: Jobs werden einzeln `completed` und grau.
- nur globaler Abschluss: keine erfundenen Zwischenstände; alle Jobs erst nach Gesamtabschluss abschließen.
- unklare Korrelation: `uncertain`, keine Zeitstempelaktualisierung.
- Dashboard zeigt ausschließlich tatsächlich materialisierte Queue-Jobs; nie ungeplante Räume.
