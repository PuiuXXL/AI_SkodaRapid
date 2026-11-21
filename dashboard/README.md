# DriveMate dashboard

P4's React + TypeScript dashboard. **Live only**: every value, event and camera image comes from the running system
(core on `/ws/ui`, P1's MJPEG streams). There is no simulated source, demo server or placeholder data in the
frontend; without core the pages say so and show `—`.

Start the backend first (repo root), then the dashboard:

```sh
python -m core.main            # P2: ws://localhost:8000/ws/ui
python -m perception.main      # P1: cameras, http://localhost:8001/video/{driver,passenger}
```

```sh
cd dashboard
npm ci
npm run dev
```

Open the local URL printed by Vite. Production: `npm run build`, then `npm run preview`.

## Pages

- `#/` start page (Connect) → `#/salut` waits for core's first state → `#/volan`.
- **La volan** (`#/volan`): voice copilot, safety, road, sound and music, messages.
- **Dashboard** (`#/dashboard`): cameras, status, KPIs, overview and the instrument stack. Its **Control** card sends
  every command core accepts (trip, scenes, LLM, declared child, test phone message, debug overlay, calibration,
  enrolment). Speed, time scale and scenes drive core's own trip simulator; the dashboard simulates nothing.
- **Simulator locație** (`#/simulator`): build a road route on the map (origin, typed stops, destination), send the
  route file to core (`PUT /simulator/route`, proxied by Vite) or download it as `drivemate-route.json`, then drive it:
  core's trip source (`simulator/`) moves the car and the map shows `State.trip.pos`. Tourist sights within 2 km of
  the road come from Wikipedia (or are added on the map); core proposes the chosen ones as breaks. See
  `docs/design/dashboard-react-typescript.md` (Simulatorul de locație → core).
- The account block in the sidebar shows the driver profile P1 recognised and has **Ieșire** (back to the start page).
- Stale data (no state for 2.5 s) is shown as no data, never as the last values; buttons are disabled while core is
  not connected. Press **D** to toggle P1's debug overlay.

## Configuration

Set these optional variables in `dashboard/.env.local`, then restart Vite:

| Variable | Default / purpose |
| --- | --- |
| `VITE_UI_WS` | `ws://localhost:8000/ws/ui` |
| `VITE_VIDEO_ORIGIN` | `http://localhost:8001` |
| `VITE_EYE_STREAM_URL` | Optional P1 eye-crop stream; no default or fabricated live crop |

Use the backend machine's reachable address when opening the dashboard on another device. For HTTPS, use WSS and HTTPS upstreams. Vite proxies `/tts`, `/media` and `/simulator` to local core port 8000. Client environment variables are public; do not put credentials in them.

## Validation

```sh
npm run typecheck
npm test
npm run build
```

Tests cover rendering with partial, empty and stale data, zero values, invalid reaction baselines, unreliable eyes, sequence gaps, bounded session buffers and the command bridge. They do not replace browser layout checks or a live P1–P3 run (`tests/integration` covers perception → core).

## Visual layer and backend actions (2026-11-21)

- `src/fluid.css` is loaded last (`src/main.tsx`): neutral graphite / silver gradients, tonal surfaces without outlines, light theme by default (AGENTS.md) and dark selectable. Older stylesheets stay underneath; new components use the `fx-` classes.
- `src/charts.tsx`: SVG chart primitives (area sparkline, mini columns, half gauge, ring, ranked bars, share bar, p50-p95 ranges, heat strip, head-pose dial). A missing reading is a gap or a dash, never a drawn value. `src/telemetry.ts` keeps about one minute of the state stream (2 Hz) for them.
- **Commands.** The buttons send the contract's messages on `/ws/ui` (`liveMessage` in `src/driver/session.ts`): `UiCommand` for the 14 `UI_COMMANDS` and `UiSpeech` for requests, answers and "stop the music". The Control card of the Dashboard exposes all of them. `tests/contract/fixtures/dashboard_ui_messages.json` is checked on both sides (`npm test` here, `tests/contract/test_dashboard_commands.py` against core).
- The instrument cards are a scroll-driven stack (`InstrumentStack.tsx`): the stage is one viewport tall, the page settles on the nearest card (`scrollend`), and the docked camera preview sits in reserved slots (`data-camera-slot`) instead of floating over content.

## Structure

`src/main.tsx` mounts the app; `driver/DriverApp.tsx` is the shell (navigation, theme, account). `driver/session.ts` is the only data source (core's `/ws/ui`, with reconnect and a staleness watchdog) and `driver/audio.ts` the browser voice; `session-state.ts` owns buffer updates. `driver/Cockpit.tsx` and `driver/MonitorPage.tsx` are the two pages; `App.tsx`, `Panels.tsx`, `Overview.tsx`, `driver/MonitorParts.tsx` and `driver/ControlPanel.tsx` render their modules. `types.ts` describes optional consumer fields without changing the shared backend contract. `design.css` is the active stylesheet; `monitor.css` retains the earlier design.

The official Motion skill is stored in `.agent-skills/motion/`. Official GSAP core, React, timeline, and performance skills are also stored in `.agent-skills/`. They were loaded explicitly for this implementation.

The current theme combines Midnight Steel, Deep Horizon, and American Denim Fade gradients. Navigation is integrated into the transparent top header. Cards use tinted translucent surfaces; the camera, charts, and indicators follow the same palette. Alarm and waiting states keep their distinct warning colors.

GSAP handles a short entrance sequence through `useDashboardEntrance.ts`, scoped and cleaned up with `useGSAP` and `gsap.matchMedia`. Motion handles section transitions, the shared selection indicator, disclosures, and reaction markers. The libraries target separate elements. Score history and alerts update directly. Both animation paths respect reduced motion.
