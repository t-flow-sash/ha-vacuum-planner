# Installation und UI-Einrichtung

## Status und Voraussetzungen

`v0.1.0-beta.2` ist ein **unveröffentlichter privater Release-Kandidat** ohne Produktiv- oder Hardwarefreigabe. Sein Config Flow wurde auf Home Assistant 2026.9.3 beaufsichtigt bis zur Raumplanung erfolgreich pilotiert. Für die Installation sind erforderlich:

- ausdrückliche Berechtigung des Repository-Eigentümers;
- authentifizierter Zugriff auf das private GitHub-Repository und dessen Release-Assets;
- eine unterstützte Home-Assistant-Installation mit **Einstellungen → Geräte & Dienste**;
- mindestens eine eingerichtete `vacuum`-Entität mit Home-Assistant-Areas;
- ein vollständiges Home-Assistant-Backup.

Der Zugriff auf Quelltext oder Artefakte ersetzt keine Lizenz. Maßgeblich ist der [Lizenzstatus](../LICENSE).

## Primärer privater Installationsweg: semantisches Release-ZIP

Sobald der Eigentümer den Kandidaten ausdrücklich als privaten GitHub-Release `v0.1.0-beta.2` bereitstellt, werden ausschließlich diese Assets verwendet:

- `vacuum_planner-v0.1.0-beta.2.zip`
- `SHA256SUMS`

### Authentifiziert per GitHub CLI herunterladen

```bash
gh auth status
gh release download v0.1.0-beta.2 \
  --repo t-flow-sash/ha-vacuum-planner \
  --pattern 'vacuum_planner-v0.1.0-beta.2.zip' \
  --pattern 'SHA256SUMS'
sha256sum -c SHA256SUMS
```

Alternativ können berechtigte Tester beide Assets in einer bereits authentifizierten GitHub-Browsersitzung herunterladen. Keine inoffiziellen Spiegel, automatisch erzeugten Source-Code-Archive oder Artefakte unbekannter Herkunft verwenden.

> In diesem Repository-Stand wurde noch **kein Tag und kein GitHub-Release** erstellt. Bis der Eigentümer den privaten Kandidaten veröffentlicht, kann ein autorisierter Tester das identische Release-ZIP lokal mit `python scripts/build_release.py --version 0.1.0-beta.2` erzeugen und die ausgegebene SHA-256-Prüfsumme kontrollieren.

### Kopieren

1. Prüfsumme erfolgreich verifizieren und ZIP in ein leeres temporäres Verzeichnis entpacken.
2. Prüfen, dass das Archiv direkt `custom_components/vacuum_planner/manifest.json` enthält.
3. Den vollständigen Ordner `custom_components/vacuum_planner` nach `<HA-CONFIG>/custom_components/vacuum_planner` kopieren.
4. Bei einem Update den alten Integrationsordner nach dem Backup vollständig ersetzen; niemals Dateien verschiedener Versionen mischen.
5. Home Assistant neu starten.

Das Release-ZIP ist das Installationsartefakt. Python-Paketformate sind kein unterstützter Home-Assistant-Installationsweg.

## HACS-Status

Das Repository ist privat. Private GitHub-Repositories können nicht als HACS Custom Repository installiert werden. **HACS ist für diesen privaten Kandidaten daher kein Installationsweg.**

Eine HACS-Anleitung wird erst relevant, wenn das Repository später öffentlich erreichbar ist, ein tatsächlicher Release vorliegt und der Eigentümer Distribution und Lizenz ausdrücklich geklärt hat. Bis dahin darf die bloße Existenz von `hacs.json` nicht als HACS-Freigabe interpretiert werden.

## UI-only Setup

Nach dem Neustart:

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
2. **Vacuum Planner** suchen.
3. Eine vorhandene Sauger-Entität auswählen.
4. Die geordneten Home-Assistant-Räume im Area-Selector auswählen.
5. Den Flow abschließen.
6. Unter dem Integrationseintrag **Konfigurieren** öffnen; Planung prüfen und **Dry-run eingeschaltet lassen**.

Fehlt die native Zuordnung eines Raums, die Raumzuordnung der Sauger-Integration vervollständigen und den Flow erneut ausführen. Rohe Segmentwerte werden nicht eingegeben.

### Keine YAML-Konfiguration

Für die Integrationseinrichtung sind **keine YAML-Konfiguration**, keine `configuration.yaml`-Einträge, Packages oder manuell erzeugten Helper nötig. Das optionale Dashboard wird getrennt und bewusst importiert; siehe [Dashboard](../dashboard/README.md).

## Sichere Erstprüfung im Shadow-/Dry-run

1. Dry-run eingeschaltet lassen.
2. Integration und Planner-Gerät auf Warnungen oder Repairs prüfen.
3. Status, dynamische Queue und offene Aufgaben kontrollieren.
4. `start_next` nur im Dry-run auslösen und Statusübergänge prüfen.
5. Home Assistant neu starten und die Wiederherstellung des Zustands kontrollieren.

Dry-run verhindert den externen Reinigungsaufruf, ersetzt aber keinen beaufsichtigten Hardwaretest. Der erfolgreiche Config-Flow-Pilot erteilte keine Freigabe für reale Reinigungsbefehle; Dry-run darf für `v0.1.0-beta.2` nur in einem separat genehmigten, beaufsichtigten Hardwaretest ausgeschaltet werden.

## Dashboard

[`dashboard/vacuum-planner.yaml`](../dashboard/vacuum-planner.yaml) ist eine importierbare Lovelace-Raw-Konfiguration mit Standardkarten. Die [Dashboard-Anleitung](../dashboard/README.md) beschreibt die einmalige stabile Benennung der Integration-Entities und den Import. Bestehende Dashboards werden nicht automatisch verändert.

## Nächste Schritte

- [Beta-Umfang](beta-scope.md)
- [Bekannte Grenzen](limitations.md)
- [Rollback und Entfernung](rollback.md)
