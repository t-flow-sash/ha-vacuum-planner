# Release Notes – v0.1.0-beta.1

**Status: unveröffentlichter privater Release-Kandidat.** `v0.1.0-beta.1` benennt das vorbereitete Artefakt; für diesen Stand wurden **kein Tag, kein GitHub-Release, kein Commit und kein Push** erstellt. Es handelt sich nicht um eine Produktions- oder Live-Pilot-Freigabe.

## Installation

Der primäre Beta-Weg ist die autorisierte Copy-Installation aus `vacuum_planner-v0.1.0-beta.1.zip`, authentifiziert aus dem privaten semantischen GitHub-Release bezogen und gegen `SHA256SUMS` geprüft. Solange der Eigentümer diesen privaten Release nicht tatsächlich erstellt hat, können berechtigte Tester das identische Artefakt reproduzierbar mit `scripts/build_release.py` bauen.

Das Repository ist privat und deshalb nicht über HACS installierbar. HACS ist nur eine spätere Option, falls das Repository öffentlich erreichbar wird und Distribution sowie Lizenz ausdrücklich freigegeben sind. Details: [Installation](docs/installation.md).

## Highlights

- vollständiges UI-Onboarding ohne YAML-Konfiguration;
- sicherer Dry-run als Standard;
- persistente Queue mit idempotentem One-Tap und `uncertain`-Recovery;
- universelle Planner-Entities und Actions;
- fail-closed Repairs und redigierte Diagnostics;
- reale `sensor.vacuum_planner_queue`-Projektion mit höchstens 20 sicheren Anzeigeeinträgen;
- importierbares Sections-Dashboard ausschließlich aus Home-Assistant-Standardkarten;
- dynamische Queue-Zustände, Completed klar grau/dezent mit Haken und Text, Touch-Ziele mindestens 48 px;
- deterministisches Release-ZIP und SHA-256-Prüfsumme;
- dokumentierter Backup-, Downgrade- und Entfernungsweg.

## Dashboard

[`dashboard/vacuum-planner.yaml`](dashboard/vacuum-planner.yaml) ist eine vollständige Raw-Konfiguration mit `views` und Sections. Nach einmaliger stabiler Benennung der erzeugten Planner-Entities liest die Markdown-Standardkarte dynamisch das begrenzte `items`-Attribut der Integration. Sie verwendet ausschließlich Home-Assistant-Standardkarten und verändert keine bestehenden Dashboards.

Completed-Einträge bleiben sichtbar und sind durch graue Darstellung, Haken und den Text **Erledigt** ausgezeichnet. Failed und Uncertain haben getrennte Symbole und Klartexte. Private Adapterziele, Tokens und interne IDs werden nicht projiziert.

## Wichtige Grenzen

- keine Tests an produktivem Home Assistant oder realer Saugerhardware;
- Live-Pilot ausdrücklich nicht freigegeben;
- kein vollständiger Planeditor;
- Planner-Commit und Geräteausführung sind getrennte Garantien;
- Downgrade nur mit bestätigter Store-Kompatibilität oder vollständiger Backup-Wiederherstellung;
- das private Artefakt und Repository-Zugriff verleihen keine zusätzlichen Nutzungs- oder Distributionsrechte.

Alle Grenzen stehen in [docs/limitations.md](docs/limitations.md), der genaue Scope in [docs/beta-scope.md](docs/beta-scope.md).

## Vor Installation oder Update

1. vollständiges Home-Assistant-Backup erstellen;
2. [Installationsanleitung](docs/installation.md) lesen;
3. Release-ZIP authentifiziert beziehen und `SHA256SUMS` prüfen;
4. Dry-run aktiv lassen;
5. [Rollback](docs/rollback.md) vorbereiten.

## Lizenzstatus

Es existiert keine vom Repository-Eigentümer festgelegte Open-Source-Lizenz. Dieser Kandidat ist keine OSS-Freigabe und darf nicht als öffentlich freigegebenes Open-Source-Release behandelt werden; siehe [`LICENSE`](LICENSE).
