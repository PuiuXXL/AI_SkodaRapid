# P4 · Dashboard and route simulator

[Project setup](../README.md) · [Role brief](../roluri/P4-dashboard-simulator-contact.md)

The dashboard is a React application for the driver and the demo operator. Every live reading, event and camera frame comes from core or perception. Missing/stale readings appear as `—` and backend-dependent controls are disabled.

## Tech stack

| Technology | Use |
| --- | --- |
| React 19 + TypeScript | Components, typed state consumers and page shell |
| Vite | Local dev server, build and backend proxy |
| Motion | Shared navigation selection, disclosures and instrument-stack transitions |
| CSS variables / SVG | Shared themes, chart primitives and responsive layouts |
| Leaflet | Map interaction and route overlays |
| OpenStreetMap / OSRM | Online map tiles, road snapping and driving routes |
| Wikipedia API | Candidate places of interest near the route |
| Browser WebSocket | Core state, commands and speech feedback |
| Web Speech / Web Audio | Driver speech input and prioritized audio output |
| Node.js + esbuild + react-dom/server | Rendering/contract regression tests |

GSAP is available as an existing dependency for scoped entrance helpers. Current navigation, theme and card behaviour is implemented with Motion and CSS. Dependencies are listed in `package.json`.

## Implementation

- `src/main.tsx` mounts the application and loads the final visual layers.
- `driver/DriverApp.tsx` owns routes, navigation, theme, persistent preferences and the shared driver session.
- `NavigationShell.tsx` implements expanded/collapsed desktop navigation and the mobile dialog with Escape/focus restoration.
- `driver/session.ts` consumes `/ws/ui`, reconnects and marks state stale after 2.5 seconds.
- `session-state.ts` maintains bounded history/event buffers and inserts gaps for missed state sequences.
- `driver/audio.ts` coordinates microphone, dialogue and a single active audio session.
- `voice/` contains speech input, dialogue-window tracking, playback and priority queues.
- `Cockpit.tsx` presents the voice copilot and essential driver information.
- `MonitorPage.tsx`, `Panels.tsx`, `MonitorParts.tsx` and `ControlPanel.tsx` expose observations, diagnostics and commands.
- `charts.tsx` and `ScoreHistory.tsx` draw faithful SVG/CSS charts, preserving unknown values and gaps.
- `route-simulation.ts`, `RouteMap.tsx` and `Simulator.tsx` plan/edit routes and control core's simulation.

### Pages

| Route | Screen |
| --- | --- |
| `#/` | Cinematic landing |
| `#/salut` | Wait for core's first state |
| `#/volan` | At the wheel |
| `#/dashboard` | Telemetry, cameras, instrument stack, event journal and controls |
| `#/setari` | Suggestion frequency, answer length and follow-up preferences |
| `#/simulator` | Map route, stops, attractions, file transfer and playback |

The navigation follows the real route and stores collapsed/theme preferences in localStorage. English UI labels are independent of the Romanian voice backend.

## Install and run

Start the backend from the repository root in separate terminals:

```bash
python -m core.main
python -m perception.main
```

Alternatively, use `python -m scripts.fake_perception` instead of real perception for a camera-free scenario demo.

Then:

```bash
cd dashboard
npm ci
npm run dev
```

On Windows use `npm.cmd`. Open Vite's printed URL. Click **Connect**, then enable voice/audio when needed. Press **D** to request the perception debug overlay.

Production build and local preview:

```bash
npm run build
npm run preview
```

A deployed build needs a serving setup for the frontend and reachable core/MJPEG endpoints. The Vite development proxy is a local development configuration.

## Endpoint configuration

Put public browser overrides in `dashboard/.env.local`, then restart Vite.

| Variable | Default |
| --- | --- |
| `VITE_UI_WS` | `ws://localhost:8000/ws/ui` |
| `VITE_VIDEO_ORIGIN` | `http://localhost:8001` |
| `VITE_EYE_STREAM_URL` | Optional real eye-crop stream, with no default |

Vite proxies `/tts`, `/media` and `/simulator` to `http://localhost:8000`. Remote clients must use a reachable backend address. HTTPS pages require WSS/HTTPS upstreams. Never put credentials in `VITE_*` variables.

## Route simulation

1. Place the start and destination on the map.
2. Add typed stops or pass-through waypoints. Reorder with the controls, drag handle or arrow keys.
3. OSRM calculates the road geometry. Wikipedia supplies nearby attractions, which can be selected or described manually.
4. Send the `drivemate_route` v1 file through `PUT /simulator/route`.
5. Core's `simulator/` module advances the vehicle. Start, pause, speed, time-scale and seek controls operate on core.
6. The map and trip details reflect `State.trip`.

The route can also be downloaded as JSON. The browser performs route planning and display; vehicle movement belongs to core. Map/routing/attraction services require internet connectivity.

## Visual system

Shared tokens live in `src/voice/obsidian-tokens.css`. The workspace uses graphite, silver, a light default theme, selectable dark mode and cyan actions. Approved logos are in `public/brand/`.

`fluid.css`, `workspace.css` and `navigation.css` provide the final presentation layers. Individual transparent illustrations live in `src/voice/illustrations/`. Local font files and their licence live in `public/fonts/`. Reduced-motion preferences are honoured.

Camera failures show a status and retry control. Camera panels do not use decorative replacement images.

## Validation

```bash
npm run typecheck
npm run build
node tests/run.mjs
node --test tests/voice.test.mjs
```

Tests cover partial/stale state, zero values, unreliable eyes, history gaps, bounded buffers, core command mappings, route-file contracts and settings. Shared JSON fixtures under `../tests/contract/fixtures/` are checked by both Python and the dashboard.

For backend route checks:

```bash
python -m pytest tests/contract/test_dashboard_commands.py tests/contract/test_dashboard_route.py tests/simulator -q
```

Run that command from the repository root. Browser layout and real microphone/camera behaviour require their corresponding interactive checks.

## Contact integration boundary

The original P4 brief also describes a trusted-contact application. Core exposes an optional `integrations.contact_app` integration point. That dedicated module is absent in this checkout, so this README documents the dashboard and simulator that are present. The phone bridge and core notification state can be inspected independently.
