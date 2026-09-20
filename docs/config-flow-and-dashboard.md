# Config Flow und Dashboard-Bereitstellung

## 1. Config-Entry-Schnitt

Empfohlen ist **eine Planner-Instanz pro Haushalt/Queue-Domäne**. Eine Instanz kann mehrere Robot Lanes verwalten, sofern deren Pläne gemeinsam angezeigt werden. Getrennte Haushalte oder vollständig unabhängige Queue-Domänen erhalten getrennte Entries.

Der Planner wird als `DeviceEntryType.SERVICE` registriert. Vorhandene Sauger-Devices und HA-Areas werden nicht dupliziert; einzelne Queue-Jobs sind keine Devices/Entities.

## 2. Ersteinrichtung

### Schritt 1 – Sauger wählen

- Entity Selector, Domain `vacuum`, Mehrfachauswahl optional;
- Existenz und Registry-Eintrag prüfen;
- pro Entity verfügbare generische Features und bekannte Adapter ermitteln.

### Schritt 2 – Fähigkeiten prüfen

- erkannte Capability-Matrix anzeigen;
- verständliche Aussage statt Vendorjargon, z. B. „Räume planbar, Fortschritt nur für Gesamtauftrag“;
- bei T0 einen bewusst bestätigten Gesamtflächenmodus anbieten oder Setup abbrechen.

### Schritt 3 – Areas wählen

- Area Selector mit stabilen Area-IDs;
- nur Areas anbieten, die der gewählte Roboter eindeutig auflösen kann, oder nicht auflösbare Areas mit Erklärung markieren;
- keine Anzeigenamen als Schlüssel speichern.

### Schritt 4 – Mapping validieren

- natives Vacuum-Area-Mapping bevorzugen;
- fehlende Bindings mit konkretem Pfad zu „Map vacuum segments to areas“ erklären;
- „Erneut prüfen“-Schritt anbieten;
- keine rohe Segment-ID-Eingabe im normalen Flow;
- Entry erst erzeugen, wenn alle ausgewählten Areas eindeutig sind.

### Schritt 5 – Planvorgaben

- pro Area: aktiv, Saugintervall, Saugen+Wischen-Intervall (nur bei Capability), Priorität und Modus;
- Defaults anbieten, aber ausdrücklich bestätigten Abschluss verlangen;
- niemals `mop_only` anbieten.

### Schritt 6 – Zusammenfassung

- Roboter, Areas, Dispatch-Strategie und Garantielevel;
- Hinweis auf Dashboard-Anlegeschritt;
- danach Config Entry plus initiale Planrevision schreiben.

## 3. Topologieänderungen und Options

### Topologieänderungen

Die Minimum-Safe-Beta ändert eine bestehende Topologie nicht im laufenden Entry. Für einen anderen
Sauger, andere Areas oder ein geändertes Mapping muss der Config Entry gelöscht und anschließend
über den initialen Config Flow neu eingerichtet werden. Dadurch wird keine neue Topologie
automatisch in eine vorhandene Queue oder Historie übernommen.

### Options Flow (Verhalten)

- Defaultzeit und Plan aktiv/pausiert;
- Retry-/Timeout-Grenzen innerhalb sicherer Werte;
- Benachrichtigungen;
- optionale Diagnoseentities;
- Dashboard-/Frontend-Erweiterung aktivieren;
- Dedup-/Wiederholungsbestätigung.

Raumintervalle sind fachliche Plandaten und werden bevorzugt über Planner-Entities bzw. Planner-UI geändert, nicht als monolithische Options-Form.

## 4. Repairs

Dauerhaft benutzerlösbare Zustände erzeugen deduplizierte Issues:

- Vacuum-Entity fehlt;
- Area wurde entfernt;
- Area-Mapping fehlt oder ist mehrdeutig;
- konfigurierte Capability ist weggefallen;
- Recovery eines externen Runs ist unklar;
- Store ist beschädigt oder nicht migrierbar.

Entity-, Area-Registry- und relevante Vacuum-State-/Capability-Verluste verriegeln die laufende
Instanz dauerhaft fail-closed. Ein Repair erklärt, dass zunächst ein Reload und bei weiterhin
ungültiger Topologie das Löschen und Neueinrichten des Entries erforderlich ist. Die Instanz
übernimmt keine reparierte oder neue Topologie automatisch im laufenden Betrieb.

## 5. Diagnostics

Diagnostics enthalten nur redigierte/aggregierte Daten:

- Integration-, Config- und Store-Schemaversion;
- Capability-Matrix und Adaptername;
- Anzahl Blöcke/Jobs nach Zustand;
- Queue-Revision, Worker-/Recovery-Zustand;
- normalisierte letzte Fehler.

Entity-/Area-IDs, Anzeigenamen, Segment-IDs, Zeitverläufe und Zugangsdaten werden entfernt oder gehasht.

## 6. Dashboard-Bereitstellung

### Harte Plattformgrenze

Eine Backend-Custom-Integration soll bestehende Lovelace-Dashboards nicht ungefragt ändern, keine internen Storage-Dateien manipulieren und keine privaten APIs für die Installation verwenden. Ein vollständig stilles „als Hauptdashboard installieren“ ist daher kein belastbares Ziel.

### Aktueller Beta-Kandidat

Ausgeliefert wird ein [importierbares Standardkarten-Dashboard](../dashboard/README.md)
mit vollständigen `views`
und Sections sowie Mock-States. Der Nutzer gibt den erzeugten Planner-Entities einmal stabile,
dokumentierte Entity-IDs und importiert die Raw-Konfiguration bewusst in ein neues Dashboard.
Eine Markdown-Standardkarte rendert das begrenzte `items`-Attribut der real implementierten
Queue-Sensorentity bei Coordinator-Updates dynamisch. Die Integration verändert weiterhin keine
bestehenden Dashboards oder Lovelace-Storage-Dateien.

Es besteht keine harte Abhängigkeit von Mushroom, `card_mod` oder anderen
HACS-Erweiterungen im universellen Standarddashboard.

### Informationsarchitektur

**Above the fold**

1. „Nächste Reinigung“ (Status, Zeit, Modus, Roboter);
2. große One-Tap-Aktion „Fällige Aufgabe starten“, die ausschließlich `vacuum_planner.start_next` aufruft;
3. „Queue“: ausschließlich tatsächlich materialisierte Jobs aus der begrenzten Queue-Sensorprojektion.

**Below the fold**

4. Raumplan mit Intervallen, nächster Fälligkeit und Aktivstatus;
5. verständliche Capability-/Mapping-Hinweise;
6. seltene Einstellungen und Diagnose.

Statusdarstellung:

- `completed`: grau/dezent + Haken;
- `running`: klar hervorgehoben;
- `pending`: normal;
- `failed`/`uncertain`: Warnung plus konkrete Aktion;
- keine Platzhalter für nicht geplante Räume.

## 7. Dashboard-Datenweg

Kompakte Zustände kommen aus Entities. Die Queue-Sensorprojektion ist auf 20 sichere
Einträge begrenzt; vollständige read-only Daten liefert ausschließlich die Response-Action
`vacuum_planner.get_queue`. Coordinator-Updates aktualisieren die Entities.

## 8. Abnahmekriterien

- Einrichtung ohne YAML/Freitext-Entity-IDs;
- fehlendes Mapping blockiert verständlich und reparierbar;
- Dashboard in einem bestätigten Schritt anlegbar;
- kein Vendor-Entity-Verweis in der UI-Konfiguration;
- Standardfunktion bleibt allein mit Home-Assistant-Standardkarten nutzbar;
- Tablet, Desktop und Mobile haben klare Touch-/Fokusführung;
- die UI unterscheidet Planner- und Robot-Atomizität korrekt.
