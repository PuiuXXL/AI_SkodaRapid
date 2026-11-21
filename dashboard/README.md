# DriveMate dashboard

P4's local React + TypeScript dashboard. Start in simulated mode; select **Live · local** to connect to P2 and P1. Simulated readings are synthetic and use the provisional P3 fixture.

P2 integration handoff: [simulator location payload, proposed transport, ownership and acceptance checks](../docs/design/dashboard-react-typescript.md#contract-de-integrare-simulator--p2--21-noiembrie-2026). The route simulator currently previews/copies JSON locally; it does not send location to core.

```sh
cd dashboard
npm ci
npm run dev
```

Open the local URL printed by Vite. Production: `npm run build`, then `npm run preview`.

## Controls

- Section buttons select overview, gaze/reaction, cabin/assistant, trip report, or system performance. Arrow keys, Home and End move between section buttons.
- Compact reduces card padding. Camera and general driver state remain mounted when changing sections.
- Live uses the existing WebSocket and MJPEG interfaces. Expand the passenger camera to load its stream. Press **D** to request the core's debug toggle.
- Voice activation uses P3's existing module and requires an open socket and a browser gesture. Camera placeholders and missing readings stay explicit.

## Configuration

Set these optional variables in `dashboard/.env.local`, then restart Vite:

| Variable | Default / purpose |
| --- | --- |
| `VITE_UI_WS` | `ws://localhost:8000/ws/ui` |
| `VITE_VIDEO_ORIGIN` | `http://localhost:8001` |
| `VITE_EYE_STREAM_URL` | Optional P1 eye-crop stream; no default or fabricated live crop |

Use the backend machine's reachable address when opening the dashboard on another device. For HTTPS, use WSS and HTTPS upstreams. Vite proxies `/tts` and `/media` to local core port 8000. Client environment variables are public; do not put credentials in them.

## Validation

```sh
npm run typecheck
npm test
npm run build
```

Tests cover rendering with partial data, zero values, invalid reaction baselines, unreliable eyes, sequence gaps, and bounded session buffers. They do not replace browser layout checks or live P1–P3 integration.

## Structure

`src/main.tsx` mounts the app; `App.tsx` owns the monitor and section navigation. `Panels.tsx`, `Overview.tsx`, and `Assistant.tsx` render the modules. `session.ts` owns transport and simulation; `session-state.ts` owns buffer updates. `types.ts` describes optional consumer fields without changing the shared backend contract. `design.css` is the active stylesheet; `monitor.css` retains the earlier design.

The official Motion skill is stored in `.agent-skills/motion/`. Official GSAP core, React, timeline, and performance skills are also stored in `.agent-skills/`. They were loaded explicitly for this implementation.

The current theme combines Midnight Steel, Deep Horizon, and American Denim Fade gradients. Navigation is integrated into the transparent top header. Cards use tinted translucent surfaces; the camera, charts, and indicators follow the same palette. Alarm and waiting states keep their distinct warning colors.

GSAP handles a short entrance sequence through `useDashboardEntrance.ts`, scoped and cleaned up with `useGSAP` and `gsap.matchMedia`. Motion handles section transitions, the shared selection indicator, disclosures, and reaction markers. The libraries target separate elements. Score history and alerts update directly. Both animation paths respect reduced motion.
