# Bekannter Ausgangszustand

Stand der read-only Bestandsaufnahme zu Projektbeginn.

## Erkannte Sauger

- `vacuum.eufy_s2` – Zustand bei Aufnahme: `docked`
- `vacuum.z60_ultra_roller_complete` – Zustand bei Aufnahme: `docked`

Diese IDs dokumentieren ausschließlich die Migrationsquelle und sind **kein** Bestandteil des zukünftigen universellen Entity-Vertrags.

## Bestehende Planner-Oberfläche

Die aktuelle Installation verteilt Planner-Zustand und Logik über YAML-Helper, Templates, Skripte, Automationen und ein installationsspezifisches Lovelace-Dashboard.

### Erkannte Helper-Struktur

- globale Aktiv-/Lauf-/Ausstehend-Schalter
- je Raum: Aktiv, Heute überspringen, Modus, Saugen-Intervall, Saugen+Wischen-Intervall, Priorität, letzter Saugzeitpunkt und letzter Saugen+Wischen-Zeitpunkt
- Queue-Zustand als mehrere kommaseparierte `input_text`-Werte für Segmente, Labels und aktuelle Phase
- eigener Zeitstempel für den letzten Morgenstart

### Erkannte Skriptgruppen

- je Raum direkter Start der fälligen Aufgabe
- je Raum manueller Start mit gewähltem Modus
- Morgenprogramm berechnen und starten
- nächste Phase des Morgenprogramms starten

### Erkannte Automationen

- täglicher Reset der „Heute überspringen“-Flags
- Morgenstart nach Ende des letzten Nachtmodus
- verzögerter Start eines ausstehenden Programms, wenn der Sauger wieder frei ist
- Abschluss-/Fortschrittslogik zur Aktualisierung der Zeitstempel und Queue

### Erkannte Dashboard-Struktur

- Hero-/Statusbereich mit Planner-Aktivität, nächster Aktion, Roboterstatus und Akku
- Queue-Block mit nur eingeplanten Räumen; aktive und erledigte Räume werden über Segmentzustand unterschieden
- One-Tap-Schnellstart pro Raum, Hold-Aktion für manuellen Modus
- Raumkarten mit Aktivierung, Skip, Modus und Intervallen
- starke Kopplung an konkrete Dreame-Entitäten, Segment-IDs und Mushroom/stack-in-card/card_mod

## Native Area-Readiness

Beide aktuell erkannten Sauger melden das Home-Assistant-Feature `CLEAN_AREA`. Bei der read-only Prüfung war die Segment→Area-Zuordnung für den Eufy vollständig hinterlegt, für den Dreame/Mova jedoch noch leer. Das bestätigt den benötigten Onboarding-Gate: Ein Gerät kann Area Cleaning technisch unterstützen und trotzdem noch nicht einsatzbereit sein, solange der Benutzer unter **Entität → Einstellungen → „Map vacuum segments to areas“** keine Zuordnung gespeichert hat.

## Zu bewahrendes Verhalten

- Aufgaben sind Saugen oder Saugen+Wischen; kein reines Wischen.
- One-Tap startet die aktuell fällige Aufgabe.
- Tagesqueue enthält nur eingeplante Räume.
- Erledigte Räume werden grau bzw. visuell zurückgenommen.
- Ein gestarteter Tagesplan ist ein zusammenhängender Queue-Block; spätere Ad-hoc-Aufgaben werden dahinter angefügt.

## Technische Schulden, die das neue Design beseitigen muss

- Zeitstempel dürfen nicht schon beim Senden eines Reinigungsbefehls als erfolgreich abgeschlossen gelten; Abschluss und Fehler müssen getrennte Zustandsübergänge sein.
- Kommaseparierte Queue-Strings sind nicht transaktional, nur begrenzt skalierbar und bei Neustarts/Parallelzugriffen fehleranfällig.
- Ein Tagesblock braucht eine stabile `block_id`, unveränderliche Reihenfolge und getrennte Laufzeitstände pro Job.
- Direkte Segment- und Hersteller-Service-IDs dürfen nicht im Planner-Core oder Dashboard stecken.
- Die Logik muss nach Home-Assistant-Neustart erkennen, ob ein Job geplant, gesendet, aktiv, abgeschlossen, abgebrochen oder unklar ist.
- Ad-hoc-Aufgaben dürfen einen bereits gestarteten Tagesblock nicht neu sortieren oder überschreiben.

## Migrationsprinzip

Die neue Lösung übernimmt zunächst das fachliche Verhalten, nicht die konkreten Helper- oder Entity-IDs. Eine spätere Migration soll bestehende Intervalle und Zeitstempel kontrolliert importieren können, ohne den Altbestand sofort zu entfernen.
