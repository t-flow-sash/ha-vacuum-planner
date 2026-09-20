# Bekannte Grenzen des Beta-Kandidaten

## Freigabestatus

- Keine produktiven Home-Assistant-, Sauger- oder Firmwaretests wurden durchgeführt.
- Shadow-/Dry-run ist der freigegebene Prüfpfad und bleibt standardmäßig aktiv.
- Ein Live-Pilot ist ausdrücklich noch nicht freigegeben.
- Die automatisierten Tests verwenden simulierte Registry-, State-, Service-, Storage- und Entity-Schnittstellen.

## Einrichtung und Planung

- Der aktuelle Config Flow richtet genau eine vorhandene Sauger-Entität mit einer geordneten Auswahl von Home-Assistant-Areas pro Entry ein.
- Die Beta-Oberfläche bildet noch nicht den gesamten in der UX-Spezifikation vorgesehenen visuellen Wochenplaneditor ab.
- Raumintervalle, komplexe Mehrroboter-Lanes und Komfortoptionen der Zielarchitektur sind noch nicht vollständig als UI verfügbar.
- Dry-run ist eine Sicherheitsbarriere gegen den externen Dispatch, keine Simulation einer bestimmten Gerätefirmware.

## Kompatibilität und Ausführung

- Der installierbare Beta-Pfad konzentriert sich auf die native Home-Assistant-Area-Reinigung und erkannte Capabilities.
- Hersteller- und modellspezifische Aussagen in der [Kompatibilitätsmatrix](compatibility.md) sind Recherche, keine Hardwarefreigabe.
- Eine übergebene Raumreihenfolge ist keine allgemeine Garantie, dass jedes Gerät dieselbe Reihenfolge ausführt.
- Planner-Atomizität beweist keine atomare Gerätequeue.
- Externe Bedienung über App, Gerät oder andere Automationen kann nicht verhindert werden.
- Dispatch oder Service-Annahme gilt nicht als Reinigungserfolg. Unsichere Korrelation bleibt `uncertain` und braucht eine bewusste Auflösung.

## Dashboard

- Ausgeliefert wird ausschließlich die dokumentierte Raw-Konfiguration aus Home-Assistant-Standardkarten.
- Standardkarten können neu erzeugte Entity-IDs nicht automatisch installationsunabhängig entdecken. Deshalb müssen die Planner-Entities vor dem Import einmalig auf die dokumentierten stabilen IDs umbenannt werden.
- Das Artefakt unter [`dashboard/`](../dashboard/README.md) ist eine vollständige importierbare Raw-Konfiguration, aber kein Zero-Touch-Import. Seine Markdown-Standardkarte rendert die Integration-Entity `sensor.vacuum_planner_queue` dynamisch.
- Die sichere Queue-Projektion ist auf 20 Einträge begrenzt und enthält absichtlich keine internen IDs, Adapterziele, Tokens oder Fehlerdetails.
- Drag-and-drop, Filterung und eine ungekürzte interaktive Queue bleiben einem späteren Frontend-Slice vorbehalten. Die Produktregel bleibt: nur geplante Räume; abgeschlossene Einträge grau/dezent.
- Bestehende Lovelace-Dateien und `.storage`-Dashboarddaten werden nie automatisch verändert.

## Betrieb und Daten

- Rückwärtskompatibilität eines Downgrades ist nur gegeben, wenn die jeweilige Release-Dokumentation sie ausdrücklich bestätigt.
- Das Entladen oder Neuladen eines Config Entry bewahrt seinen Store und seine Repairs. Die endgültige Config-Entry-Löschung entfernt den entry-spezifischen Store und danach seine bekannten Repairs über Home-Assistant-APIs; ein Store-Fehler bricht fail-closed ab und lässt die Repairs bestehen.
- Direkte Store-Datei-Bearbeitung ist kein normaler Wartungsweg und nur bei vollständig gestopptem Home Assistant zulässig; siehe [Rollback](rollback.md).
- Diagnostics sind redigiert, können aber vor Veröffentlichung trotzdem auf Haushaltsmetadaten geprüft werden.

## Release und Lizenz

- Dieser Stand ist ein Kandidat, kein getaggtes oder veröffentlichtes Release; die Versionsnummer wurde für diesen Dokumentations-Slice nicht erhöht.
- Für das Repository wurde noch keine Open-Source-Lizenz festgelegt. Eine öffentliche Distribution ist dadurch blockiert; siehe [`LICENSE`](../LICENSE).
