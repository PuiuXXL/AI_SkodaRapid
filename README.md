# AI_SkodaRapid: DriveMate

AI driver-monitoring copilot, built at CodeLap Hackathon 2026 (AI Drive track).

> Work in progress. Setup and run instructions will be added here.

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
