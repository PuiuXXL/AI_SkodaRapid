# Component patterns

## 1. Signature floating glass side menu (most important component)

**Non-negotiable:** primary navigation is a **vertical left-side menu** in its own floating, translucent rounded card. The layout must not silently revert to a horizontal navbar on desktop or mobile.

**Appearance:** smoked charcoal glass (`rgba(30,31,34,.68)` with fallback), 18–24px corner radius, 1px understated border, top-edge reflection, soft shadow, backdrop blur. The menu floats 16–24px away from the top/left/bottom screen boundaries instead of touching the viewport edge. Orange is a precise selection/highlight signal, not a fill color for the whole sidebar.

**Anatomy (vertical):**

1. Header: product mark and short brand name, with an explicit collapse/expand button.
2. Optional context: workspace/project switcher or quick search if present in the product.
3. Primary nav: grouped list of icon + label rows, with visual category dividers only when useful; optional nested child links open contextually.
4. A flexible spacer that keeps secondary actions at the bottom on tall screens.
5. Footer: help/settings and a compact account/profile affordance, always accessible.

**Mandatory interactive states (both must be implemented, not merely drawn):**

| State | Width | Content | Toggle |
|---|---:|---|---|
| `expanded` | ~268px | icon + text label, product name, group headings | always-visible Collapse sidebar button |
| `collapsed` | ~80px | icon-only rows, logo mark, active state, concise tooltips on hover/focus | always-visible Expand sidebar button |

The toggle changes state on click/Enter/Space, updates `aria-label` and `aria-expanded`, and resizes the content area in sync. Preserve the manual choice when navigating; persistence across reloads is recommended when appropriate and safe for SSR. Never auto-expand solely on pointer hover. On mobile, always use a full-label drawer independent of the desktop collapsed preference.

**Behavior:**

- Expanded: ~268px width. Collapsed: ~80px wide (icons only), and keep `aria-label` / screen-reader name on every icon link, tooltip on hover/focus as useful.
- Drive selected state from actual router state; use `aria-current="page"` for the active link, highlight true parent on nested routes, show icons and descriptive text, and obey route permissions.
- Active item: orange left bar or subtle orange-tinted pill, restrained animation, readable foreground. Hover: delicate charcoal lift. Keyboard focus: high-contrast outline. Keep 44px-ish row targets.
- Use app-shell CSS Grid or equivalent to reserve menu width plus 16–24px gap for content. Fixed menus require accurate main-content compensation. Avoid covering scrolling body content.
- Sidebar can scroll internally when necessary; sticky positioning avoids overscrolling the page. Prevent app-level horizontal overflow.
- Only the collapsed vs expanded state changes on desktop. On mobile (<768px), use a true modal drawer with backdrop, trigger in a small utility header, Escape/backdrop/close support, focus trap while open, return focus on close, and prevent background scroll.
- The utility header can show breadcrumb/page title, search and notifications, but **must not contain a competing horizontal list of primary destinations**.
- When animated, prefer 180–240ms, preserve reduced-motion preference, and avoid content reflow surprises. Respect safe areas on mobile. Choose CSS or Motion deliberately, following `motion-gsap-playbook.md`; use Motion `layoutId` for the active-pill transition where relevant. Do not add GSAP for sidebar state transitions.

**Layout geometry:** 16–24px page inset, 16–24px content gap, 18–24px shell radius, 256–284px expanded, 72–84px collapsed, sticky `top:16px`, `height:calc(100dvh - 32px)` (adapt to actual safe areas and viewport behavior).

**Failure modes:** nonfunctional or missing collapse toggle; only one state implemented; auto-hover-only expand; inaccessible expand control; top navbar replacing sidebar; sidebar flush to the edge; content underneath the menu; icon-only links without names; static active marker; over-transparent text; footer links unreachable; mobile drawer inaccessible; duplicated primary navigation.

## 2. Glass card system

Create just three variants:

- `glass-nav`: floaty, translucent, blurred, higher elevation.
- `glass-overview`: translucent chart summary/profile card, modest blur, readable content.
- `solid-workspace`: opaque for tables, logs, complex graphs, forms, content editing.

All three share consistent radius, border language and typography. Cards should not all have glowing orange outlines; selected/important cards may have one.

Card anatomy: optional eyebrow -> title + actions -> important data/visual -> concise contextual footer. If a card is clickable, make the entire card or an obvious button accessible; do not create conflicting nested clicks.

## 3. Dashboard framing

- Page title + concise subtitle + primary contextual action.
- Optional command/filter strip using compact glass pills.
- KPI row (only genuine metrics). Avoid uniformly large metrics when data is secondary.
- Primary anchor panel spanning 6–9 grid columns and stacked companion panels.
- Lower row with tables, activity, detail, analysis or workflow controls.
- The signature side menu contains the product sections and collapses sensibly; do not duplicate them in a top navbar.

**Layout recipe:** `grid-template-columns: repeat(12,minmax(0,1fr)); gap:16px;` with area spans selected by content, not rigid templates. On tablets collapse to 6-column equivalent, and on phones single-column ordering by importance.

## 4. Tables and data grids

Opaque or heavy-glass card. Sticky header where meaningful, row hover, clear selection, inline filter/search, visible sorting, sensible truncation, units, readable numeric alignment, status labels with text. Avoid horizontal page overflow; permit table-local scroll where necessary. Keep actual pagination/selection/export functionality.

## 5. Data cards and KPIs

Use a hierarchy: muted label, large number, unit, comparison, tiny relevant sparkline if supported, timeframe. Avoid oversized fake percentages. Numeric metrics use tabular figures. Change badges use arrows/text, not solely red/green. Mini-chart fills can use a delicate orange gradient with 5–12% opacity.

## 6. Charts

Charts should be content-first. Use reference 04 for elegant time trends; 03/10 for bars and monitoring; 05 for multiple financial chart types. Tooltip has concise label/date and values; selected point may be orange. Favor thin grid lines and accessible series labels. Provide data table alternative for complex charts where appropriate.

Do not recreate an exact trend line from a reference if real data differs.

## 7. Buttons, filters, inputs

- Primary: warm orange fill, dark readable text; use intentionally for main actions.
- Secondary: translucent/charcoal with subtle stroke, bright text.
- Tertiary/ghost: text + gentle hover backdrop.
- Destructive: semantic red, not orange.
- Filter chips: rounded, active with warm border/fill, possible count; preserve state/URL if the product relies on it.
- Input: graphite inset, 1px border, proper focus ring, visible label, error text and validation.

## 8. Modals, drawers, popovers

Floating translucent header/backplate but dense body may use opaque dark surface. Drawers have clear close mechanism, overlay and keyboard/focus management. Menus should use portal/layer strategy as appropriate to avoid card clipping.

## 9. Hero / showcase / product canvas

Take composition from references 02 and 11: one dominant supplied image/interactive model, restrained feature callouts, spatial layering, one clear CTA. Use charcoal gradient scrims so content remains legible. Do not ship a fake configurator or 360 button without supported functionality.

## 10. Empty, loading and error states

Empty: explain why the view has no data, suggest a real next action. Loading: skeletons that match true component shape; avoid glowing long animations. Error: readable message, contextual retry. Success: confirmation tied to actual action. Preserve contextual information instead of a generic toast for every outcome.

## 11. Responsive behavior

**>= 1280px:** floating glass left side menu (expanded or collapsed) + measured main-content width + 12-col content grid.

**768–1279px:** side menu may default to compact icon-only mode; moderate gutters; collapse complex companion panes; prefer 2-column panels.

**< 768px:** side menu becomes an accessible off-canvas drawer opened from a small utility-header menu trigger; major panels stack; dense charts stay useful with adaptive legends; tables scroll locally or use mobile cards if semantics allow.

**320–375px:** all controls remain tappable; no clipped menus or unscrollable forms. Phone viewport is a functional use case, not a screenshot crop.

## 12. Performance and craft

Use CSS transforms/opacity for motion; avoid animating large blur radii, background filters, or layout-heavy properties. Prefer semantic HTML and reusable UI primitives. Defer expensive visualizations and use reduced visual effects under low performance constraints. Do not load remote fonts or third-party images without project permission.
