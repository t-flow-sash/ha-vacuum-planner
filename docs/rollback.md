# Backup, Rollback und Entfernung

## Vor jeder Änderung

1. Ein **vollständiges Home-Assistant-Backup** erstellen und extern verfügbar halten.
2. Die aktuell installierte Vacuum-Planner-Version bzw. den Git-Stand notieren.
3. Dry-run aktivieren und die Planung pausieren.
4. Warten, bis kein Commit oder Lauf mehr offen ist. Einen Zustand `uncertain` nicht durch Dateimanipulation „lösen“.
5. Erst danach Update, Downgrade oder Entfernung beginnen.

Ein Ordner-Backup allein ersetzt kein Home-Assistant-Backup, weil Config Entry und Planner-Store getrennt gespeichert werden.

## Downgrade über HACS (nur künftig)

Dieser Abschnitt gilt ausschließlich für eine **zukünftige öffentliche Veröffentlichung**, die tatsächlich über HACS bezogen werden kann. Für den aktuellen privaten Beta-Kandidaten ist HACS kein Installations- oder Rollbackpfad; hier gilt ausschließlich die private Copy-/Release-ZIP-Installation und der manuelle Downgrade unten.

1. Backup verifizieren.
2. In HACS den Vacuum-Planner-Eintrag öffnen.
3. **Erneut herunterladen** und eine ausdrücklich gewünschte ältere verfügbare Version wählen.
4. Home Assistant neu starten.
5. Integration, Repairs, Planner-Status und Queue im Dry-run prüfen.

Ein Downgrade ist nur sicher, wenn der ältere Stand das vorhandene Store-Schema lesen kann. Ist diese Kompatibilität nicht in den Release Notes bestätigt, stattdessen das vollständige Backup wiederherstellen.

## Manueller Downgrade

1. Home Assistant stoppen.
2. `custom_components/vacuum_planner` durch die vollständig gesicherte ältere Ordnerfassung ersetzen; keine Stände mischen.
3. Ohne bestätigte Rückwärtskompatibilität zusätzlich das zusammengehörige vollständige HA-Backup wiederherstellen.
4. Home Assistant starten und zunächst ausschließlich im Dry-run prüfen.

## Integration entfernen

1. Backup erstellen und Dry-run/Planung wie oben sichern.
2. Unter **Einstellungen → Geräte & Dienste → Vacuum Planner** den Config Entry entfernen.
3. Danach die Integration in HACS deinstallieren oder bei manueller Installation den Ordner `custom_components/vacuum_planner` bei gestopptem Home Assistant entfernen.
4. Home Assistant neu starten.
5. Prüfen, dass keine Vacuum-Planner-Entities, Actions oder Repairs mehr aktiv sind.

Erst die endgültige Config-Entry-Löschung ruft den Home-Assistant-Removal-Hook auf. Dieser
löscht über `Store.async_remove()` die entry-spezifische Datei
`vacuum_planner.<config-entry-id>` und anschließend alle bekannten entry-spezifischen
Repairs. Normales Entladen, Neustarten oder erneutes Laden löscht diese Daten nicht.
`Store.async_remove()` ist auch bei bereits fehlender Datei sicher wiederholbar. Scheitert
die Store-Löschung, wird der Fehler an Home Assistant weitergegeben und die Repairs werden
absichtlich nicht entfernt, damit der fehlgeschlagene Datenabbau nicht als erfolgreich
erscheint. Das Backup deshalb bis zur verifizierten endgültigen Entfernung aufbewahren.

Beim Entladen und bei einem fehlgeschlagenen Setup werden alle registrierten Listener-
Cleanup-Schritte versucht. Routing in `hass.data` und `entry.runtime_data` wird danach
identitätsgesichert entfernt, auch wenn ein Callback eine Exception wirft. Ein einzelner
Cleanup-Fehler wird unverändert weitergegeben; mehrere Cleanup-Fehler beziehungsweise ein
Setup- plus Rollback-Fehler werden erst nach vollständigem Cleanup als `ExceptionGroup`
gemeldet. Ein fehlgeschlagenes Plattform-Unload (`False`) bleibt dagegen geladen und
reaktiviert die Command-Generation, wie es der Home-Assistant-Unload-Vertrag verlangt.

## Store-Datei: nur manueller Notfallweg

Der autoritative Zustand liegt pro Config Entry in einer Datei nach dem Muster:

```text
<HA-CONFIG>/.storage/vacuum_planner.<config-entry-id>
```

Für diese Datei gelten harte Regeln:

- **Home Assistant vollständig stoppen**, bevor eine Datei unter `.storage` kopiert, ersetzt, verschoben oder gelöscht wird.
- Die konkrete Datei und die übergeordnete `.storage`-Sicherung vorher separat kopieren.
- Store-Dateien **niemals automatisch** durch Skripte, ein Dashboard oder einen Update-Schritt bearbeiten oder löschen lassen. Einzige reguläre automatische Löschung ist der oben beschriebene Home-Assistant-Removal-Hook bei endgültiger Config-Entry-Löschung.
- Keine manuelle JSON-Reparatur bei laufendem oder nur neu startendem Home Assistant.
- Die Datei nicht isoliert auf einen inkompatiblen Integrationsstand zurücksetzen; bevorzugt das vollständige, zusammengehörige HA-Backup wiederherstellen.

Direkte Store-Bearbeitung ist kein normaler Rollbackpfad. Bei beschädigtem oder nicht migrierbarem Zustand zuerst Diagnostics/Repairs sichern und ein Issue mit redigierten Daten erstellen.

## Rollback-Abnahme

- Home Assistant startet ohne neue Fehler.
- Vacuum Planner lädt oder ist vollständig entfernt.
- Kein offener/unsicherer Lauf wird als abgeschlossen ausgegeben.
- Dry-run ist nach Wiederherstellung aktiv.
- Bestehende Saugerintegration und Dashboards sind unverändert.
