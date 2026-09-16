# Bekannter Ausgangszustand

Stand der read-only Bestandsaufnahme zu Projektbeginn.

## Erkannte Sauger

- `vacuum.eufy_s2` – Zustand bei Aufnahme: `docked`
- `vacuum.z60_ultra_roller_complete` – Zustand bei Aufnahme: `docked`

Diese IDs dokumentieren ausschließlich die Migrationsquelle und sind **kein** Bestandteil des zukünftigen universellen Entity-Vertrags.

## Bestehende Planner-Oberfläche

Erkannte Statussensoren:

- nächste Aktion
- heute fällig
- Raumstatus für Küche, Flur, Essbereich und Wohnzimmer
- Morgenprogramm-Status

Erkannte Skriptgruppen:

- je Raum direkter Start
- je Raum manueller Start
- Morgenprogramm erstellen/starten
- nächste Phase des Morgenprogramms starten

## Zu bewahrendes Verhalten

- Aufgaben sind Saugen oder Saugen+Wischen; kein reines Wischen.
- One-Tap startet die aktuell fällige Aufgabe.
- Tagesqueue enthält nur eingeplante Räume.
- Erledigte Räume werden grau bzw. visuell zurückgenommen.
- Ein gestarteter Tagesplan ist ein zusammenhängender Queue-Block; spätere Ad-hoc-Aufgaben werden dahinter angefügt.

## Migrationsprinzip

Die neue Lösung übernimmt zunächst das fachliche Verhalten, nicht die konkreten Helper- oder Entity-IDs. Eine spätere Migration soll bestehende Intervalle und Zeitstempel kontrolliert importieren können, ohne den Altbestand sofort zu entfernen.
