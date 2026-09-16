# HA Vacuum Planner

Herstellerbewusste, raumbasierte Saugerplanung für Home Assistant – ohne YAML-Zwang für Anwender.

> **Projektstatus:** Architektur- und Spezifikationsphase. Noch keine Live-Tests und keine Änderungen an einer produktiven Home-Assistant-Instanz.

## Produktziel

HA Vacuum Planner soll aus Home-Assistant-Räumen und einer vorhandenen `vacuum.*`-Entität einen verständlichen Reinigungsplan erzeugen. Der Tagesplan wird beim Start als zusammenhängender Block eingeplant. Danach können weitere spontane Aufgaben an die Queue angehängt werden.

Leitplanken:

- Einrichtung vollständig über die Home-Assistant-Oberfläche
- primär Standard-Entitäten und native Areas
- Herstellerfunktionen über klar abgegrenzte Adapter
- transparente Capability-Tiers statt falscher Universalitätsversprechen
- universeller Entity-Vertrag für ein mitgeliefertes Dashboard
- niemals ausschließlich wischen: Raumaufgaben sind Saugen oder Saugen+Wischen
- One-Tap startet die aktuell fällige Aufgabe
- in der Queue erscheinen nur geplante Räume; erledigte Einträge werden visuell zurückgenommen

## Dokumentation

- [Produktanforderungen](docs/requirements.md)
- [Bekannter Ausgangszustand](docs/current-state.md)
- [Architekturentscheidung](docs/adr/0001-solution-shape.md) *(in Review)*
- [Queue- und Block-Semantik](docs/queue-semantics.md)
- [Universeller Entity-Vertrag](docs/entity-contract.md)
- [Kompatibilitätsmatrix](docs/compatibility.md) *(in Arbeit)*
- [UX-Spezifikation](docs/ux-specification.md) *(in Arbeit)*
- [Roadmap](docs/roadmap.md) *(in Arbeit)*

## Entwicklungsgrundsätze

1. Keine produktiven Live-Tests in der ersten Phase.
2. Statische Prüfungen und Unit-Tests gegen simulierte Coordinator-/Adapterobjekte sind erlaubt.
3. Core-Funktionen dürfen nicht von einem einzelnen Hersteller abhängen.
4. Herstelleradapter müssen degradieren können, ohne den Planner unbrauchbar zu machen.
5. Aktuelle Home-Assistant-APIs und Integrationsrichtlinien sind maßgeblich.

## Lizenz

Noch nicht festgelegt. Das Repository ist privat.
