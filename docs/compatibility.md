# Home Assistant: Kompatibilitätsmatrix für herstellerunabhängige Saugplanung

**Recherche-Stand:** 16. September 2026
**Referenzversion:** Home Assistant Core **2026.9.2**
**Ziel:** belastbare technische Grundlage für ein privates, herstellerunabhängiges GitHub-Projekt. Der Planner soll primär `vacuum.*` und Home-Assistant-Areas verwenden; Herstellerdienste, MQTT-Payloads und Buttons sind Adapter/Fallbacks.

> **Wichtige Abgrenzung:** Dies ist eine statische Quellenauswertung, kein Hardware-Labortest. „Verifiziert“ bedeutet: in offizieller HA-Dokumentation, HA-Core-Quellcode oder im jeweiligen Upstream-Repository belegt. Es bedeutet nicht, dass jede Modell-/Firmwarekombination praktisch getestet wurde.

## Kurzfazit

1. **Die neue tragfähige Abstraktion ist `vacuum.clean_area`.** HA ordnet vom Roboter gemeldete Segmente einmalig HA-Areas zu und ruft danach mit `cleaning_area_id` herstellerneutral auf. In Core 2026.9.2 implementieren das mindestens **Roborock, Ecovacs, Matter und MQTT Vacuum**. [S1–S3]
2. **`vacuum.*` definiert keine universelle Job-Queue und keine universellen Raumprofile.** Eine geordnete Area-Liste ist möglich, aber die tatsächliche Reihenfolge bleibt integrations-/firmwareabhängig. Zuverlässige Sequenzen, Retry, Abbruch und Wiederaufnahme gehören deshalb in den Planner.
3. **Beste unmittelbare Zielplattformen:**
   - **Native-Area-Pfad:** Roborock Core, Ecovacs Core, Matter RVC und Valetudo über MQTT; außerdem aktuelle Dreame/Mova-, Eufy- und Narwal-Custom-Integrationen, sofern die konkrete Entity `CLEAN_AREA` meldet.
   - **Vendor-Segment-Pfad:** Xiaomi Miio sowie ältere oder modellabhängig eingeschränkte Integrationsstände ohne `CLEAN_AREA`.
   - **Ganzflächen-Pfad:** Roomba, SwitchBot, SharkIQ, Miele/LG und Altgeräte mit nur Ganzflächensteuerung.
4. **Karten sind nicht die Planungs-API.** Karte/Camera/Image ist UI/Diagnostik. Die stabile Planungsidentität ist `HA Area ID -> Integration-Segment-ID`, nicht Pixelkoordinate, Kartenname oder Entity-Name.
5. **Lokale Steuerung und Funktionsumfang sind getrennte Achsen.** Valetudo ist am cloudärmsten, verlangt aber Rooting und modellabhängige Installationswege. Roborock ist für Befehle lokal, Karten/Routinen bleiben offiziell cloudabhängig. Ecovacs ist standardmäßig Cloud Push, kann aber gegen eine selbst gehostete Bumper-Instanz konfiguriert werden. [S4, S8, S10]
6. **Neato ist kein sinnvoller Neuentwicklungs-Target mehr:** neue Integrations-Setups sind wegen des abgeschalteten Developer Network nicht mehr möglich; bestehende Setups laufen nur bis zum endgültigen Cloud-Ende. [S12]

---

## 1. Verifizierter Home-Assistant-Vertrag

### 1.1 Offizielle `vacuum`-Actions

In HA Core 2026.9.2 sind für State-Vacuums folgende standardisierte Features/Actions relevant: `start`, `pause`, `stop`, `return_to_base`, `locate`, `clean_spot`, `set_fan_speed`, `send_command` sowie neu `clean_area`. Die Zustände sind `cleaning`, `docked`, `idle`, `paused`, `returning`, `error`. [S1, S2]

`vacuum.clean_area` erhält:

```yaml
action: vacuum.clean_area
target:
  entity_id: vacuum.robot
data:
  cleaning_area_id:
    - kitchen
    - living_room
```

Die Integration meldet Segmente als `{id, name, optional group}`. Der Benutzer mappt diese im Entity-Dialog auf HA-Areas. HA übersetzt die Area-Liste intern in Segment-IDs, dedupliziert bei erhaltener Reihenfolge und ruft `async_clean_segments()` der Integration auf. Nicht gemappte Areas verursachen einen Validierungsfehler. Änderungen der Robotersegmente können eine HA-Repair-Warnung auslösen. [S1–S3]

### 1.2 Was der Standard **nicht** liefert

Verifiziert **nicht** Teil des generischen Vacuum-Vertrags:

- persistente Queue/Jobliste;
- garantiert eingehaltene Segmentreihenfolge;
- pro Raum Saugstufe, Wassermenge, Reinigungsmodus oder Wiederholungen;
- Kartenabruf/-bearbeitung;
- Dock-Sonderaktionen (Moppwäsche, Trocknung, Entleerung);
- universelle „letzte Reinigung pro Raum“-Historie;
- standardisierte Fehlercodes über den Zustand `error` hinaus.

`vacuum.send_command` ist zwar standardisiert aufrufbar, sein `command`/`params`-Inhalt ist ausdrücklich herstellerspezifisch. Es ist damit ein Transport-Fallback, keine portable Semantik. [S1]

### 1.3 Konsequenz für dieses Projekt

**Fast path:** `vacuum.clean_area` verwenden, wenn das Entity das Feature `CLEAN_AREA` meldet und ein Area-Mapping existiert.
**Fallback:** Herstelleradapter übersetzt HA-Areas in Segment-/Raum-IDs.
**Minimal path:** bei Geräten ohne Räume nur `vacuum.start` anbieten und Raumpläne als „nicht ausführbar“ markieren, statt stillschweigend das ganze Stockwerk zu reinigen.

---

## 2. Kompatibilitätsprofile

Die Kürzel in dieser Recherche beschreiben **Plattform-/Planungsfähigkeit**, nicht Qualität, Datenschutz oder Produktpreis. Sie sind nur eine Markt-Matrix-Kurzform. Der öffentliche Planner-Vertrag verwendet stattdessen die feinere, autoritative Capability-Matrix aus [Capability- und Adaptermodell](capabilities.md).

| Profil | Mindestfähigkeit | Planner-Verhalten | Typische Plattformen |
|---|---|---|---|
| **A3 – Native Areas + Profile/Order Extensions** | `vacuum.clean_area`, gemeldete Segmente; zusätzlich dokumentierte Raumparameter/Reihenfolge | Native Areas zuerst; optionaler Profiladapter | Dreame HACS, Valetudo MQTT; teilweise Narwal/Eufy Custom |
| **A2 – Native Areas** | `vacuum.clean_area` und HA-Area-Mapping | Kein Herstellerdienst für normalen Raumstart | Roborock Core, Ecovacs Core, Matter RVC, MQTT Vacuum |
| **B1 – Vendor Segments** | Raum-/Segmentreinigung nur über Custom-Service, `send_command`, Button oder MQTT | Expliziter Adapter; IDs inventarisieren und validieren | Xiaomi Miio; ältere Integrationsstände; Shark2MQTT |
| **C0 – Whole-floor only** | Start/Pause/Stop/Dock, keine belastbaren Räume | Nur Ganzflächenjobs | Roomba Core, SwitchBot Core, SharkIQ Core, Miele, LG ThinQ |
| **D0 – Legacy/EOL** | Setup oder Backend nicht mehr nachhaltig | Read-only/Best-Effort, kein neues Target | Neato Cloud |

**Orthogonale Deployment-Achse:** `local-only` / `local after cloud bootstrap` / `hybrid` / `cloud`. Diese darf nicht in den Capability-Tier eingerechnet werden.

---

## 3. Kompatibilitätsmatrix

Legende: **Ja** = explizit belegt; **Teilw.** = modell-/firmware-/konfigurationsabhängig; **Nein** = Quellcode/Docs bieten die Funktion nicht; **?** = nicht belastbar dokumentiert.
„Queue“ meint eine belastbare, über mehrere Räume/Jobs steuerbare Reihenfolge — nicht nur „mehrere IDs in einem Request“.

| Plattform / Integrationspfad | Installation / Wartung | Standard-`vacuum.*` | Raum/Segment | Queue / Reihenfolge | Karte / Raumdaten | Steuerpfad | Tier | Hauptrisiken |
|---|---|---|---|---|---|---|---|---|
| **Roborock** | **Core** `roborock`, Silver Quality | Start/Pause/Stop/Dock/Locate/Fan/Spot/Send + **`clean_area`** | **Ja, nativ**; Segmente aus Kartenräumen | Mehrere Segmente in einem Aufruf; **keine universelle Queue-Garantie**. App-Routinen erscheinen als Buttons | Live-Map als Image, Räume/Map-Auswahl; Map und Routinen immer Cloud | **Hybrid:** Befehle/Polling lokal bevorzugt, Cloud für Setup/Fallback; Map/Routinen Cloud | **A2** | Cloudausfall betrifft Map/Routinen; Q-Serie modellabhängig; Port 58867/LAN-Erreichbarkeit [S4, S5] |
| **Dreame / Mova** | **HACS Default** `Tasshack/dreame-vacuum`, v1.0.11; kein Core-Pfad | Basis-Actions + `send_command`; aktueller Code implementiert **`CLEAN_AREA`** | **Ja**; nativer HA-Area-Pfad plus `dreame_vacuum.vacuum_clean_segment` | Herstellerdienst `vacuum_set_cleaning_sequence`; Raumparameter via `vacuum_set_custom_cleaning`; Geräte können Parameter ignorieren, wenn Custom-Cleaning/Sequence-Schalter anders gesetzt sind | Umfangreiche Live-/Multi-Floor-Map, Räume, Editierdienste; Mapdaten teils Cloud | **Hybrid/konfigurationsabhängig**; Manifest klassifiziert `cloud_polling`; lokale Befehle möglich, Maps haben Cloudpfade | **A3** | Reverse Engineering, HACS-Code mit HA-Rechten, Cloud-/Firmwarebruch; veröffentlichte Geräteliste nennt bei MOVA nur L600/Z500 — neue MOVA-Modelle vor Kauf/Release prüfen [S6, S7] |
| **Valetudo** | Robotseitige Software + HA Core MQTT; Map-Card optional über HACS | MQTT Vacuum liefert Basis-Actions; aktuelles Autodiscovery setzt `clean_segments_command_topic`, damit HA **`clean_area`** anbietet | **Ja, nativ über MQTT**; direkte Capability ebenfalls verfügbar | Payload unterstützt `segment_ids`, `iterations`, `customOrder`; **nicht jede Firmware unterstützt `customOrder`**. Mehrjob-Queue bleibt Planner-Aufgabe | Raw Map + Segments über MQTT; Valetudo Map Card optional | **Lokal-only** nach erfolgreicher Valetudo-Installation | **A3** | Rooting/Installation modellabhängig, Brick-/Garantie-/Update-Risiko; Projekt bewusst selektiv bei Support; MQTT absichern [S8–S10] |
| **Xiaomi Miio / Mi Robot Vacuum** | **Core** `xiaomi_miio` | Basis-Actions inkl. `send_command`; **kein `CLEAN_AREA` im Core-Entity** | **Ja, aber vendor-spezifisch:** `xiaomi_clean_segment`, `xiaomi_clean_zone` bzw. `app_segment_clean` | Mehrere Room-IDs möglich; keine belastbare persistente Queue | Core liefert keine moderne Karte; optional Xiaomi Cloud Map Extractor / Xiaomi Vacuum Map Card | **Local Polling** mit Gerätetoken; Cloud ggf. zur Tokenbeschaffung/Map-Extraktion | **B1** | Token-Handling, Modell-/Command-Dialekte, Segment-IDs manuell; Cloud Map Extractor zusätzlicher Cloud-/Custom-Code [S11] |
| **Ecovacs / Deebot** | **Core** seit 2024.2; altes `Deebot-4-Home-Assistant` ist archiviert und verweist auf Core | Basis-Actions + `send_command`; aktuelle Modelle erhalten **`clean_area`** bei Map-/Room-Support | **Ja, nativ modellabhängig**; Segmente mapübergreifend gemeldet, gereinigt wird nur aktive Map | Mehrere Räume im Auftrag; keine allgemeine Queuegarantie | SVG-Map, aktive Map, Raumdaten; je Modell | Standard **Cloud Push**; HA unterstützt alternativ selbst gehosteten Server (Bumper) | **A2** | Undokumentierte/reverse-engineerte API; Modellunterstützung communityabhängig; Bumper ist eigener Betriebs-/Security-Stack [S13, S14] |
| **Eufy RoboVac (Damacus)** | **HACS Custom Repo** `damacus/robovac`; Stable v2.4.3, aktiver Nachfolger von CodeFoodPixels | Basis-Actions; **Stable v2.4.3 hat noch kein `CLEAN_AREA`**. Der geprüfte, unveröffentlichte `main`-Stand schaltet es bei vorhandenen Raumsegmenten frei | **Teilw./modellabhängig**; 30+ Modelle, Room Discovery derzeit explizit u. a. T2320; manueller Segment-Fallback im Entwicklungsstand | Mehrere Room-IDs + Count im Adapter; Reihenfolge nicht als garantiert dokumentiert | Raum-Metadaten modellabhängig; keine belastbar universelle Live-Map-Aussage | **Lokal nach Cloud-Login/Key-Bootstrap** | **A2 erst mit passendem Entwicklungsstand, sonst B1** | Release-/Main-Differenz; sehr breites Tuya-Protokollspektrum 3.3–3.5; Cloudzugang für Keys/Room-Fallback; Modellregressionen; Custom-Code [S15] |
| **Eufy S1 Pro Spezialintegration** | HACS Custom `tkoba1974/ha-eufy-robovac-s1-pro` | Basissteuerung, Modi/Wasser/Saugstufe | **Nein:** Upstream dokumentiert Room Cleaning lokal als nicht implementierbar/geplant | Nein | Keine Raum-/Mapverwaltung lokal | **Lokal nach einmaligem Eufy-Login** | **C0** | Modell-Silo; Cloud/P2P enthält Raumdaten; Wartungsreset fehlt; nicht mit allgemeiner Eufy-Unterstützung gleichsetzen [S16] |
| **iRobot Roomba / Braava** | **Core** `roomba` | Start/Pause/Stop/Dock/Locate/Send, modellabhängig Fan | **Nein im Core** (`CLEAN_AREA` fehlt) | Nein | Core-Integration stellt keine planbare Raumsegment-API bereit | **Local Push/MQTT**; Credentials lokal, bei manchen neueren Modellen nur über Cloud-Tool beschaffbar | **C0** | Roboter-MQTT erlaubt nur **eine** Verbindung; App-Konflikt; neue x05-Modelle 105/405/505 ausdrücklich nicht unterstützt [S17, S18] |
| **Neato Botvac** | **Core**, aber Neuanlage nicht mehr möglich | Basissteuerung/Spot/Map-Feature | Keine native HA-Area-Reinigung | Nein | Letzte Cleaning Map (Camera) | **Cloud Polling** | **D0** | Neato Cloud wird eingestellt; Developer Network weg; bestehende Installationen nur bis Shutdown [S12] |
| **Matter Robot Vacuum Cleaner** | **Core Matter** + Matter Server | Start/Stop/Pause/Dock/Locate je Cluster; **`clean_area`**, wenn Gerät Areas meldet | **Ja, nativ**, geräteabhängig | Area-ID-Liste; keine Queue-/Profilgarantie | Cleanable Areas, aber kein herstellerspezifischer Kartenersatz | **Local Push**, ohne Cloud steuerbar | **A2** | Noch heterogene Geräteimplementierungen; Matter bietet weniger Tiefe als Hersteller-API; IPv6/mDNS/VLAN-Anforderungen [S19] |
| **SwitchBot K/S-Serie** | **Core** `switchbot` | Aktuell nur Start/Dock/State im Vacuum-Entity | **Nein** | Nein | Keine Planner-Raum-API | **Local Push**, Account-Sync für nicht lokal entdeckbare Geräte nötig | **C0** | Sehr schmale HA-Funktion; K10/K10 Pro melden nur `cleaning`/`docked`; Bluetooth-/Account-Discovery [S20] |
| **Shark IQ** | **Core** `sharkiq` | Start/Pause/Stop/Dock/Locate/Fan | **Nein im Core** | Nein | Keine Planner-Raum-API | **Cloud Polling** | **C0** | Cloud/API-Abhängigkeit; Pause modellabhängig [S21] |
| **Shark via `shark2mqtt`** | Externer Docker-/HAOS-Add-on-Bridge + MQTT | Basis-Vacuum per MQTT | Raum-Buttons; Multiroom über `vacuum.send_command` | Mehrere Räume in einem Custom-Command, kein Standard-`clean_area` belegt | Room-Daten aus Shark Cloud, keine universelle HA-Map | **Cloud-Bridge**; Auth0/Chromium-Login | **B1** | 1,2-GB-Image, Browserautomation, Cloudflare/Account-Lock-Risiko, Secrets/Refresh-Token [S22] |
| **Narwal (Community)** | HACS Custom `sjmotew/NarwalIntegration`, v1.0.10 | Basis-Actions; **`vacuum.clean_area` ab HA 2026.3+** laut Upstream | **Ja**, nur Modelle mit lokalem WS-Port 9002; nicht alle Narwal-Serien | Mehrere Räume in einem Lauf auf Flow hardwareverifiziert; kein allgemeiner Queuevertrag | Live Map, Raumlabels, Pfad, Einstellungen | **Lokal-only** bei kompatibler Hardware | **A3** | Junges Reverse-Engineering-Projekt; viele modell-/firmwarespezifische Ausnahmen; ältere Releases hatten „erfolgreiche“, aber wirkungslose Raumstarts; alternative Narwal-Repos kollidieren im selben Domain-Namen [S23] |
| **Miele Scout / Robot Vacuum** | **Core** `miele` | Start/Stop/Pause/Fan/Spot, begrenzte Steuerung | Nein | Nein | Keine Planner-Segment-API | **Cloud Push**, Miele CloudService zwingend | **C0** | Drittanbieter-API begrenzt, Cloud/OAuth [S24] |
| **LG ThinQ Robot Cleaner** | **Core** `lg_thinq` | Start/Pause/Dock/Send, State | Nein | Nein | Keine Planner-Segment-API | **Cloud Push**, Internet erforderlich | **C0** | Region-/Cloudabhängigkeit; schmale standardisierte Semantik [S25] |

### Interpretation wichtiger Sonderfälle

- **Dreame/Mova:** Für das Projekt ist `Tasshack/dreame-vacuum` der technisch relevante Hauptadapter. Die README-Geräteliste ist jedoch sichtbar älter/enger als der Markt. Daher gilt: *Integration vorhanden* ist verifiziert, *konkretes neues MOVA-Modell unterstützt* erst nach Eintrag in Upstream-Liste/Issue oder Hardwaretest. Ein sehr junges alternatives Repo wie `David-lllwyz/MOVA-Vacuum-HA` (P60 self-reported) sollte wegen geringer Reife nicht Default werden.
- **Eufy:** „Eufy unterstützt Räume“ ist keine markenweite Aussage. Bei Damacus Stable v2.4.3 fehlt `CLEAN_AREA`; der geprüfte, noch unveröffentlichte `main`-Stand enthält nativen HA-Area-Code für vorhandene Segmente. Die separate S1-Pro-Lokalintegration dokumentiert Raumreinigung explizit als unmöglich. Capability daher immer an der tatsächlich installierten Entity erkennen, nie am Logo oder Repository-Namen.
- **Valetudo:** Ältere Anleitungen nennen für Segmente direkt `mqtt.publish`. Der aktuelle Valetudo-Code publiziert jedoch `clean_segments_command_topic` und Segmentattribute für HA MQTT Vacuum; damit ist auf aktuellem Stand der native `vacuum.clean_area`-Pfad möglich. Direkte MQTT-Payloads bleiben nur für `iterations`/`customOrder` nötig. [S9]
- **Deebot:** Das frühere HACS-Repo ist archiviert, weil die Integration in Core übernommen wurde. Kein neues Projekt sollte die archivierte Custom Component installieren. [S14]

---

## 4. Adapteranforderungen

### 4.1 Empfohlener Kernvertrag

```text
VacuumAdapter
  probe(entity_id) -> CapabilitySnapshot
  start_whole(options?)
  start_areas(ha_area_ids[], options?) -> JobHandle
  pause() / resume() / stop() / dock()
  observe() -> NormalizedVacuumState
  optional get_rooms() -> RoomDescriptor[]
  optional set_room_profiles(profiles[])
  optional start_zones(zones[])
```

`CapabilitySnapshot` sollte mindestens enthalten:

```yaml
native_clean_area: true|false
ordered_multi_area: verified|best_effort|false
per_room_profile: true|false
map_available: true|false
control_path: local|local_after_bootstrap|hybrid|cloud
integration_domain: roborock
integration_version: 2026.9.2
adapter_version: 1
```

### 4.2 Dispatch-Reihenfolge

1. Entity vorhanden und verfügbar prüfen.
2. Laufenden Job/Robotzustand prüfen; nie blind einen zweiten Start senden.
3. Wenn `CLEAN_AREA`: `vacuum.clean_area` mit HA Area IDs.
4. Sonst passender Adapter:
   - Dreame: `dreame_vacuum.vacuum_clean_segment`;
   - Xiaomi: `xiaomi_miio.vacuum_clean_segment` oder dokumentierter `vacuum.send_command`;
   - Valetudo-Sonderoptionen: `mqtt.publish` nur für Iterationen/Custom Order;
   - Shark2MQTT: `vacuum.send_command clean_rooms`;
   - button-only: gezieltes `button.press`, aber nur als klar markierter schwacher Adapter.
5. Fehlt ein Raumadapter: Job **nicht** zu Ganzflächenreinigung degradieren; als `unsupported` melden.
6. Nach Start den realen Vacuum-State mit Timeout verifizieren; ein erfolgreicher Service-Call ist noch kein gestarteter Roboter.

### 4.3 Queue-/Sequenzmodell

Die Queue muss herstellerneutral im Planner liegen:

```text
PENDING -> DISPATCHING -> RUNNING -> SUCCEEDED
                     \-> RETRY_WAIT -> DISPATCHING
                     \-> BLOCKED / FAILED / CANCELLED
```

Empfehlungen:

- **Ein Job = ein atomarer HA-Area-Satz.** Räume mit identischem Profil dürfen gebündelt werden.
- Unterschiedliche Profile als getrennte Jobs ausführen, sofern der Adapter keine verifizierten Mixed-Room-Profile unterstützt.
- Reihenfolge erst als `verified` markieren, wenn Integration **und konkrete Firmware** sie belegen; sonst `best_effort`.
- Dock-/Ladeunterbrechung nicht als Erfolg interpretieren. `returning`/`docked` kann Zwischenzustand einer Fortsetzung sein.
- Idempotency-Key und Launch-Timestamp persistieren; nach HA-Neustart Zustand rekonstruieren statt erneut starten.
- Segment-/Area-Mapping-Änderungen als Blocker behandeln und HA-Repair-Hinweis sichtbar machen.

### 4.4 Raumidentität

Canonical ID im Projekt:

```text
HA area_id
  -> adapter binding
     -> integration entity_id
     -> current segment_id(s)
     -> map/floor scope
```

Nicht als dauerhafte Schlüssel verwenden: freundliche Raumnamen, Kartenindex (`map_2`), Pixelkoordinaten oder reine Segmentnummer ohne Geräte-/Map-Scope. Dreame dokumentiert ausdrücklich, dass Map-IDs/Indizes sich durch Löschen/Ersetzen verändern können. [S7]

---

## 5. Karten- und UI-Strategie

| Zweck | Empfehlung |
|---|---|
| Scheduling/Entscheidung | HA Areas + Planner-Daten; keine Karte erforderlich |
| Raum-Mapping | Native HA-Funktion „Map vacuum segments to areas“ |
| Roborock/Ecovacs | Core Image-Entity bevorzugen |
| Dreame/Mova | Integrationseigene Camera/Image/Map-Daten; Xiaomi Vacuum Map Card nur als UI-Option |
| Valetudo | `lovelace-valetudo-map-card` über HACS, MQTT-Mapdaten |
| Xiaomi Miio ohne Map | Optional Xiaomi Cloud Map Extractor + Xiaomi Vacuum Map Card; klar als Cloud-/Custom-Abhängigkeit deklarieren |

Die **Xiaomi Vacuum Map Card** ist ein UI-Adapter mit Templates für zahlreiche Plattformen, aber kein Scheduling-Backend. Ein Ausfall/Breaking Change der Karte darf den Planner nicht stoppen. [S26]

---

## 6. Wartungs- und Sicherheitsmodell

### 6.1 Prioritätsregeln

1. **Core vor HACS**, sofern Core dieselbe notwendige Capability bietet.
2. **Native `clean_area` vor Vendor-Service**, weil HA Area-Mapping und Repairs übernimmt.
3. **Lokal vor Cloud**, aber nicht auf Kosten eines unwartbaren Root-/Bridge-Stacks ohne Betreiberbereitschaft.
4. Custom-Repos versionieren/pinnen, Release Notes lesen und nach HA-Updates in einer Testinstanz prüfen.
5. Credentials niemals in Planner-Logs/Issues; Diagnosedaten vor Veröffentlichung auf Tokens, DSN, Room-Namen, Map-URLs und IPs prüfen.

### 6.2 Risikoklassen

| Klasse | Beispiele | Maßnahmen |
|---|---|---|
| **Core + lokal** | Matter, Roomba, SwitchBot; Roborock teilweise | normale HA-Update-Tests; Netzwerksegmentierung; lokale Ports nur HA erlauben |
| **Core + Cloud/hybrid** | Roborock Map, Ecovacs, SharkIQ, Miele, LG | Cloudausfall/Rate-Limit als `degraded`; keine Endlosschleifen; Reauth sichtbar |
| **HACS Custom Component** | Dreame, Eufy, Narwal | Code läuft im HA-Prozess; Repo/Owner/Release prüfen, Version pinnen, Backups, schnelle Deaktivierung ermöglichen |
| **Externe Bridge** | shark2mqtt, Bumper | Container/Add-on härten, Secrets/Volumes schützen, Egress einschränken, Ressourcen/Health überwachen |
| **Robot Rooting** | Valetudo | exakte Modell-/Firmware-Anleitung, Recovery-Pfad, Update-Sperren verstehen, Risiko bewusst akzeptieren |
| **EOL Cloud** | Neato | Migration planen; keine neuen Features investieren |

### 6.3 Datenschutz

Vacuum-Karten können Grundriss, Raumbezeichnungen, Hindernisse und Anwesenheitsmuster enthalten. Deshalb:

- Map-Entities nicht öffentlich freigeben;
- keine Karten/Diagnosedumps ungeprüft an Issues anhängen;
- MQTT mit Auth/ACL, idealerweise TLS außerhalb eines vertrauenswürdigen LAN;
- Planner-Historie auf notwendige Metadaten begrenzen;
- Cloud-Map-Extractor als separate, explizit aktivierte Abhängigkeit behandeln.

---

## 7. Empfehlung für die Implementierung

### Phase 1 — Entwicklung nicht blockieren

- Generischen Adapter für `vacuum.start/pause/stop/return_to_base` bauen.
- Feature-Probe für `CLEAN_AREA` und nativen `vacuum.clean_area`-Adapter implementieren.
- Eigene persistente Queue, Timeouts, Statusnormalisierung und Dry-Run hinzufügen.
- Unsupported Areas hart und sichtbar ablehnen.
- Tests mit Fake-Adapter/Fixtures; keine Herstellerhardware nötig.

**Payoff:** Deckt Roborock, Ecovacs, Matter, aktuelles MQTT/Valetudo sowie moderne Custom Components ohne Markenlogik ab.

### Phase 2 — High-value Vendor Adapter

1. **Dreame/Mova:** Segmentstart, optionale Sequence/Custom Cleaning; Schalterzustände vor Start prüfen.
2. **Xiaomi Miio:** Segment-Service/`send_command`, manuelles Binding und Modelltests.
3. **Eufy:** Capability-basiert zwischen Damacus-Area, vendor room und whole-floor unterscheiden.
4. **Valetudo Extended:** Iterations/CustomOrder über MQTT, nur wenn benötigt.

**Payoff:** Breite Bestandsgeräte-Unterstützung; höhere Test- und Wartungskosten durch reverse-engineerte Payloads.

### Phase 3 — Long tail

- Shark2MQTT, Narwal, Button-only-Integrationen.
- C0-Plattformen als Ganzflächen-Runner.
- Neato nur Legacy-Kompatibilität, keine neue Investition.

### Kauf-/Plattformempfehlung

Für ein neues herstellerunabhängiges Planner-Projekt ist die Priorität:

1. Gerät/Integration meldet `CLEAN_AREA` und Segmente;
2. lokale Steuerung funktioniert ohne Herstellercloud oder degradiert kontrolliert;
3. Mapping-/Segmentänderungen werden erkannt;
4. Integration ist Core oder aktiv gepflegt;
5. konkrete Modell-/Firmwareunterstützung ist dokumentiert.

Daraus folgen als risikoarme Software-Ziele **Roborock Core** (mit Cloud-Caveat für Maps), **Matter RVC** (wenn konkrete Geräteimplementierung reif ist), **Ecovacs Core** und **Valetudo** für Betreiber, die Rooting bewusst akzeptieren. **Dreame/Mova** bietet den größten Funktionsumfang, hat aber als Custom-/Reverse-Engineering-Stack einen höheren Wartungspreis.

---

## 8. Verifizierte Fakten vs. Annahmen

### Verifiziert

- `vacuum.clean_area` und Segment-zu-Area-Mapping existieren in HA 2026.9.2. [S1–S3]
- Roborock, Ecovacs, Matter und MQTT Vacuum implementieren `CLEAN_AREA` im Core-Code. [S5, S13, S19, S3]
- Xiaomi Miio, Roomba, SwitchBot und SharkIQ implementieren im aktuellen Core-Vacuum-Entity kein `CLEAN_AREA`. [S11, S18, S20, S21]
- Roborock-Mapdaten und Routinen werden immer über die Cloud geladen. [S4]
- Valetudo ist ein lokaler Cloud-Ersatz und publiziert aktuelle HA-MQTT-Discovery-Daten für Segmente. [S8–S10]
- Tasshack/Dreame hat Segment-, Zonen-, Cleaning-Sequence- und Custom-Cleaning-Dienste sowie aktuellen `CLEAN_AREA`-Code. [S6, S7]
- Neato-Neuinstallationen sind nicht mehr möglich. [S12]
- Das alte Deebot-HACS-Repo ist archiviert und wurde in HA Core übernommen. [S14]

### Annahmen / bewusst nicht garantiert

- Eine übergebene Reihenfolge mehrerer HA-Areas wird von jedem Roboter exakt eingehalten. **Nicht garantiert.**
- Jede aktuelle MOVA-/Dreame-Modellvariante funktioniert mit Tasshack. **Nicht belegt; modellweise prüfen.**
- „Lokal“ bedeutet, dass weder Setup noch Map/Key jemals Cloud benötigen. **Je Integration falsch; Deployment-Achse beachten.**
- Ein vorhandenes Map-Image bedeutet steuerbare Räume. **Falsch als allgemeine Annahme.**
- Ein erfolgreich abgeschlossener HA-Service-Call bedeutet, dass der Roboter physisch gestartet ist. **Nicht garantiert; Zustand verifizieren.**
- Hersteller-Apps, Firmwares und reverse-engineerte APIs bleiben stabil. **Nicht garantiert.**

---

## Quellen

Alle Quellcodeaussagen beziehen sich soweit möglich auf HA **2026.9.2** oder auf feste Upstream-Commits.

- **[S1]** HA Core 2026.9.2, Vacuum-Komponente und `clean_area`-Dispatch: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/vacuum/__init__.py>
- **[S2]** Offizielle HA Vacuum-Dokumentation, States und Area-Mapping: <https://www.home-assistant.io/integrations/vacuum/>
- **[S3]** HA Core 2026.9.2, MQTT Vacuum (`segments`, `clean_segments_command_topic`, `CLEAN_AREA`): <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/mqtt/vacuum.py> und <https://www.home-assistant.io/integrations/vacuum.mqtt/>
- **[S4]** Offizielle Roborock-Dokumentation, lokaler Pfad/Cloud-Fallback/Maps: <https://www.home-assistant.io/integrations/roborock/>
- **[S5]** HA Core 2026.9.2, Roborock Segmentimplementierung: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/roborock/vacuum.py>
- **[S6]** Tasshack Dreame Vacuum, README/Installation/Supportliste, Commit `ae8422f`: <https://github.com/Tasshack/dreame-vacuum/tree/ae8422f281716ef064c8cdf14164e8c294afd476>
- **[S7]** Dreame Services und Raum-/Map-Semantik: <https://github.com/Tasshack/dreame-vacuum/blob/ae8422f281716ef064c8cdf14164e8c294afd476/docs/services.md>, <https://github.com/Tasshack/dreame-vacuum/blob/ae8422f281716ef064c8cdf14164e8c294afd476/docs/room_entities.md>, <https://github.com/Tasshack/dreame-vacuum/blob/ae8422f281716ef064c8cdf14164e8c294afd476/custom_components/dreame_vacuum/vacuum.py>
- **[S8]** Valetudo Cloud-Replacement und lokale Architektur: <https://github.com/Hypfer/Valetudo/tree/190816dbe8c45c5f7256ef87ca1ffb04ecb6da78>
- **[S9]** Valetudo HA/MQTT-Integration: <https://github.com/Hypfer/Valetudo/blob/190816dbe8c45c5f7256ef87ca1ffb04ecb6da78/docs/pages/integrations/home-assistant-integration.md> und <https://github.com/Hypfer/Valetudo/blob/190816dbe8c45c5f7256ef87ca1ffb04ecb6da78/backend/lib/mqtt/homeassistant/components/VacuumHassComponent.js>
- **[S10]** Valetudo Segment-Payload, Iterations und `customOrder`: <https://github.com/Hypfer/Valetudo/blob/190816dbe8c45c5f7256ef87ca1ffb04ecb6da78/backend/lib/mqtt/capabilities/MapSegmentationCapabilityMqttHandle.js>
- **[S11]** Offizielle Xiaomi Miio Vacuum-Dokumentation und Core-Code: <https://www.home-assistant.io/integrations/xiaomi_miio/#xiaomi-mi-robot-vacuum>, <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/xiaomi_miio/vacuum.py>
- **[S12]** Offizielle Neato-Dokumentation inklusive Cloud-EOL: <https://www.home-assistant.io/integrations/neato/>
- **[S13]** Offizielle Ecovacs-Dokumentation/Self-hosted Bumper und Core Area-Code: <https://www.home-assistant.io/integrations/ecovacs/>, <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/ecovacs/vacuum.py>
- **[S14]** Archiviertes Deebot Custom Repository mit Core-Hinweis: <https://github.com/DeebotUniverse/Deebot-4-Home-Assistant>
- **[S15]** Damacus RoboVac: Stable v2.4.3 sowie geprüfter `main`-Commit `f31f339` mit unreleased Area-Code, lokale Steuerung und Modelle: <https://github.com/damacus/robovac/tree/f31f339fc753576e2defe75e836a712832e35132>
- **[S16]** Eufy S1 Pro lokale Integration und dokumentierte Raum-Limitierung: <https://github.com/tkoba1974/ha-eufy-robovac-s1-pro/tree/e085361dfffaaa9581b945eceffc229a8584ebf9>
- **[S17]** Offizielle Roomba-Dokumentation, Modell- und MQTT-Limits: <https://www.home-assistant.io/integrations/roomba/>
- **[S18]** HA Core 2026.9.2 Roomba Vacuum: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/roomba/vacuum.py>
- **[S19]** Matter lokal + Core RVC Areas: <https://www.home-assistant.io/integrations/matter/>, <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/matter/vacuum.py>
- **[S20]** SwitchBot Vacuum-Dokumentation/Core-Code: <https://www.home-assistant.io/integrations/switchbot/>, <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/switchbot/vacuum.py>
- **[S21]** SharkIQ Core-Dokumentation/Code: <https://www.home-assistant.io/integrations/sharkiq/>, <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/sharkiq/vacuum.py>
- **[S22]** Shark2MQTT Bridge, Commit `c45fe74`: <https://github.com/CamSoper/shark2mqtt/tree/c45fe7464ec293dc9c0552aeb24fbd18e72ffbd2>
- **[S23]** Narwal Local Integration v1.0.10, Hardwarematrix/Room Cleaning: <https://github.com/sjmotew/NarwalIntegration/tree/1a833fc2f45c2daf7b2a0ed3ea4d1637126b2332>
- **[S24]** Miele Integration / Robot Vacuum: <https://www.home-assistant.io/integrations/miele/#vacuum>
- **[S25]** LG ThinQ Integration / Robot Cleaner: <https://www.home-assistant.io/integrations/lg_thinq/#vacuum>
- **[S26]** Xiaomi Vacuum Map Card v2.4.1: <https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card/tree/045c3ac946d4ef0a01201f306e9949643984a155>
