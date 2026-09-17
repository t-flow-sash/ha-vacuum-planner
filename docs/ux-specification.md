# UX-Konzept: Home-Assistant-Saugerplaner

**Status:** Umsetzungsreife UX-Spezifikation
**Zielgruppe:** Produkt, Home-Assistant-Integration, Frontend/Lovelace, QA
**Sprache:** Deutsch; alle sichtbaren Texte lokalisierbar
**Grundsatz:** Einrichtung, Planung und tägliche Bedienung funktionieren ohne YAML, Templates oder Coding.

---

## 1. Executive Summary

Der Saugerplaner ist kein technisches Steuerpult, sondern beantwortet innerhalb von zwei Sekunden drei Fragen:

1. **Was ist heute dran?**
2. **Was startet der große Button?**
3. **Gibt es etwas, das meine Aufmerksamkeit braucht?**

Die Primäraktion lautet immer konkret, beispielsweise **„3 Räume jetzt reinigen“**. Ein Tap startet genau die nächste fällige, startfähige Tagesaufgabe beziehungsweise den noch offenen Tagesblock. Es gibt keinen Modus **„nur Wischen“**: Wenn Wischen geplant ist, wird **„Saugen + Wischen“** ausgeführt.

Empfohlen ist eine vollwertige Home-Assistant-Integration mit:

- **Config Flow** für Roboterwahl, Capability-Prüfung und initiale Raumzuordnung,
- **Options Flow** für seltene Systemeinstellungen und Reparatur der Zuordnung,
- **einem eigenen visuellen Planungseditor** für wiederkehrende Planänderungen,
- **einem nach einmal bestätigter Anlage dynamisch generierten Dashboard** auf Basis universeller Entitäten,
- **keiner ungefragten Änderung bestehender Dashboards**.

Ein reiner Blueprint ist aus UX-Sicht unzureichend: Er kann die komplexe dynamische Raumzuordnung, Validierung, Queue-Transparenz und dashboardweite Null-Konfiguration nicht angemessen abbilden.

---

## 2. Nicht verhandelbare Produktregeln

### 2.1 Bedienregeln

- Kein YAML, keine Templates, keine manuellen Entity-IDs.
- Keine versteckten Hauptaktionen und keine Bedienung nur per Wischgeste.
- Primär Home-Assistant-**Areas/Räume** verwenden; herstellerspezifische Segmente bleiben Implementierungsdetail.
- Fehlt eine Raumzuordnung, ist das eine klar benannte Vorbedingung und kein stiller Fehler.
- **Nie nur Wischen.** Zulässige Reinigungsarten sind `Saugen` und `Saugen + Wischen`.
- One-Tap startet die **fällige Aufgabe**, nicht einen unbestimmten Standardlauf.
- Die Tagesqueue zeigt ausschließlich heute geplante Räume plus später bewusst angehängte Zusatzjobs.
- Erledigte Queue-Einträge bleiben bis Tagesende sichtbar und werden grau dargestellt.
- Beim ersten Start wird der noch offene Tagesplan im Planner als **ein versiegelter Block** übergeben. Ob derselbe Block atomar in der Gerätequeue liegt oder kontrolliert vom Planner sequenziert wird, zeigt die UI capability-abhängig an.
- Nach Blockstart dürfen Zusatzjobs angehängt werden; sie ändern nicht rückwirkend den bereits gesendeten Block.
- Destruktive oder schwer rückgängig zu machende Aktionen erhalten eine Bestätigung; der normale Start nicht.

### 2.2 UX-Prinzipien

1. **Nächste sinnvolle Handlung vor Systemzustand.** „Jetzt reinigen“ ist wichtiger als zehn Sensorwerte.
2. **Konkrete Sprache.** „Küche und Flur jetzt reinigen“, nicht „Service ausführen“.
3. **Progressive Offenlegung.** Alltag auf dem Dashboard, Planung im Editor, technische Details in Diagnose.
4. **Erklärbare Automatik.** Jede Fälligkeit zeigt kurz „warum“ und „wann“.
5. **Fehler am Ort der Handlung.** Ein nicht zugeordneter Raum wird in Queue und Editor erklärt und verlinkt.
6. **Sicher optimistisch, technisch ehrlich.** Nach Tap sofort Feedback, aber „gestartet“ erst nach Bestätigung des Roboters.
7. **Familientauglich.** Alltagstexte statt Integrationsbegriffe wie Segment-ID, Service oder Payload.

---

## 3. Zielgruppen und zentrale Jobs-to-be-done

### 3.1 Familienmitglied / Alltagsnutzer

- „Zeig mir, ob heute etwas dran ist.“
- „Starte mit einem Tap die richtige Reinigung.“
- „Lass die Küche zusätzlich reinigen, ohne den Plan zu verstehen.“
- „Sag mir verständlich, warum nichts startet.“

### 3.2 Haushaltsorganisator / Planer

- „Lege pro Raum fest, an welchen Tagen und wie gereinigt wird.“
- „Ändere den Plan spontan für heute, ohne den Wochenplan zu beschädigen.“
- „Erkenne Lücken, Konflikte und nicht zugeordnete Räume.“

### 3.3 Home-Assistant-Administrator

- „Richte die Integration ohne YAML ein.“
- „Ordne HA-Räume zu Roboter-Räumen zu.“
- „Erhalte stabile, herstellerneutrale Entitäten für eigene Automationen und Dashboards.“
- „Kann Diagnoseinformationen sehen, ohne sie der Familie aufzudrängen.“

---

## 4. Begriffsmodell und Zustände

### 4.1 Nutzersprache

| Technischer Begriff | Sichtbarer Begriff |
|---|---|
| Area | Raum |
| Segment | erkannter Roboter-Raum; nur im Zuordnungsdialog sichtbar |
| Job | Aufgabe |
| Queue | Heute / Tagesplan |
| Dispatch | An Roboter senden |
| Capability | Unterstützte Funktion |
| Config Entry | eingerichteter Saugerplaner |

### 4.2 Plan, Tagesaufgabe und Ausführungsblock

- **Wochenplan:** wiederkehrende Regeln je HA-Raum.
- **Tagesplan:** aus dem Wochenplan abgeleitete Aufgaben für das aktuelle lokale Datum, ergänzt um einmalige Änderungen.
- **Tagesaufgabe:** ein geplanter Raum mit Reinigungsart und Status.
- **Ausführungsblock:** die beim ersten Start atomar eingefrorene, geordnete Liste aller aktuell startfähigen, offenen Tagesaufgaben.
- **Zusatzjob:** nach dem Blockstart bewusst angehängte Aufgabe; steht sichtbar hinter dem Block.

### 4.3 Statusmodell einer Tagesaufgabe

`geplant` → `bereit` → `gesendet` → `läuft` → `erledigt`

Alternative Übergänge:

- `geplant/bereit` → `übersprungen`
- `geplant/bereit` → `blockiert`
- `gesendet/läuft` → `fehlgeschlagen`
- `übersprungen` → `wiederhergestellt`
- `fehlgeschlagen` → `erneut bereit`

**Darstellung:**

- Bereit: normale Oberfläche, klarer Modus-Chip.
- Läuft: Akzentfarbe plus Fortschritt/Spinner und Text.
- Erledigt: grau, Häkchen, Text „Erledigt“; nicht entfernen.
- Übersprungen: grau, Durchstreichung optional nur zusätzlich, Text „Heute übersprungen“.
- Blockiert: Warnfarbe, Grund in Klartext, Lösung als Button.
- Fehlgeschlagen: Fehlerfarbe, Ursache und „Erneut versuchen“.

### 4.4 Priorisierung für One-Tap

1. Wenn ein Block läuft: Primäraktion wird **„Reinigung anzeigen“**, nicht noch einmal starten.
2. Wenn ein gesendeter Block auf Roboterbestätigung wartet: **„Start wird bestätigt …“**, deaktiviert.
3. Wenn offene Zusatzjobs nach einem laufenden Block bereitstehen: **„Nächsten Zusatzjob starten“** nur, wenn der Adapter kein automatisches Anhängen unterstützt.
4. Sonst: alle offenen, startfähigen Tagesaufgaben werden als Block gestartet.
5. Wenn nur blockierte Aufgaben vorhanden sind: **„Problem beheben“**.
6. Wenn nichts fällig ist: **„Heute nichts geplant“**, sekundär **„Raum zusätzlich reinigen“**.

---

## 5. Informationsarchitektur

```text
Saugplanung (Dashboard / Start)
├── Heute
│   ├── Hero: Status + One-Tap
│   ├── Tagesqueue
│   ├── Zusatzjob hinzufügen
│   └── Hinweise/Fehler
├── Plan bearbeiten
│   ├── Wochenübersicht
│   ├── Raumdetail
│   ├── Mehrfachbearbeitung
│   └── Vorschau „Nächste 7 Tage“
├── Verlauf
│   ├── letzte Läufe
│   └── Fehler / ausgelassene Aufgaben
└── Einstellungen
    ├── Roboter
    ├── Raumzuordnung
    ├── Planverhalten
    ├── Benachrichtigungen
    ├── Dashboard
    └── Diagnose
```

### Navigationsprinzip

- Eigenes Hauptdashboard **„Saugplanung“** in der Sidebar, sofern der Administrator dies im Onboarding bestätigt.
- Maximal vier Hauptziele: `Heute`, `Plan`, `Verlauf`, `Einstellungen`.
- Auf Mobilgeräten Navigation über HA-native Header/Subviews; keine selbst erfundene Bottom-Navigation, falls diese mit der HA-App kollidiert.
- Zurück-Navigation und Browser-/App-Back funktionieren auf jedem Unterbildschirm.
- Deep Links: Fehlerhinweise öffnen direkt die betroffene Raumzuordnung oder Einstellung.

---

## 6. Onboarding / Config Flow

### 6.1 Ziel

In wenigen Minuten vom installierten Bestandteil zum startfähigen Tagesplan – ohne Eingabe von Entity-IDs. Das Onboarding wird erst als „fertig“ bezeichnet, wenn mindestens ein Roboter, ein startfähiger Raum und ein Plan vorhanden sind.

### 6.2 Screen 1 – Willkommen

**Titel:** `Saugplanung einrichten`
**Text:** `Plane die Reinigung nach Räumen und starte den fälligen Tagesplan mit einem Tap.`
**Nutzenpunkte:**

- `Verwendet deine Home-Assistant-Räume`
- `Unterstützt Saugen und Saugen + Wischen`
- `Zeigt immer, was heute ansteht`

**Primär:** `Einrichtung starten`
**Sekundär:** `Abbrechen`

Kein Marketing-Karussell und keine Berechtigungsabfrage ohne unmittelbaren Grund.

### 6.3 Screen 2 – Roboter wählen

Automatisch gefilterte Auswahl kompatibler `vacuum`-Entitäten, Anzeige als verständliche Zeile:

- Gerätename
- zugehörige Integration/Hersteller
- aktueller Status
- Kompatibilitätsbadge: `Voll unterstützt`, `Eingeschränkt`, `Nicht geeignet`

**Titel:** `Welcher Roboter soll geplant werden?`
**Hilfetext:** `Es werden nur Roboter angezeigt, die Home Assistant bereits kennt.`

Bei genau einem voll kompatiblen Gerät: vorausgewählt, aber nicht kommentarlos übersprungen.
Bei keinem Gerät: Empty State, siehe Fehlerzustände.

### 6.4 Screen 3 – Funktionsprüfung

Die Integration prüft Adapterfähigkeiten und übersetzt sie in Nutzerfolgen.

**Titel:** `Das kann dein Roboter`
**Beispiel:**

- ✓ `Räume einzeln reinigen`
- ✓ `Saugen + Wischen`
- ✓ `Mehrere Räume in einer Reinigung`
- ! `Zusatzjobs werden nacheinander gestartet`

**Copy bei Einschränkung:**
`Du kannst den Plan verwenden. Einige Aufgaben sendet Home Assistant nacheinander statt als gemeinsamen Block.`

**Primär:** `Weiter`
**Sekundär bei ungeeignet:** `Anderen Roboter wählen`

„Voll unterstützt“ darf nur bei tatsächlich validierten Capabilities erscheinen. Keine Herstellerfunktion versprechen, die der Adapter nicht sicher abbildet.

### 6.5 Screen 4 – Räume zuordnen

Dies ist der kritischste Onboarding-Schritt.

**Titel:** `Räume prüfen`
**Text:** `Der Sauger verwendet die Raumzuordnung aus Home Assistant. Prüfe, ob alle geplanten Räume verbunden sind.`

Standardpfad mit nativer HA-Zuordnung:

- HA-Area und erkannter Roboter-Raum werden als bestätigte, zunächst nicht frei editierbare Zuordnung gezeigt.
- Fehlende Zuordnung erhält den konkreten Button `In Sauger-Einstellungen zuordnen` zur nativen Funktion **„Map vacuum segments to areas“**.
- Nach Rückkehr prüft `Erneut prüfen` die Zuordnung erneut.
- Der Planner führt kein paralleles, benutzerseitiges Segmentregister.

Nur wenn ein expliziter Vendor-Adapter keine native HA-Zuordnung bereitstellt, erscheint ein Adapter-Mapping als progressive Erweiterung. Dann gelten:

- Vorschläge durch normalisierte Namen werden nie still übernommen.
- Segment-IDs bleiben technische Adapterdetails und werden nicht als normale Eingabefelder gezeigt.
- `Nicht verwenden` ist eine bewusste Auswahl.
- Unaufgelöste, aber aktiv eingeplante Räume verhindern den Abschluss.
- Ein HA-Raum darf nur dann mehrere Segmente umfassen, wenn der Adapter dies eindeutig unterstützt.

**Inline-Fehler:** `Küche ist noch keinem Roboter-Raum zugeordnet.`
**Primär:** `Zuordnung erneut prüfen`
**Sekundär:** `Später fortsetzen` – erzeugt einen unvollständigen Zustand, aber keinen scheinbar fertigen Plan.

### 6.6 Screen 5 – Planvorschlag

**Titel:** `Dein erster Wochenplan`
**Text:** `Wir haben einen einfachen Vorschlag erstellt. Du kannst alles später ändern.`

Jeder ausgewählte Raum erhält eine kompakte Zeile:

`Küche · Mo, Mi, Fr · Saugen + Wischen`

Nutzer kann:

- Räume aktivieren/deaktivieren,
- Wochentage wählen,
- Reinigungsart `Saugen` oder `Saugen + Wischen` wählen,
- Reihenfolge per Auf/Ab-Tasten ändern; Drag-and-drop nur zusätzlich.

**Primär:** `Plan übernehmen`
**Sekundär:** `Ohne Vorschlag planen`

Kein „magischer“ Plan aufgrund von Haushaltsannahmen ohne sichtbare Bestätigung.

### 6.7 Screen 6 – Dashboard

**Titel:** `Saugplanung ist bereit`
**Hinweis:** `Lege unter Einstellungen → Dashboards einmal das Community Dashboard „Saugplanung“ an. Deine bestehenden Dashboards werden nicht verändert.`

**Zusammenfassung:**

- `1 Roboter verbunden`
- `6 Räume zugeordnet`
- `12 Aufgaben pro Woche`

**Primär:** `Dashboard öffnen`
**Sekundär:** `Einstellungen ansehen`

### 6.8 Wiederaufnahme und Abbruch

- Jeder erfolgreiche Schritt wird gespeichert.
- Wiederaufnahme startet beim ersten unvollständigen Schritt.
- Copy: `Einrichtung fortsetzen – noch 2 Schritte`.
- Beim Verlassen mit ungespeicherten Eingaben: `Änderungen verwerfen?` mit `Weiter bearbeiten` als sicherer Primäraktion und `Verwerfen` als destruktiver Sekundäraktion.

---

## 7. Planungseditor

### 7.1 Warum nicht ausschließlich Options Flow?

Ein Options Flow eignet sich für selten geänderte, formularartige Einstellungen. Ein Wochenplan mit vielen Räumen, Tagen, Reihenfolgen, Vorschau, Bulk-Aktionen und Konflikten ist ein visueller Editor und sollte als eigener Integrations-/Frontend-Bildschirm umgesetzt werden. Das verhindert einen langen Wizard und häufiges „Weiter/Zurück“.

### 7.2 Wochenübersicht

**Titel:** `Wochenplan`
**Header-Aktionen:** `Heute`, `Vorschau`, Overflow mit `Plan pausieren` und `Plan zurücksetzen`.

Darstellung:

- Desktop/Tablet: Matrix mit Räumen als Zeilen und Wochentagen als Spalten.
- Mobil: tageweise Karten/Liste; keine horizontal zwingend zu scrollende 7-Tage-Matrix.
- Jede geplante Zelle zeigt textlich und per Icon den Modus: `Saugen` oder `Saugen + Wischen`.
- Leere Zellen zeigen bei Fokus/Touch `Aufgabe hinzufügen`.
- Legende ist sichtbar und nicht nur über Farbe codiert.

**Primär oberhalb des Folds:** `Änderungen speichern`, sobald Änderungen vorliegen.
**Sticky Action Bar mobil:** `Verwerfen` / `Speichern`.

### 7.3 Raumdetail

**Titel:** `Küche planen`
Felder:

1. `Im Plan verwenden` – Toggle.
2. `Reinigungstage` – Mehrfachauswahl Mo–So, große Chips.
3. `Reinigung` – Segmented Control: `Saugen` | `Saugen + Wischen`.
4. `Reihenfolge` – relative Position über `Früher` / `Später`; Drag optional.
5. Optional bei unterstütztem Adapter unter `Erweitert`: Intensität, Wiederholungen. Diese Werte sind capability-gated und nie Voraussetzung für den Basisplan.

**Verboten:** eine Option `Wischen` ohne Saugen.

**Vorschau:** `Nächste Reinigung: Mittwoch · Saugen + Wischen`.

### 7.4 Mehrfachbearbeitung

Auswahlmodus über sichtbare Checkboxen, nicht Long-Press als einziger Weg.

Mögliche Aktionen:

- `Tage festlegen`
- `Saugen`
- `Saugen + Wischen`
- `Pausieren`

Bestätigung zeigt Reichweite: `Reinigung für 4 Räume ändern?`.

### 7.5 Speichern, Konflikte und Wirksamkeit

- Autosave nur für triviale Toggles; komplexe Planänderungen explizit speichern.
- Nach Speichern: Snackbar `Wochenplan gespeichert` mit `Rückgängig` für 10 Sekunden.
- Wenn der Tagesblock noch nicht gestartet wurde: `Die Änderung gilt ab heute.`
- Wenn der Tagesblock bereits gesendet wurde: Dialog:
  - `Der heutige Reinigungsblock läuft bereits.`
  - `Änderungen gelten ab morgen. Für heute kannst du einen Zusatzjob anhängen.`
  - Aktionen: `Ab morgen speichern` / `Abbrechen` / optional `Als Zusatzjob hinzufügen`.
- Bei paralleler Änderung: `Der Plan wurde inzwischen auf einem anderen Gerät geändert.` mit `Neu laden` und `Meine Änderungen prüfen`; niemals still überschreiben.

### 7.6 Vorschau

`Nächste 7 Tage` zeigt pro Tag Räume und Modus sowie Warnungen. Der heutige, bereits eingefrorene Block wird als `Bereits an Roboter gesendet` markiert. Vorschau ist read-only und beantwortet „Was passiert wann?“.

---

## 8. Tagesqueue

### 8.1 Struktur

**Abschnittstitel:** `Heute`
**Zusammenfassung:** `3 von 5 Räumen offen · ca. 48 Min.` – Zeit nur, wenn belastbar; sonst weglassen.

Reihenfolge:

1. aktuell laufende Aufgabe,
2. offene Aufgaben des gesendeten Blocks,
3. offene noch nicht gesendete Tagesaufgaben,
4. angehängte Zusatzjobs,
5. erledigte/übersprungene Aufgaben am Ende, grau.

Die Queue enthält **keine ungeplanten Räume**. Diese erscheinen nur im Auswahl-Dialog `Zusatzjob hinzufügen` und nach Bestätigung in der Queue.

### 8.2 Queue-Zeile

Pflichtinhalt:

- Raumname: `Küche`
- Modus: `Saugen + Wischen`
- Status: `Als Nächstes`, `Läuft`, `Erledigt`, `Blockiert`, `Zusatzjob`
- optionaler Grund: `Laut Wochenplan: Mittwoch`
- Overflow-Menü mit beschrifteten Aktionen.

Direkte Aktion für offene Einträge: `Heute überspringen`.
Im Menü: `Auf morgen verschieben`, `Reihenfolge ändern`, `Details`.

### 8.3 Reihenfolge ändern

- Vor Start des Blocks: Reihenfolge änderbar.
- Nach Versand: Blockreihenfolge gesperrt, Copy: `Diese Reihenfolge wurde bereits an den Roboter gesendet.`
- Zusatzjobs können untereinander sortiert werden, sofern technisch noch nicht gesendet.
- Drag-and-drop darf angeboten werden, aber jede Zeile braucht zusätzlich `Nach oben` und `Nach unten` im Menü sowie Tastaturbedienung.

### 8.4 Heute überspringen / verschieben

- `Heute überspringen`: Sofortige Aktion mit Snackbar `Küche heute übersprungen` + `Rückgängig`.
- `Auf morgen verschieben`: erzeugt eine einmalige Aufgabe für morgen; Copy `Küche auf morgen verschoben`.
- Überspringen verändert den Wochenplan nicht.
- Ist der Block bereits gesendet, ist Überspringen für gesendete Aufgaben deaktiviert oder wird – nur wenn der Adapter sicher abbrechen kann – als `Aktuelle Aufgabe abbrechen` gesondert angeboten. Kein falsches Versprechen.

### 8.5 Zusatzjob

Button: `Raum zusätzlich reinigen`.

Sheet/Dialog:

1. Räume als HA-Areas auswählen.
2. Modus wählen: `Saugen` oder `Saugen + Wischen`.
3. Zusammenfassung: `Wohnzimmer wird nach dem Tagesplan gereinigt.`
4. Primär: `Zur Queue hinzufügen`.

Nach Blockstart steht sichtbar `Zusatzjob` und `Wird anschließend gestartet`. Doppelte Raumwahl erzeugt eine bewusste Warnung: `Küche ist heute bereits eingeplant. Trotzdem ein zweites Mal reinigen?`.

---

## 9. One-Tap-Start

### 9.1 Hero-Komponente

Der Hero ist die visuell dominante Komponente über dem Fold.

**Bereit:**

- Eyebrow: `Heute geplant`
- Headline: `Küche, Flur und Wohnzimmer`
- Subline: `3 Räume · Saugen + Wischen`
- Primärbutton: `3 Räume jetzt reinigen`
- Sekundär: `Plan ansehen`

**Nichts geplant:**

- Headline: `Heute ist nichts geplant`
- Subline: `Der nächste Plan startet Donnerstag.`
- Primär: `Raum zusätzlich reinigen`

**Läuft:**

- Headline: `Küche wird gereinigt`
- Subline: `1 von 3 · danach Flur`
- Primär: `Reinigung anzeigen`
- Sekundär, nur wenn sicher unterstützt: `Pausieren`

**Blockiert:**

- Headline: `Reinigung kann nicht starten`
- Subline: `Küche ist keinem Roboter-Raum zugeordnet.`
- Primär: `Raum zuordnen`

### 9.2 Interaktionsvertrag

1. Tap sendet genau einmal den aktuell offenen Tagesblock.
2. Button wechselt unverzüglich zu `Wird vorbereitet …` und wird gegen Doppeltaps gesperrt.
3. Nach Annahme durch Adapter: `An Roboter gesendet`.
4. Erst bei Roboterbestätigung: `Reinigung gestartet`.
5. Timeout: nicht als Erfolg darstellen; `Der Roboter hat den Start noch nicht bestätigt.` mit `Status prüfen` und `Erneut versuchen` nur idempotent/sicher.
6. Vor dem normalen Start kein Bestätigungsdialog; alle betroffenen Räume stehen bereits im Hero.
7. Bei überraschendem Umfang (beispielsweise mehr als konfigurierter Schwellenwert oder geschätzte Dauer > 120 Minuten) optional Bestätigungs-Sheet, standardmäßig jedoch nicht.

### 9.3 Schutz vor Fehlbedienung

- Idempotency-Key pro Block verhindert Doppelversand.
- Während `dispatching` keine zweite Startaktion.
- Bei HA-Neuladen Zustand serverseitig rekonstruieren; der Button darf nicht zu „Starten“ zurückspringen, solange Auftrag unklar ist.
- „Stoppen“ ist räumlich und visuell vom Start getrennt und bestätigt: `Gesamte Reinigung stoppen?`.

---

## 10. Dashboard-Spezifikation

### 10.1 Zielbild

Modern, HA-nativ, ruhig und familienfähig. Keine technische Entity-Liste. Sections-/Grid-Prinzip, native Tile-/Button-/Markdown-/Conditional-Mechaniken, möglichst ohne HACS-Pflicht. `card-mod` darf nicht Voraussetzung der Kernbedienung sein.

### 10.2 Desktop/Tablet

- Maximalbreite Inhalt: ca. 1200 px.
- 12-Spalten-Logik beziehungsweise HA-Sections-Grid.
- Linke 8 Spalten: Hero + Tagesqueue.
- Rechte 4 Spalten: Robotstatus, nächster Termin, Planstatus, schnelle Zusatzaktion.
- Unterhalb: Wochenvorschau / Verlauf.

### 10.3 Mobil

Reihenfolge strikt:

1. Hero + Primäraktion,
2. kritischer Hinweis,
3. laufende/offene Tagesqueue,
4. `Raum zusätzlich reinigen`,
5. kompakter Robotstatus,
6. nächster Termin,
7. Verlauf.

Keine horizontale Hauptnavigation, keine 7-Spalten-Matrix, keine Hover-Abhängigkeit.

### 10.4 Karten

#### A. Hero `Nächste Aktion`

- dynamische Headline, Raumanzahl, Modus, Blockstatus,
- großer Primärbutton,
- Statusfeedback live, aber nicht flackernd,
- Warnhinweis integriert, wenn Aktion blockiert.

#### B. `Heute`

- Tagesqueue gemäß Kapitel 8,
- Fortschrittszeile `2 von 5 erledigt`,
- erledigte Einträge grau, weiterhin lesbar,
- Empty State statt leerer Karte.

#### C. `Roboter`

- Name und menschenlesbarer Zustand,
- Akku nur wenn relevant,
- Dock-/Wasser-/Behälterwarnung nur bei Handlungsbedarf,
- keine diagnostische Sensorwand.

#### D. `Plan`

- `Nächste Reinigung: Donnerstag · 2 Räume`,
- Button `Plan bearbeiten`,
- Planstatus `Aktiv` / `Pausiert bis …`.

#### E. `Zusatzreinigung`

- Button `Raum zusätzlich reinigen`,
- öffnet Sheet; keine Reihe kryptischer Raumicons.

#### F. `Letzte Reinigung`

- Zeitpunkt, Räume, Ergebnis,
- Link `Verlauf anzeigen`,
- Fehler prominent, Erfolg zurückhaltend.

### 10.5 Universelle Entity-Schnittstelle

Die UI darf keine herstellerspezifischen Entity-IDs voraussetzen. Alle Entitäten gehören zum Planner-Gerät und haben stabile Unique IDs. Namen sind Beispiele; die Integration liefert sie automatisch.

Der vollständige und allein kanonische Katalog steht in [Universeller Entity-Vertrag](entity-contract.md). Für das Dashboard sind insbesondere vorgesehen:

- `switch` **Planung**;
- `sensor` **Status**, **Nächste Aktion**, **Ausstehende Aufgaben**, **Aktuelle Phase** und **Nächster Start**;
- `binary_sensor` **Bereit** und **Eingriff erforderlich**;
- `button` **Nächste fällige Aufgabe starten** und **Aktuellen Block abbrechen**; der One-Tap-Button ruft ausschließlich `vacuum_planner.start_next` auf;
- die dort definierten raumbezogenen Entities und das normalisierte Lifecycle-`event`.

Es gibt keine zusätzliche Planner-`vacuum`-Entity. Die im Config Entry gewählte vorhandene `vacuum.*`-Entity darf nur für Akku-/Dockstatus angezeigt und wird weder ersetzt noch dupliziert. Zulässige Statuswerte und Attribute richten sich ausschließlich nach dem Entity-Vertrag.

**Wichtige Modellentscheidung:** Komplexe Tagesqueue nicht ausschließlich als riesiges Sensorattribut behandeln. Die Integration stellt zusätzlich eine WebSocket-/Coordinator-API für den vollständigen Editorzustand bereit. Sensorattribute bleiben größenbegrenzt, stabil versioniert und für einfache Lovelace-Darstellung geeignet.

### 10.6 Actions/Services für universelle Bedienung

UI und Automationen verwenden ausschließlich die kanonischen Actions:

- `vacuum_planner.start_next` als öffentliche One-Tap-Action
- `vacuum_planner.start_due_block`
- `vacuum_planner.enqueue_area`
- `vacuum_planner.skip_area_today`
- `vacuum_planner.postpone_area`
- `vacuum_planner.cancel_block`
- `vacuum_planner.resolve_uncertain_run`
- optional read-only `vacuum_planner.get_queue`

`vacuum_planner.start_due_block` ist die technische Block-Action zum Versiegeln und Committen eines fälligen Snapshots. Sie ist nicht der One-Tap-Vertrag und wird vom One-Tap-Button nicht direkt aufgerufen.

Selektoren sollen HA-Areas und gültige Enum-Werte anbieten; keine Segment-ID-Eingabe. Action-Responses liefern Block-ID und angenommene Aufgaben, damit die UI korrekt bestätigen kann.

### 10.7 Dashboard-Bereitstellung

**Bevorzugt:** gebündelte Custom Dashboard Strategy `Saugplanung`. Der Nutzer legt das Community Dashboard einmal über die öffentliche HA-Oberfläche an; erst danach wird es dynamisch aus Config Entries, Registry und Planner-Daten generiert.

Anforderungen:

- Bestehende Dashboards nie verändern oder überschreiben.
- Dashboard aus Planner-Geräte-/Entity-Registry dynamisch generieren.
- Mehrere Planner als klar getrennte Views oder auswählbare Instanzen behandeln.
- Nutzeranpassungen und vorhandene Dashboards bleiben unangetastet.
- Entfernen der Integration verändert keine Nutzerdashboards.
- Fällt Frontend-Bundle/Strategie aus, bleiben Entities und Actions funktionsfähig.

**Fallback:** eine vom Release getestete Copy-paste-YAML-Ansicht, die ausschließlich universelle, deterministisch benannte Entitäten verwendet und ohne Anpassung funktioniert. Dieser Fallback ist Dokumentation/Notausgang, nicht Primär-Onboarding. Wenn deterministische Namen wegen HA-Umbenennung nicht garantiert werden können, muss stattdessen ein UI-Import mit Entity-Auswahl angeboten werden; „ohne Anpassung“ darf nicht behauptet werden.

---

## 11. Config Flow, Options Flow und Lovelace-Strategie: Verantwortungsgrenzen

### 11.1 Config Flow – muss leisten

- vorhandene Roboter erkennen und auswählen,
- Kompatibilität/Capabilities prüfen,
- eindeutige Instanz erzeugen und Duplikate verhindern,
- Roboter-Räume abrufen,
- HA-Areas zuordnen und Zuordnung validieren,
- minimalen Startplan anlegen oder bewusst überspringen,
- Dashboard-Opt-in abfragen,
- unvollständige Einrichtung wiederaufnehmbar machen,
- Auth-/Verbindungsfehler der zugrunde liegenden Integration verständlich referenzieren.

**Nicht in Config Flow:** vollständiger fortlaufender Wocheneditor, Tagesqueue, operative Startsteuerung.

### 11.2 Options Flow – muss leisten

- Roboter wechseln/reparieren, soweit technisch sicher,
- Raumdaten neu einlesen und Zuordnungen reparieren,
- Standardverhalten wie Startfenster, Planpausen, Benachrichtigungen und Queue-Regeln,
- Dashboard-/Frontend-Erweiterung aktivieren oder deaktivieren,
- optionale Adapterfunktionen konfigurieren,
- Diagnose und Capability-Neuprüfung anstoßen.

**Nicht als alleinige Lösung:** komplexe Wochenmatrix oder tägliche Ad-hoc-Bedienung. Options Flow bleibt kurz, formularartig und selten genutzt.

### 11.3 Visueller Planungseditor – muss leisten

- Wochenmatrix und mobile Tageslisten,
- Raumdetail, Bulk-Edit, Reihenfolge,
- Konflikte und Vorschau,
- heutige Änderungen versus künftiger Wochenplan,
- Undo und parallele Änderungsauflösung.

Bereitstellung als von der Integration registriertes Frontend-/Panel oder als eng integrierter Konfigurationsdialog. Ziel ist Null-YAML; verwendete Frontend-Assets werden mit der Integration ausgeliefert.

### 11.4 Automatische Lovelace-Strategie – Bewertung

**Stärken:**

- erzeugt aus universellen Entitäten ein konsistentes Dashboard,
- passt sich neuen Räumen und Zuständen dynamisch an,
- reduziert Support für Entity-Namen und YAML,
- kann HA-native Cards/Sections bevorzugen,
- erlaubt eine verwaltete, updatefähige Standardansicht.

**Grenzen/Risiken:**

- Custom Strategy benötigt ein Frontend-Modul und ist versionssensitiver als reine Backend-Entities,
- Strategie-Konfiguration ist für Nutzer nicht der geeignete Plan-Datenspeicher,
- automatische Anlage/Registrierung eines Dashboards darf nicht auf fragile interne Storage-Manipulation setzen,
- manuelle Änderungen an einer generierten Ansicht können beim Regenerieren kollidieren,
- mehrere Planner, deaktivierte Entities und umbenannte Entities müssen sauber behandelt werden.

**Entscheidung:** Strategie nur als Darstellungsschicht. Plan und Queue liegen in der Integration. Das Dashboard wird einmal vom Nutzer über **Einstellungen → Dashboards → Dashboard hinzufügen** angelegt und danach dynamisch aktualisiert. Keine stille Registrierung, kein eigenes Sidebar-Panel als abweichender Primärweg und niemals direkte `.storage`-Manipulation.

---

## 12. Copy-System

### 12.1 Tonalität

- freundlich, konkret, lösungsorientiert,
- kurze Sätze, aktive Verben,
- kein Schuldton („Du hast nicht …“),
- keine unübersetzten technischen Statuscodes.

### 12.2 Kerntexte

| Situation | Copy |
|---|---|
| startbereit | `3 Räume jetzt reinigen` |
| nichts fällig | `Heute ist nichts geplant.` |
| läuft | `Küche wird gereinigt · 1 von 3` |
| wartet auf Bestätigung | `Der Roboter bestätigt den Start …` |
| komplett | `Für heute ist alles erledigt.` |
| Plan pausiert | `Der Wochenplan ist pausiert.` |
| Zusatzjob | `Wohnzimmer wird anschließend gereinigt.` |
| Zuordnung fehlt | `Küche ist noch keinem Roboter-Raum zugeordnet.` |
| offline | `Der Roboter ist nicht erreichbar.` |
| unsicherer Zustand | `Der Startstatus ist noch unklar. Bitte prüfe den Roboter.` |
| Speichern erfolgreich | `Wochenplan gespeichert.` |
| Änderung erst morgen | `Der heutige Block läuft bereits. Die Änderung gilt ab morgen.` |

### 12.3 Button-Regeln

- Verb + Objekt: `Plan speichern`, `Raum zuordnen`, `Erneut versuchen`.
- Kein alleinstehendes `OK`, `Ja`, `Nein` in kritischen Dialogen.
- Destruktiv: `Gesamte Reinigung stoppen`; sicher: `Weiter reinigen`.
- Anzahl in Primäraktion, wenn sie Sicherheit erhöht: `4 Räume jetzt reinigen`.

---

## 13. Fehler-, Leer- und Ladezustände

| Zustand | Darstellung | Primäraktion | Systemverhalten |
|---|---|---|---|
| Kein Roboter gefunden | `Home Assistant kennt noch keinen kompatiblen Saugroboter.` | `Integrationen öffnen` | Deep Link zu Geräte & Dienste; später erneut prüfen |
| Roboter nicht erreichbar | `Der Roboter ist nicht erreichbar. Der Plan bleibt erhalten.` | `Erneut prüfen` | kein Block als gesendet markieren |
| Raumdaten fehlen | `Der Roboter hat noch keine Räume bereitgestellt.` | `Raumdaten neu laden` | Diagnosehinweis, keine manuellen Fantasie-IDs |
| Zuordnung fehlt | `2 geplante Räume müssen noch zugeordnet werden.` | `Räume zuordnen` | betroffene Aufgaben blockiert; andere sichere Aufgaben nach transparenter Bestätigung startbar |
| Mop nicht unterstützt | `Dieser Roboter unterstützt kein Saugen + Wischen.` | `Plan auf Saugen umstellen` | nie still herabstufen |
| Plan leer | `Noch keine Reinigungen geplant.` | `Wochenplan erstellen` | keine leere Queue-Karte |
| Heute leer | `Heute ist nichts geplant.` | `Raum zusätzlich reinigen` | nächsten Termin zeigen |
| Alle erledigt | `Für heute ist alles erledigt.` | `Raum zusätzlich reinigen` | Erledigte grau zeigen |
| Plan pausiert | `Der Plan ist bis morgen pausiert.` | `Jetzt fortsetzen` | keine automatischen Starts |
| Versand fehlgeschlagen | `Der Tagesplan konnte nicht an den Roboter gesendet werden.` | `Erneut versuchen` | identischer Block/Idempotency-Key |
| Bestätigung läuft aus | `Der Roboter hat den Start noch nicht bestätigt.` | `Status prüfen` | Status nicht fälschlich auf idle setzen |
| Teilfehler | `2 Räume erledigt, Küche konnte nicht gestartet werden.` | `Küche erneut versuchen` | erfolgreiche Aufgaben bleiben erledigt |
| Roboter beschäftigt | `Der Roboter führt bereits eine andere Reinigung aus.` | `Später starten` | keine fremde Aufgabe überschreiben |
| Dock-/Wasserproblem | konkrete Meldung, falls Capability vorhanden | `Als erledigt markieren` nicht anbieten; `Status prüfen` | Ursache priorisieren |
| Plan parallel geändert | `Der Plan wurde auf einem anderen Gerät geändert.` | `Neu laden` | kein stilles Last-write-wins |
| Daten werden geladen | Skeleton mit reservierter Höhe | keine | nach 10 s erklärender Zustand statt Endlosspinner |
| HA startet neu | `Saugplanung wird wiederhergestellt …` | keine | serverseitige Queue rekonstruieren |
| Unbekannter Fehler | `Saugplanung konnte nicht geladen werden.` + Referenzcode | `Neu laden` | technische Details nur unter `Details` |

**Teilblock-Regel:** Sind einzelne Räume blockiert, zeigt die UI exakt, was startbar ist: `3 Räume starten · 1 Raum benötigt Zuordnung`. Kein stilles Weglassen. Der Nutzer bestätigt `3 startbare Räume reinigen` oder behebt zuerst das Problem.

---

## 14. WAF-, Touch- und Responsive-Regeln

### 14.1 Zwei-Sekunden-Test

Ohne Scrollen müssen erkennbar sein:

- aktueller Gesamtzustand,
- heutiger Umfang,
- nächste Primäraktion,
- ein eventuell blockierendes Problem.

### 14.2 WAF

- Familienansicht zeigt maximal einen dominanten CTA.
- Icons immer mit Text bei Aktionen; reine Icons nur für etablierte, sekundäre Funktionen mit zugänglichem Label.
- Herstellerbegriffe, Segmentnummern und Entity-IDs bleiben außerhalb der Diagnose.
- Warnungen nur bei Handlungsbedarf; gesunde Zustände ruhig darstellen.
- Keine technische Konfiguration im Alltagsdashboard.
- Standardfall in maximal einem Tap; Zusatzjob in maximal drei Entscheidungen.
- Erfolg bleibt sichtbar, aber grau und leise; Fehler werden nicht durch Rotflächen dramatisiert.

### 14.3 Touch

- Mindestziel 48 × 48 CSS-px; bevorzugt 56 px für Primäraktionen.
- Mindestens 8 px Abstand zwischen benachbarten Touch-Zielen.
- Keine Aktion ausschließlich durch Swipe, Hover, Long-Press oder Drag.
- Primärbutton über volle Kartenbreite auf Mobilgeräten.
- Sticky Save-Leiste darf OS-/HA-Safe-Areas nicht überdecken.
- Doppeltap-Schutz und sichtbarer Pending-Zustand.

### 14.4 Breakpoints als Verhaltensregeln

- **Kompakt (< 600 px):** eine Spalte, Karten stapeln, Tagesansicht statt Wochenmatrix, Bottom Sheet für Auswahl.
- **Mittel (600–1023 px):** zwei Spalten, Hero volle Breite, Queue dominant.
- **Breit (≥ 1024 px):** 8/4-Hauptlayout; keine unlesbar breiten Textzeilen.
- Nicht nur Pixelbreite prüfen: HA-Sidebar, Tablet-Hochformat, eingebettete Panels und Zoom bis 200 % berücksichtigen.

### 14.5 Visuelle Sprache

- HA-Theme-Farben und semantische Tokens nutzen; keine hart codierten Hellmodusfarben.
- Akzent für aktive/primäre Zustände, neutrales Grau für erledigt, Warn-/Fehlerfarben sparsam.
- Modus nie nur per Farbe: Text `Saugen` / `Saugen + Wischen` und unterschiedliche Icons.
- Radius, Schatten und Cards zurückhaltend; Informationshierarchie entsteht primär durch Typografie und Abstand.
- Animationen 150–250 ms; `prefers-reduced-motion` respektieren.

---

## 15. Accessibility

Ziel: WCAG 2.2 AA im eigenen Frontend, soweit Home-Assistant-Host und verwendete Komponenten dies ermöglichen.

### 15.1 Semantik und Tastatur

- Korrekte Überschriftenhierarchie, Landmarks und Listensemantik.
- Alle Funktionen per Tastatur; sichtbarer Fokus mit mindestens 3:1 Kontrast zum Umfeld.
- Logische Fokusreihenfolge entspricht visueller Reihenfolge.
- Dialog öffnet Fokus auf Titel/erste sinnvolle Aktion, hält Fokus und gibt ihn beim Schließen zurück.
- Drag-Reihenfolge zusätzlich per Buttons und Tastatur veränderbar; Screenreader meldet `Küche an Position 2 verschoben`.

### 15.2 Screenreader und Live-Zustände

- Buttons erhalten vollständige Namen: `Tagesplan mit 3 Räumen starten`.
- Icon-only Controls besitzen lokalisierte Accessible Names.
- Statusänderungen über zurückhaltende Live Region: `Reinigung gestartet. Küche ist zuerst dran.`
- Laufender Fortschritt nicht bei jedem Prozentpunkt ansagen; nur relevante Etappen.
- Fehler mit betroffenem Feld programmatisch verknüpfen; Fokus auf Fehlerzusammenfassung nach fehlgeschlagenem Submit.

### 15.3 Kontrast, Farbe, Zoom

- Textkontrast mindestens 4,5:1; großer Text 3:1; UI-Komponenten/Fokus 3:1.
- Erledigt-Grau muss weiterhin lesbar sein; nicht durch niedrige Opazität unter Kontrastgrenze drücken.
- Status nie nur durch Farbe.
- Reflow bei 320 CSS-px und 400 % Zoom ohne Verlust zentraler Funktionen.
- Systemschrift und HA-Schriftgrößen respektieren; keine festen Höhen für mehrzeilige deutsche Texte.

### 15.4 Sprache und Kognition

- Kurze, konkrete Sätze; Abkürzungen vermeiden.
- Datum lokal formatiert: `Mi., 16. September`, nicht interner Timestamp.
- Zeitangaben mit absolutem Anker, wenn Missverständnis möglich ist: `morgen, Do. 17. September`.
- Bestätigungen nennen Objekt und Folge.
- Keine automatische Zeitüberschreitung bei wichtigen Dialogen.

---

## 16. Kritischer User-Journey-Review

### Journey A – Ersteinrichtung bis erster Erfolg

**Happy Path:** Integration hinzufügen → Roboter wählen → Capabilities verstehen → Räume zuordnen → Planvorschlag bestätigen → Dashboard öffnen → Tagesblock starten.

**Kritische Risiken:**

1. **Raumzuordnung ist schwer verständlich** (hoch): Robotername und HA-Area können abweichen.
   **Mitigation:** Vorschläge, Karte/Identifikation wenn verfügbar, klare Zwei-Seiten-Sprache, bewusste Bestätigung.
2. **„Fertig“ trotz nicht startfähigem Plan** (kritisch).
   **Mitigation:** Completion Gate: mindestens ein sicher zugeordneter, geplanter Raum; sonst Status `Einrichtung fortsetzen`.
3. **Capability-Überversprechen** (kritisch).
   **Mitigation:** Nutzerfolgen statt technische Flags; degradierte Ausführung transparent darstellen.
4. **Dashboard erscheint unerwartet** (mittel).
   **Mitigation:** explizites, vorausgewähltes Opt-in und Zusage, bestehende Dashboards nicht zu ändern.

**Abnahmekriterium:** Ein technisch durchschnittlicher HA-Admin kann ohne Entity-ID innerhalb von fünf Minuten eine sichtbare, startfähige Aufgabe erzeugen.

### Journey B – Morgendlicher One-Tap-Start

**Happy Path:** Dashboard öffnen → `3 Räume jetzt reinigen` erkennen → tippen → Versand/Bestätigung sehen → Queue verfolgt Fortschritt.

**Kritische Risiken:**

1. **Unklar, was gestartet wird** (kritisch).
   **Mitigation:** Räume und Modus direkt über dem CTA; keine generische Startcopy.
2. **Doppeltap erzeugt doppelten Lauf** (kritisch).
   **Mitigation:** sofort sperren, idempotenter Block, serverseitige Block-ID.
3. **UI meldet Erfolg vor Roboterbestätigung** (hoch).
   **Mitigation:** drei Zustände `wird vorbereitet` → `gesendet` → `gestartet`.
4. **Ein blockierter Raum verhindert alles ohne Wahl** (hoch).
   **Mitigation:** Problem und startbare Teilmenge zeigen; Nutzer entscheidet bewusst.

**Abnahmekriterium:** Testpersonen können nach zwei Sekunden sagen, welche Räume und welcher Modus durch den Button gestartet werden.

### Journey C – Spontaner Zusatzjob während der Tagesblock läuft

**Happy Path:** `Raum zusätzlich reinigen` → Raum + Modus → Zusammenfassung → anhängen → Queue zeigt Zusatzjob hinter Block.

**Kritische Risiken:**

1. **Nutzer glaubt, der laufende Block werde geändert** (hoch).
   **Mitigation:** Copy `wird anschließend gereinigt`, visuelle Gruppe `Zusatzjobs`.
2. **Doppelte Reinigung desselben Raums** (mittel).
   **Mitigation:** Duplikatwarnung mit bewusster Bestätigung.
3. **Adapter kann nicht anhängen** (hoch).
   **Mitigation:** Integration orchestriert sequenziell; UI sagt `Home Assistant startet den Zusatzjob danach`.

**Abnahmekriterium:** Ein Zusatzjob ist in höchstens drei Entscheidungen angehängt und seine Position ist eindeutig.

### Journey D – Wochenplan ändern, während heute schon läuft

**Happy Path:** Plan öffnen → Änderung → Speichern → klare Aussage `gilt ab morgen` → optional Zusatzjob heute.

**Kritische Risiken:**

1. **Mentaler Konflikt zwischen Plan und eingefrorenem Block** (kritisch).
   **Mitigation:** heutiger Block als Snapshot; Dialog trennt `ab morgen` und `heute hinzufügen`.
2. **Verlust paralleler Änderungen** (hoch).
   **Mitigation:** Versionsprüfung und Konfliktdialog.
3. **Mobile Matrix unbedienbar** (hoch).
   **Mitigation:** mobile Tages-/Raumkarten statt geschrumpfter Desktopmatrix.

### Journey E – Raumzuordnung bricht nach Kartenänderung

**Happy Path:** Attention-Hinweis → `Räume zuordnen` → alte/neue Segmente vergleichen → reparieren → blockierte Aufgabe erneut starten.

**Kritische Risiken:**

1. **Stilles Reinigen des falschen Raums** (kritisch).
   **Mitigation:** Mapping-Identität validieren; unsichere Zuordnung blockieren statt raten.
2. **Historie/Plan geht bei Reparatur verloren** (hoch).
   **Mitigation:** Plan bindet an HA-Area, Segmentzuordnung ist austauschbarer Adapter-Layer.
3. **Alle Aufgaben werden unnötig blockiert** (mittel).
   **Mitigation:** nur betroffene Räume blockieren; sichere Räume transparent startbar lassen.

### Journey F – Fehler nach teilweise erfolgreichem Block

**Happy Path:** Queue zeigt erledigte Räume grau, fehlgeschlagenen Raum rot/konkret → `Erneut versuchen` erzeugt nur verbleibende Aufgabe.

**Kritische Risiken:**

1. **Gesamten Block versehentlich wiederholen** (kritisch).
   **Mitigation:** Retry ist auf fehlgeschlagene/offene Aufgaben begrenzt und nennt Raum.
2. **Erfolg verschwindet aus Queue** (mittel).
   **Mitigation:** erledigte Einträge bleiben bis Tagesende grau sichtbar.

### Review-Fazit

Die größten Produktgefahren liegen nicht in der Wochenmatrix, sondern an drei Systemgrenzen:

1. HA-Area ↔ Herstellersegment,
2. UI-Tap ↔ bestätigter Roboterstart,
3. lebender Wochenplan ↔ eingefrorener Tagesblock.

Diese Grenzen müssen als explizite Zustände im Datenmodell und in der Copy existieren. Werden sie nur implizit in Automationen behandelt, kann das Interface weder korrekt noch vertrauenswürdig sein.

---

## 17. Produkt- und Telemetrie-Kriterien

Datenschutzfreundlich und standardmäßig lokal. Falls anonyme Produkttelemetrie überhaupt angeboten wird, nur Opt-in und ohne Raum-/Gerätenamen.

Sinnvolle lokale Diagnose-/Qualitätskennzahlen:

- Anteil vollständig abgeschlossener Onboardings,
- Abbruchschritt ohne personenbezogene Inhalte,
- Startbestätigungslatenz,
- Dispatch-/Teilfehlerrate nach Adaptertyp,
- Häufigkeit reparierter Mappings,
- Anzahl Doppeltap-Abwehrfälle,
- Queue-Rekonstruktion nach Neustart.

UX-Erfolgskriterien:

- ≥ 90 % erkennen im 2-Sekunden-Test nächste Aktion und Umfang.
- ≥ 95 % starten Happy Path beim ersten Versuch.
- 100 % aller Hauptaktionen sind ohne Gesten, Maus und YAML erreichbar.
- Kein Testfall kann durch Doppeltap denselben Block zweimal senden.
- Kein Mapping-Fehler führt still zur Reinigung eines anderen Raums.

---

## 18. Umsetzungspriorität

### P0 – Vertrauensfähiger Kern

- Config Flow mit Capability- und Mapping-Validierung,
- universelles Entity-/Action-Modell,
- Tagesblock mit idempotentem Start,
- Dashboard-Hero und Tagesqueue,
- erledigt-grau, blockiert/Fehler/Timeout,
- Wochenplan-Basiseditor,
- responsive und tastaturbedienbar.

### P1 – Alltagskomfort

- Zusatzjobs nach Blockstart,
- Verschieben/Überspringen/Undo,
- Vorschau nächste sieben Tage,
- verwaltetes Dashboard + eigene Kopie,
- Verlauf und Benachrichtigungen,
- Multi-Edit.

### P2 – Adapterabhängige Verfeinerung

- Karte zur Raumidentifikation,
- belastbare Dauerprognose,
- Reinigungsintensität/Wiederholungen,
- mehrere Roboter und Aufgabenzuteilung,
- erweiterte Diagnose.

---

## 19. QA-/Abnahmecheckliste

### Onboarding

- [ ] Einrichtung ohne YAML, Entity-ID oder Entwicklerwerkzeuge möglich
- [ ] Kein scheinbarer Abschluss ohne startfähigen Raum
- [ ] Raumvorschläge werden bestätigt, nicht still übernommen
- [ ] Capability-Einschränkungen werden als Nutzerfolge erklärt
- [ ] Bestehende Dashboards bleiben unverändert

### Alltag

- [ ] Hero beantwortet Was, Umfang und nächste Aktion über dem Fold
- [ ] One-Tap startet nur den fälligen offenen Block
- [ ] Doppeltap ist technisch und visuell abgefangen
- [ ] Gesendet und vom Roboter gestartet sind getrennte Zustände
- [ ] Queue enthält nur geplante Räume und bestätigte Zusatzjobs
- [ ] Erledigte Aufgaben bleiben grau sichtbar
- [ ] Nirgendwo wird „nur Wischen“ angeboten

### Planung

- [ ] Mobile Bedienung benötigt keine 7-Spalten-Matrix
- [ ] Reihenfolge ist ohne Drag-and-drop änderbar
- [ ] Heutiger Snapshot und künftiger Plan sind klar getrennt
- [ ] Parallele Änderungen überschreiben sich nicht still
- [ ] Undo für Überspringen und Planänderungen vorhanden

### Fehler & Accessibility

- [ ] Jeder Fehler nennt Ursache, Folge und nächste Lösung
- [ ] Status wird nicht allein über Farbe vermittelt
- [ ] Alle Ziele mindestens 48 × 48 CSS-px
- [ ] Vollständig per Tastatur und Screenreader bedienbar
- [ ] Reflow/Zoom und lange deutsche Texte geprüft
- [ ] Reduced Motion und Theme-Farben unterstützt

---

## 20. Design-Handoff an Entwicklung

### Backend-Vertrag

- Stable Planner-ID, Area-basierte Pläne, austauschbares Segment-Mapping.
- Versionierter Plan und versionierter Tagesblock.
- Idempotenter Dispatch und rekonstruierbare Zustände.
- Explizite Reason Codes, die im Frontend lokalisiert werden; keine Backend-Fehlersätze als UI-Copy.
- Capability-Modell bestimmt sichtbare Optionen.
- Vollständige Queue über Coordinator/WebSocket; kompakte Zustände über Entities.

### Frontend-Vertrag

- Kein herstellerspezifischer Code in Dashboard-Komponenten.
- Alle Screens mit Loading, Empty, Partial, Error und Offline ausdesignen.
- HA-native Komponenten zuerst; Custom CSS nur zur Hierarchie, nicht zur Strukturreparatur.
- Managed Strategy/Panel funktional unabhängig vom Kern halten.
- Visuelle Regressionen für Mobil, Tablet, Desktop, Hell/Dunkel und 200-%-Zoom.

### Copy-/Lokalisierungsvertrag

- Alle Texte über Translation Keys.
- Pluralisierung korrekt (`1 Raum`, `2 Räume`).
- Datums-/Zeitformat aus HA-Locale/Timezone.
- Reason Codes erhalten handlungsorientierte Texte und passende Deep Links.

---

## 21. Annahmen und offene technische Validierungen

Dieses Dokument ist ein UX-/Produktkonzept; es wurden auftragsgemäß keine Live-Tests und keine Home-Assistant-Schreibzugriffe durchgeführt.

Vor Implementierung technisch zu validieren:

1. Welche öffentliche HA-Schnittstelle im Zielrelease die sichere Anlage/Registrierung eines dedizierten Dashboards erlaubt.
2. Ob die Custom-Lovelace-Strategy als stabiler öffentlicher Erweiterungspunkt für den geplanten Distributionsweg gilt; andernfalls Sidebar-Panel priorisieren.
3. Welche Adapter einen echten Mehrraumblock akzeptieren und welche sequenziell orchestriert werden müssen.
4. Wie Roboter-Raumidentitäten Kartenänderungen überstehen und wann Mapping invalidiert wird.
5. Welche Queue-/Attributgrößen in HA performant und recorderfreundlich bleiben.
6. Wie Startbestätigung und Recovery je Adapter belastbar erkannt werden.

Die UX darf bei keiner dieser Unsicherheiten Fähigkeit vortäuschen. Capability-gating, explizite Zwischenzustände und sichere Degradation sind Teil des Produkts, nicht nachträgliche Fehlerbehandlung.
