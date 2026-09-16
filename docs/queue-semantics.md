# Queue- und Block-Semantik

## Begriffe

- **Plan**: dauerhafte Regeln pro Raum.
- **Snapshot**: unveränderliche Auswertung des Plans zu einem Zeitpunkt.
- **Block**: geordnete Menge von Jobs aus demselben Snapshot.
- **Job**: atomare Raumaufgabe mit `vacuum` oder `vacuum_and_mop`.
- **Ad-hoc-Job**: nach dem Tagesblock angehängte spontane Aufgabe.

## Kerninvariante

Sobald der Benutzer den Tagesplan startet, wird aus allen zu diesem Zeitpunkt fälligen Räumen ein unveränderlicher Block erzeugt. Änderungen an Intervallen, Prioritäten oder Skip-Flags verändern diesen laufenden Block nicht. Neue spontane Aufgaben werden hinter dem letzten noch nicht terminalen Job des Blocks eingereiht.

## Datenmodell

### Block

| Feld | Bedeutung |
|---|---|
| `block_id` | stabile UUID |
| `kind` | `scheduled` oder `adhoc` |
| `created_at` | Erzeugungszeitpunkt |
| `started_at` | erster Versand an Adapter |
| `completed_at` | Zeitpunkt, an dem alle Jobs terminal sind |
| `plan_revision` | Revision der Regeln, aus denen der Snapshot entstand |
| `state` | `planned`, `running`, `completed`, `partial`, `cancelled`, `failed` |
| `job_ids` | unveränderliche Reihenfolge |

### Job

| Feld | Bedeutung |
|---|---|
| `job_id` | stabile UUID |
| `block_id` | zugehöriger Block |
| `area_id` | native HA-Area |
| `room_key` | Adapterzuordnung, z. B. Segment-ID |
| `mode` | `vacuum` oder `vacuum_and_mop` |
| `position` | Position im Block |
| `state` | siehe Zustandsautomat |
| `attempt` | Versandversuch |
| `adapter_token` | optionale Hersteller-/Run-Korrelation |
| `planned_at`, `sent_at`, `started_at`, `finished_at` | Audit-Zeitpunkte |
| `error_code` | normalisierter Fehler |

## Job-Zustandsautomat

```text
planned -> dispatching -> dispatched -> running -> completed
                   |           |          |
                   v           v          v
                 failed      unknown    failed
planned/running -> skipped
planned/dispatched/running -> cancelled
```

Regeln:

1. `last_vacuum` und `last_vacuum_and_mop` werden ausschließlich nach `completed` aktualisiert.
2. Ein gesendeter Befehl ist noch kein erfolgreicher Job.
3. Kann nach Neustart nicht sicher ermittelt werden, ob der Roboter den Job ausgeführt hat, wird `unknown` statt `completed` gesetzt.
4. Wiederholungen benutzen dieselbe `job_id` und erhöhen `attempt`; sie erzeugen keine doppelte Historie.
5. Terminale Zustände sind `completed`, `skipped`, `cancelled`, `failed` und nach manueller Klärung `unknown`.

## Versandstrategien

### A — Native Blockübergabe

Der Adapter kann mehrere Räume in definierter Reihenfolge als einen Auftrag senden. Der Planner markiert den Block als `dispatched`, beobachtet aber einzelne Räume nur, wenn die Plattform ausreichende Telemetrie liefert.

### B — Sequentielle Raumjobs

Der Planner sendet jeweils genau einen Raum und startet den nächsten erst nach bestätigtem Abschluss. Das emuliert den Block portabel und ermöglicht saubere Raumhistorie, kann aber zusätzliche Docking-/Statuslatenz verursachen.

### C — Generischer Fallback

Ist keine Raumreinigung verfügbar, kann nur eine Ganzflächenreinigung gestartet werden. Alle ausgewählten Areas werden als ein aggregierter Job dargestellt; eine raumgenaue Erfolgsaussage ist nicht zulässig.

## Ad-hoc-Verhalten

- Während `planned`: Anhängen hinter den Snapshot-Block.
- Während `running`: Anhängen hinter alle bestehenden nichtterminalen Jobs.
- Gleicher Raum und gleicher Modus bereits ausstehend: standardmäßig deduplizieren; UI bietet bewusstes „noch einmal reinigen“ als explizite Aktion.
- Höherwertiger Modus (`vacuum_and_mop`) darf einen noch nicht gesendeten `vacuum`-Job desselben Raums nur nach bestätigter UI-Aktion ersetzen.
- Ein Ad-hoc-Job verändert keine Fälligkeit, bevor er erfolgreich abgeschlossen wurde.

## Nebenläufigkeit

- Eine config-entry-bezogene `asyncio.Lock` schützt alle Queue-Mutationen.
- Persistenz wird nach jeder Zustandsänderung atomar geschrieben.
- Service-/Button-Aufrufe tragen einen Idempotency-Key oder werden im Coordinator dedupliziert.
- Adaptercallbacks dürfen ausschließlich über den Coordinator Zustände ändern.

## Recovery

Nach HA-Neustart:

1. persistierte Queue laden;
2. ausgewählte `vacuum.*`-Entität und Adapter prüfen;
3. Adapterstatus abfragen;
4. `running`/`dispatched` gegen verfügbare Telemetrie abgleichen;
5. sicher zuordenbare Jobs fortsetzen;
6. nicht sicher zuordenbare Jobs auf `unknown` setzen und einen Repair-/UI-Hinweis erzeugen;
7. niemals stillschweigend erneut starten.

## Dashboard-Darstellung

- nur Jobs des aktuellen Tagesblocks und danach angehängte Ad-hoc-Jobs anzeigen;
- `completed`: grau/dezent mit Haken;
- `running`: primäre Akzentfarbe und klarer Fortschrittsstatus;
- `planned`: normal;
- `failed`/`unknown`: Warnfarbe plus konkrete nächste Aktion;
- keine leeren Platzhalter für nicht geplante Räume.
