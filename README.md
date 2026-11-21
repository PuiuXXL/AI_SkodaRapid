# DriveMate

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="dashboard/public/brand/drivemate_full_dark.svg">
  <img alt="DriveMate" src="dashboard/public/brand/drivemate_full_light.svg" width="220">
</picture>

AI driver-monitoring copilot, built at CodeLap Hackathon 2026 (AI Drive track).

> Work in progress. Setup and run instructions will be added here.

## Design și contribuții

Interfețele web folosesc [DriveMate Graphite](.agents/skills/obsidian-orange-web-skill/SKILL.md). Pachetul complet este inclus în repository. Vezi [regulile pentru agenți](AGENTS.md) și [aplicarea în DriveMate](docs/design/obsidian-orange.md) înainte de modificări UI.

## Repository structure

| Folder | Purpose |
|---|---|
| `shared/` | JSON state contract shared by all modules |
| `perception/` | Computer vision: driver and passenger cameras |
| `core/` | Context engine, safety rules, SOS |
| `assistant/` | LLM copilot and voice |
| `integrations/` | Phone bridge, emergency call, contact page |
| `simulator/` | Simulated route, director panel, replay |
| `dashboard/` | Live web dashboard |
| `profiles/` | Driver and passenger profiles |
| `scripts/` | Utilities: model download, benchmark, fake data |
| `tests/` | Tests per module |
| `docs/` | Documentation |
| `presentation/` | Final presentation (`AI_SkodaRapid.pptx`) |
| `requirements/` | Python dependencies per module |
