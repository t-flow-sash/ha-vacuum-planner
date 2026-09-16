# Produktanforderungen

## Problem

Die bestehende Saugerplanung funktioniert, ist aber installationsspezifisch. Sie soll zu einem wiederverwendbaren Home-Assistant-Produkt werden, das ein normaler Benutzer ohne KI, Programmierung oder YAML konfigurieren kann.

## Muss-Anforderungen

### Einrichtung und Bedienung

- Konfiguration ausschließlich über UI-Flows.
- Eine vorhandene `vacuum.*`-Entität wird ausgewählt.
- Home-Assistant-Areas bilden das primäre Raummodell.
- Fehlen erforderliche Raumzuordnungen, stoppt das Onboarding mit einer verständlichen Erklärung und einem konkreten nächsten Schritt.
- Planung und spontane Änderungen bleiben nach der Einrichtung ohne YAML möglich.

### Planung

- Räume können eigene Intervalle, Prioritäten und Aktivzustände erhalten.
- Unterstützte Aufgabentypen sind **Saugen** und **Saugen+Wischen**; ausschließliches Wischen ist ausgeschlossen.
- One-Tap startet die aktuell fällige Aufgabe.
- Der Tagesplan wird beim Start logisch als geschlossener Block in die Ausführungsqueue übernommen.
- Danach dürfen zusätzliche spontane Aufgaben hinter diesem Block angehängt werden.
- Die sichtbare Queue enthält nur tatsächlich geplante Räume.
- Erledigte Räume bleiben für den Tageskontext sichtbar, werden aber grau/dezent dargestellt.

### Herstellerunabhängigkeit

- Der Core benutzt bevorzugt die standardisierte `vacuum.*`-Entität und offizielle HA-Abstraktionen.
- Segment-, Sequenz-, Raum-, Karten- und Queue-Funktionen dürfen über optionale Adapter angebunden werden.
- Eingeschränkte Integrationen erhalten dokumentierte Capability-Tiers und nachvollziehbare Payoffs.
- Fehlen Komfortfunktionen, bleibt eine reduzierte Betriebsart nutzbar.

### Dashboard

- Planner-Entitäten haben einen stabilen, herstellerunabhängigen Vertrag.
- Ein standardisiertes Dashboard zeigt Zustand, nächste Aufgabe, Tagesqueue, Raumplan und Eingriffe.
- Bevorzugt wird ein eigenes Hauptdashboard, das weitgehend automatisch bereitgestellt wird.
- Falls Home-Assistant-Sicherheits-/API-Grenzen dies verhindern, wird ein generiertes, direkt nutzbares Dashboard-Artefakt mit minimalem Installationsschritt angeboten.
- Das Dashboard darf keine installationsspezifischen Entity-IDs verlangen, die nicht aus der Planner-Konfiguration entstehen.

### Qualität und Sicherheit

- Keine Geheimnisse oder Cloud-Zugangsdaten außerhalb der jeweiligen Herstellerintegration speichern.
- Keine direkte Abhängigkeit von privaten, undokumentierten Hersteller-APIs im Core.
- Adapterfehler dürfen den Planungszustand nicht beschädigen.
- Queue-Operationen müssen idempotent und nach Neustarts rekonstruierbar sein.
- In Phase 1 keine Live-Tests gegen die produktive HA-Instanz oder reale Roboter.

## Soll-Anforderungen

- Config Flow mit progressiver Offenlegung herstellerspezifischer Optionen.
- Options Flow für spätere Änderungen ohne Neuinstallation.
- Diagnoseexport ohne sensible Daten.
- Übersetzungen mindestens Deutsch und Englisch.
- Reparaturhinweise (`Repairs`) bei verlorener Entität, fehlenden Areas oder nicht mehr erfüllten Capabilities.
- Ereignisse und Zustandsattribute zur nachvollziehbaren Queue-Ausführung.

## Nicht-Ziele der ersten Phase

- Eigene Karten-/SLAM-Implementierung.
- Ersatz der vorhandenen Herstellerintegration.
- Vollständige Vereinheitlichung jeder herstellerspezifischen Reinigungsoption.
- Produktive Live- oder Hardwaretests.
