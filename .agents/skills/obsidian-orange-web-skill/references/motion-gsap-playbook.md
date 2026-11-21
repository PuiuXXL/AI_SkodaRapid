# Motion.dev + GSAP — contextual motion decision engine

Verified source categories: [Motion documentation](https://motion.dev/docs), [Motion example gallery](https://motion.dev/examples), [GSAP docs](https://gsap.com/docs/v3/), [GSAP React integration](https://gsap.com/resources/React/), [GSAP ScrollTrigger](https://gsap.com/docs/v3/Plugins/ScrollTrigger/). Source URLs below are **external references to study or adapt**, not bundled vendor source code; Motion+ examples may have separate access requirements.

## Decision procedure (MUST USE)

1. Determine context: operations/data-entry, data exploration, consumer marketplace, finance, industrial, geospatial, personal, product/marketing.
2. Identify the actual *state transition* or storytelling need: navigate, expand, reorder, filter, select, save, reveal, scroll, compare, annotate.
3. Rank purpose as `essential-feedback` / `helps-orientation` / `deliberate-brand-moment` / `decorative`. Skip `decorative` by default, especially in operational dashboards.
4. Choose cheapest compatible engine: `CSS` for simple effects, `Motion` for component state/layout in React/Vue, `GSAP` for curated multi-step timelines, complex scroll and controlled sequences. Vanilla Motion or GSAP may be used in non-React stacks; assess installed dependencies first.
5. State exact target, trigger, duration/ease, reduced-motion fallback, cleanup and URL. Avoid new dependency if negligible benefit.
6. Test at 60fps where possible, keyboard and touch behavior, route unmount, fast repeated toggles, small viewport, low-power/reduced-motion settings.

## Motion selection matrix

| Scenario / context | Target behavior | Preferred | Suggested duration / easing | Official reference |
|---|---|---|---|---|
| Sidebar Collapsed ↔ Expanded (all platforms) | Width/layout and label continuity, no content jump | Motion `layout` or synchronized CSS grid **not both for same property** | 200–240ms easing-out | https://motion.dev/docs/react-layout-animations |
| Moving active sidebar pill | Selected orange underlay moves to actual active route | Motion `layoutId` in `LayoutGroup` | 180–240ms spring, little/no bounce | https://motion.dev/examples/react-shared-layout-animation |
| Mobile drawer | Backdrop fade and panel slide, restore focus | Motion `AnimatePresence` + native/a11y dialog semantics | 180–240ms ease-out | https://motion.dev/docs/react-animate-presence |
| Tabs & filter segment | Underline/pill tracks selection, chart updates without warp | Motion `layoutId`; CSS if static | 160–220ms | https://motion.dev/examples/react-layout-animation |
| Accordion / details | Compact height + arrow change | Motion layout | 180–260ms | https://motion.dev/docs/react-layout-animations |
| Tooltip/popover | Trigger-linked opacity/short offset, no hover jitter | CSS or Motion | 120–160ms | https://motion.dev/docs/react-animation |
| Modal from context card | Shared element if continuity improves recognition | Motion `layoutId` + `AnimatePresence` | 220–320ms | https://motion.dev/examples/react-modal-shared-layout |
| Toast / save success | Single small appearance and dismissal | Motion `AnimatePresence` | 140–220ms | https://motion.dev/docs/react-animate-presence |
| Numeric KPI change | Change indicator and small opacity cue; values always truthful | CSS / Motion | 120–220ms | https://motion.dev/docs/react-animation |
| Time-series tooltip | Precise crosshair and data tooltip movement | chart tool + Motion tooltip | 100–180ms | https://motion.dev/docs/react-motion-component |
| New feed item | Newly inserted row gains subtle highlight and position | Motion `layout` | 180–240ms | https://motion.dev/docs/react-layout-animations |
| Collapsible filters | Filter panel reveals without scrolling content under controls | Motion `layout` | 180–260ms | https://motion.dev/docs/react-layout-animations |
| Industrial active device | A single port/module becomes visually selected on command | CSS / Motion | 150–240ms | https://motion.dev/docs/react-gestures |
| Scannable radial selection | Selected category moves into focus, legend updates | Motion layout/SVG attributes | 180–260ms | https://motion.dev/docs/react-animation |
| Drag to reorder (real feature only) | Item stays spatially attached to drag | Motion reorder or existing DnD stack | spring suited to actual drag | https://motion.dev/docs/react-layout-animations |
| Long, visual marketing section | One thoughtful in-view reveal where it makes narrative sense | Motion `whileInView` | 300–500ms | https://motion.dev/docs/react-scroll-animations |
| Light scroll progress UI | Progress of reading/section | Motion `useScroll` | scroll-linked only | https://motion.dev/docs/react-use-scroll |
| Large cinematic hero (product/vehicle) | Sequenced image, headline, callouts with emphasis | GSAP Timeline | ~0.7–1.4s entire sequence | https://gsap.com/docs/v3/GSAP/Timeline/ |
| Product story scroll chapters | Pin/unpin or scrub 3D/story narrative on user scroll | GSAP ScrollTrigger | scroll-linked and mobile-specific | https://gsap.com/docs/v3/Plugins/ScrollTrigger/ |
| Brand object feature hotspots | Stagger once for 2–4 honest feature annotations | GSAP timeline | 90–130ms between elements | https://gsap.com/docs/v3/GSAP/Timeline/ |
| Advanced reparenting gallery | Seamless actual element relocation | GSAP Flip | 250–450ms | https://gsap.com/docs/v3/Plugins/Flip/ |
| Responsive motion scenes | Disable/mute motion and pinning on mobile/reduced-motion | GSAP `matchMedia()` | condition-driven | https://gsap.com/docs/v3/GSAP/gsap.matchMedia%28%29/ |
| Scroll storytelling outside React | Section enters trigger and reveals guided sequence | GSAP ScrollTrigger | scroll-linked | https://gsap.com/docs/v3/Plugins/ScrollTrigger/ |

## Context-aware recommendations (what to SUGGEST, not force)

**Operations/cyber/admin (images 01/08):** sidebar width/pill shift, modal/dialog state, filter/tabs, local alert/new activity highlighting. Avoid parallax, perpetual threat-dot breathing, spinning statistics or animated backgrounds.

**General dashboards & CRM:** collapsed/expanded nav, chart selection tooltip, table filter reveal, task completed toast. Avoid scroll-jacking and splash intros.

**Finance/trading (05):** precisely timed order success/errors, temporary quote-change highlight, accordion order details. Do not tween financial positions/quotes through intermediate misleading values; respect real-time update performance.

**Industrial/IoT/energy (03/10):** signal active module on direct selection; status transition once; discreet diagnostic overlay. Do not animate alarm states in seizure-provoking loops.

**Automotive/product explorer (02/11):** optional guided rotation or hero entrance with GSAP if *actual* imagery/3D exists; Motion tab/carousel transitions. No fake 360 controls.

**Mobility/maps (09):** overlays for route selection/destination details; map motion should be controlled by map SDK. No fake geographic motion.

**Wellness/personal (06/07/12):** calm soft progress/ring transitions, profile card expansion, reduced-motion static ring; do not animate a health score to imply improvement.

**Marketing/storytelling (11):** one selective GSAP hero entrance or ScrollTrigger story, mobile static alternative; don't install GSAP for a simple CTA hover.

## Rules for implementation

- **Motion React:** `npm install motion`; import from `motion/react` according to current docs. In React, use state-driven variants, `layout`/`layoutId`, and `useReducedMotion` or `MotionConfig` for reduced-motion. Full docs: https://motion.dev/docs/react , https://motion.dev/docs/react-use-reduced-motion . For Vue consult https://motion.dev/docs/vue ; for vanilla https://motion.dev/docs .
- **GSAP:** `npm install gsap`; add `@gsap/react` in React when appropriate, see https://gsap.com/resources/React/ . Scope selectors, clean up timelines/ScrollTriggers. Use GSAP only if the existing project justifies it; no duplicate animations between GSAP and Motion on one element. Use `gsap.matchMedia()` for responsive and reduced-motion alternatives.
- **Animations on real user actions:** do not delay input handling or server mutations for visual flair. A busy state should appear immediately; success state should reflect completed server work.
- **Motion sensitivity:** reduce spatial shifts/parallax/pinning under `prefers-reduced-motion`; retain opacity/instant state where useful. Keep UI accessible without JS animation.
- **CPU/GPU:** prefer transforms/opacity. Do not continuously animate blur radius, width of huge chart canvases, hundreds of objects, or many expensive backdrop-filter surfaces.
- **Safety:** no rapid flashing, unexpected autoplay, heavy camera movement, looping backgrounds or transitions that change perceived risk/data meaning.

## Proposal template for a coding agent

```
Screen/context: <real route + actual user job>
Animation: <component and state change>
Why: <orientation/feedback/narrative>
Engine: <CSS | Motion | GSAP> and why not the others
Trigger: <click/data update/route change/scroll>
Duration/easing: <precise values>
Reduced-motion fallback: <instant/opacity-only/disabled>
Official reference: <specific motion.dev or gsap.com URL>
Verification: <keyboard/mobile/cleanup/performance>
```

Suggest at most 3 high-value motions per screen on normal SaaS pages. On a critical high-density operations screen, prefer 0–2 active effects. Only a marketing/product narrative may justify a multi-step cinematic sequence.
