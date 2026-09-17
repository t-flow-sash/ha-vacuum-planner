# Anforderungs-Nachverfolgung

Quelle ist das am 16. September 2026 übergebene Projektbriefing `vacuum_planner.xml`. Diese Matrix zeigt, wo jede Anforderung konkret entschieden oder spezifiziert wurde.

| Briefing-Anforderung | Umsetzung/Entscheidung | Nachweis |
|---|---|---|
| Einrichtung ohne KI, Coding oder YAML | Custom Integration mit Config-, Reconfigure- und Options-Flow | [ADR 0001](adr/0001-solution-shape.md), [Config Flow](config-flow-and-dashboard.md) |
| Tagesplanung wird beim Start als dynamischer geschlossener Block übertragen | Unveränderlicher Snapshot; vollständiges Sealing vor externem Commit | [Queue-Semantik](queue-semantics.md) |
| Zusätzliche Aufgaben nach Start anhängen | Append-Gate öffnet erst nach Commit; Ad-hoc-Jobs stehen hinter dem Block | [Queue-Semantik](queue-semantics.md), [UX](ux-specification.md) |
| Weitestgehend herstellerunabhängig inklusive Core/HACS/Custom Repos | Nativer `vacuum.clean_area`-Pfad plus capability-basierte Adapter; Markt-Matrix mit Quellen | [Architektur](architecture.md), [Kompatibilitätsmatrix](compatibility.md) |
| Einschränkungen und Payoffs klar ausweisen | Autoritative Capability-Matrix; Planner- und Robot-Atomizität getrennt | [Capabilities](capabilities.md), [ADR 0001](adr/0001-solution-shape.md) |
| Entwicklung nicht durch schwächere Integrationen blockieren | Capability-gesteuerte Degradation und separater Whole-home-Modus statt kleinstem gemeinsamen Nenner | [Capabilities](capabilities.md), [Roadmap](roadmap.md) |
| Primär `vacuum.*` und native Raumfunktionen | HA Area IDs als öffentliche Raumidentität; `vacuum.clean_area` bevorzugt | [Architektur](architecture.md), [Kompatibilitätsmatrix](compatibility.md) |
| Fehlende Raumzuordnung verständlich melden | Onboarding-Gate, Retry und Repair mit konkreter Nutzerführung | [Config Flow](config-flow-and-dashboard.md), [UX](ux-specification.md) |
| Standarddashboard universell beliefern | Stabiler Entity-/Action-Vertrag; große Queue-Daten via Response/WebSocket | [Entity-Vertrag](entity-contract.md) |
| Eigenes Hauptdashboard oder Copy-paste ohne Anpassung | Explizit bestätigte Dashboard Strategy; bestehende Dashboards bleiben unangetastet | [Config Flow](config-flow-and-dashboard.md), [UX](ux-specification.md) |
| Keine Live-Tests in dieser Phase | Ausschließlich read-only Inventar, statische Recherche und Dokumentprüfung | [Current State](current-state.md), [Roadmap](roadmap.md) |
| Sub-Agenten/UX-Agent parallel einsetzen | Architektur-, Integrations-/Markt- und UX-Reviews wurden getrennt parallel erstellt und anschließend konsolidiert | diese Spezifikationssammlung |
| Teilergebnisse gemeinsam prüfen | Widersprüche zwischen Capability-Tiers, Dashboard-Transport und Markt-Matrix wurden im Consolidation Review bereinigt | [Capabilities](capabilities.md), [Entity-Vertrag](entity-contract.md), [Kompatibilitätsmatrix](compatibility.md) |
| Privates GitHub-Repository | Repository bleibt privat; `main` enthält alle Spezifikationsartefakte | Projekt-README und Repository-Einstellungen |
| Parallelisierung | Architektur/Concurrency, Plattformrecherche und UX liefen als unabhängige Workstreams | diese Spezifikationssammlung |

## Zusätzliche verbindliche Produktregeln

Aus dem etablierten System wurden außerdem übernommen:

- kein `mop_only`: Wischen bedeutet immer **Saugen+Wischen**;
- One-Tap startet die aktuell fällige Aufgabe idempotent;
- die Tagesqueue zeigt nur geplante Räume;
- erledigte Räume bleiben bis Tagesende sichtbar und werden grau/dezent dargestellt;
- Dispatch/Akzeptanz ist niemals gleichbedeutend mit erfolgreicher Reinigung;
- ein unsicherer Lauf wird nicht automatisch als erfolgreich gewertet.
