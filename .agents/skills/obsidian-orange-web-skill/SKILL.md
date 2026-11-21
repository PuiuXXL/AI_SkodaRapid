---
name: obsidian-orange-adaptive-web
version: 2.0.0
description: >-
  Transform the visual design of an existing web application, admin console,
  dashboard, analytics platform, SaaS interface, or marketing site into a
  premium, dark charcoal-and-orange design inspired by the CY·FOCUS references.
  Uses a floating translucent vertical side menu with TWO user-controlled modes
  (Collapsed icon-only and Expanded icon-and-label), glass cards, strong data
  hierarchy, contextual visualization patterns, responsive layouts, and
  functional preservation, Anthropic-inspired design critique, and purposeful animation recommendations sourced from Motion and GSAP official docs. Apply when asked to redesign, restyle, improve,
  modernize, or visually align an existing web UI without changing its purpose.
metadata:
  short-description: Context-aware dark-orange glassmorphic web design system
---

# Obsidian Orange — Anthropic Fusion + Motion/GSAP (v2.0)

## Mission

Create a **cohesive visual redesign of the user's actual web product**, not a generic screenshot clone. The dominant aesthetic is defined by the **first uploaded CY·FOCUS image**, reinforced by the **eighth CY·FOCUS dashboard image**: near-black / graphite surfaces, charcoal depth, ember-orange emphasis, fine typography, crisp dense information, soft reflections, and a glass-like floating side menu and overlays.

Treat the remaining images as **context-sensitive design references**, not independent themes. Borrow appropriate interaction patterns, chart grammar, composition, depth, specialized widgets, and content treatments without replacing the core charcoal/orange identity.

**Outcome:** a production-feasible, responsive, accessible interface that looks intentionally designed for its domain, preserves the site's routes and business functionality, and never sacrifices clarity to decoration.

## Activate this skill when

- The user asks to redesign an existing web app, SaaS interface, dashboard, admin panel, analytics product, portal, or landing page.
- The user wants the dark CY·FOCUS aesthetic, translucent cards, subtle orange accent, and a dynamic, floating translucent side menu (not a top navbar).
- The app needs to inherit a common visual language while adapting to its real content, industry, audience, and information density.
- The current design has inconsistent styles, basic cards, weak hierarchy, or poor navigation.

**Do not** rewrite business logic, remove required fields, invent product claims, discard information, change data contracts, or overuse decorative effects. Do not choose chart types before understanding the data.

## Reference order and routing

1. **PRIMARY / mandatory:** `references/images/01-cyfocus-primary.png` — image 1; dark graphite, orange highlights, product atmosphere and hierarchy.
2. **PRIMARY / mandatory:** `references/images/08-cyfocus-dashboard.png` — image 8; operational sidebar, activity panels, dense data UI, restrained orange signals.
3. **SECONDARY / conditional:** references 02–07 and 09–12 — consult `references/context-playbook.md` for choosing patterns by app type.
4. Follow existing product-specific constraints (semantics, accessibility, company identity, real data, framework) over purely stylistic resemblance.

**Style inheritance rule:** Always inherit the **palette, materials, typographic restraint, spacing rhythm, and navigation behavior** from the primary references. Inherit **layout patterns, visualizations, micro-interactions, and widget types** from secondary references only when relevant.

If image files are absent because only this `SKILL.md` was copied, follow the written specifications; do not assume access to uploads or use fabricated file paths.

## Core visual DNA — non-negotiable

- **Palette:** background #090A0C or #0D0F12; dark charcoal panels; warm gray text; warm amber / burnt orange (#FF6B3D family) for focus, alerts, selected states, key metrics, primary CTAs. White space is replaced by meaningful dark negative space.
- **Materials:** subtle translucent cards over tonal gradients and blurred atmospheric glows. Use true glass only when there is something behind it and the contrast remains readable. Solid dark panels are preferred for dense tables and body copy.
- **Depth:** restrained multi-layer surfaces, delicate 1px borders, soft directional highlights, warm orange bloom used locally (never a large generic neon glow on everything).
- **Typography:** modern, readable sans serif (Geist, Inter, or the project's existing equivalent); compact labels, quiet metadata, confident page headings, prominent numbers with tabular figures.
- **Geometry:** 12–20px cards, 16–24px larger containers; pill-like controls; modest curvature, not inflated toy-like cards. Maintain consistent grid and rhythm.
- **Navigation:** a **vertical floating, glassmorphic side menu is mandatory**, resembling a distinct translucent card. Place it at the left by default, keep current-route highlighting dynamic, support expanded/icon-only collapsed modes, and use an accessible slide-over drawer on mobile. **Do not substitute a horizontal navbar or top navigation for the primary navigation.** A compact utility-only header may be added to the content area when genuinely needed.
- **Data visualization:** fine lines, calibrated orange emphasis, readable axes, appropriate color distinctions, faithful values, and efficient layouts.
- **Interaction:** 120–240ms motion, subtle easing and hover elevation, informative state transitions, reduced-motion support. Never animate for its own sake.
- **Voice:** product-specific, concise, precise. Do not blindly rename business features after the cyber dashboard.

## Anthropic frontend-design principles — adapted, not copied

This skill draws on the official [Anthropic frontend-design skill](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md): make deliberate decisions based on the actual product, avoid interchangeable AI-generated templates, treat typography/content as part of design, use structure to carry meaning, and critique rendered results. This is an independent, user-specific synthesis; do not present it as an official Anthropic artifact. Read `references/design-critique.md` for the detailed two-pass design review. **The user's CY·FOCUS brief overrides generic aesthetic heuristics**, so dark charcoal/orange is an intentional requirement rather than a generic default.

**Two-pass gate before code:**
1. Establish a short visual charter: five or six tokens, typography roles, signature layout, component density, reference rationale, animation budget, responsive constraints. Write a small annotated wireframe.
2. Check each decision against the real user's product and both CY·FOCUS images. Remove fake dashboards, decorative chips, unnecessary labels, attention-stealing animations or repetitive cards. Only then implement.

**Visual fidelity priority when adapting an existing page:** `01` atmosphere / palette / material → `08` dashboard anatomy → mandatory floating glass collapsible sidebar → correct product semantics → optional secondary reference patterns → motion. A striking animation never compensates for a wrong layout, unreadable information, or broken actions.

## Motion and GSAP integration — optional libraries, mandatory contextual guidance

Read `references/motion-gsap-playbook.md` *before* adding animation code. The agent MUST analyze context, then propose a small explicit motion plan before implementation: **trigger → purpose → affected component → library or CSS → duration/easing → reduced-motion fallback → link to official documentation or example**. If no animation adds understanding, choose no animation.

- **Motion** ([motion.dev/docs](https://motion.dev/docs), [official examples](https://motion.dev/examples)): use for React/Vue interactions, layout changes, active tab/route indicators, sidebar Expanded ⇄ Collapsed transitions, accordions, conditional mounts, popovers and small shared-element transitions. Primary React APIs: `motion` from `motion/react`, `layout`/`layoutId`, `AnimatePresence`, `whileHover`, `whileTap`, `useReducedMotion`. For vanilla JavaScript consult the platform-specific Motion API; do not import React-only hooks in non-React apps.
- **GSAP** ([gsap.com/docs/v3](https://gsap.com/docs/v3/), [ScrollTrigger](https://gsap.com/docs/v3/Plugins/ScrollTrigger/), [React guide](https://gsap.com/resources/React/)): use for coordinated hero timelines, product presentations, scroll chapters, maps/diagrams with deliberate staged sequencing, and advanced FLIP/reparent transitions. Prefer scoped `gsap.context()`/`useGSAP()` and clean up animations on unmount/route change; responsive `gsap.matchMedia()` and reduced-motion checks are mandatory for nonessential movement.
- **CSS**: preferred for simple hover color, focus, button press, 1–2-property opacity and border transitions. You do not need either library merely to achieve a premium look.
- **Do not bundle both by default.** Keep CSS only when it suffices, use Motion when React UI state drives animation, add GSAP only when a genuinely distinct timeline/scroll use case warrants the bundle. Do not let two engines animate the same DOM property on the same element.
- **Performance budget:** prioritize opacity/transform, minimize paint-heavy box-shadow/backdrop-filter animation, avoid animating chart scales in a way that misrepresents numerical data. Restrict gratuitous entrance animations (at most one intentional entry orchestration per view). Honor `prefers-reduced-motion: reduce` and give an immediate accessible fallback.
- **Demo implementations:** `examples/react/GlassSidebarMotion.tsx` and `examples/react/ProductHeroGSAP.tsx` are recipes to adapt to the real router. No fake interactions, never replace actual data. Source links remain attached as URLs, not copied examples from vendor sites.

## Complete component coverage

See `references/component-inventory.md` for an exhaustive inventory of the visual and behavioral parts visible in references `01` and `08`, plus context-specific components extracted from reference images `02–12`. Each component has anatomy, state model, visual rules and an appropriate motion choice. **Audit every component present in the real platform**, even if absent in the pictures (forms, authentication, uploads, pagination, errors, accessibility). Do not remove unsupported-by-reference functionality.

## Pixel-level fidelity and critique gate

Read `references/reference-forensics.md`. Do not reproduce the marketing/gallery frame or tablet chrome around the UI; reproduce **the interface inside** it. The original screenshot has a built-in dark navigation left rail; user modification takes precedence: use the same CY·FOCUS palette and visual hierarchy but elevate the rail to a floating translucent card with mandatory Expanded and Collapsed modes.

When browser screenshots are available, compare the rendered result at desktop and mobile against the two primary references: background temperature, orange concentration, information density, surface sizes, sidebar weight, panel borders, spacing, typography and focal region. Review after one full initial layout pass, then refine mismatches. If you cannot render, say so; do not invent a visual QA result.

## Mandatory implementation workflow

### 1. Audit before touching code

Inspect the repository, component architecture, design tokens, routing, and current screens. Identify framework and styling approach (React, Next, Vue, Angular, Svelte, plain HTML/CSS, Tailwind, CSS modules, etc.). Inventory every screen, form, table, chart, modal, feedback state, keyboard interaction, and mobile variant.

Write a short internal transformation map for each page: **user goal -> critical content -> interaction -> suitable layout -> relevant reference -> implementation risk**. Capture existing logos, accessibility constraints, assets, breakpoints, and component libraries. Preserve existing conventions where practical.

If the environment does not grant access to the codebase, produce a design-system and screen-specific implementation plan; do **not** pretend the site has been changed.

### 2. Choose the right content archetype

Apply one or more of these archetypes from `references/context-playbook.md`:

- **Operations / security / admin:** dense dashboard, sidebar, incidents, activity stream, states, logs (references 01 + 08, optionally 10).
- **Metrics / analytics:** KPI strips, trend charts, filters, comparison, drill-down (01 + 08 + 04 + 03).
- **Trading / finance:** dense but organized market panels, heatmap, order controls, numerical precision (01 + 08 + 05).
- **Industrial / IoT / energy:** monitoring tiles, device diagrams, logs, throughput and health indicators (01 + 08 + 03 + 10).
- **Automotive / product explorer:** large central product visualization and surrounding contextual controls (01 + 02 + 11).
- **Mobility / geospatial:** map-first layouts and location panels where location is fundamental (01 + 09).
- **Personal / professional profile:** focused identity pane, clear metrics, lightweight glass materials (01 + 07).
- **Wellness / personal insights:** calm reading rhythm, ring/progress widgets, empathetic copy (01 + 12 + 06).
- **Marketing / showcase:** cinematic single focal object, controlled overlays, strategic typography and CTAs (01 + 11).

For mixed applications, define one primary page archetype and borrow only adjacent patterns. Do not impose dashboard widgets on a checkout or registration form.

### 3. Build tokens first

Read `references/design-tokens.md` and start from `examples/theme.css`. Centralize colors, surfaces, radius, spacing, typography, shadows, glows, motion, and chart palette. **Do not hardcode one-off colors throughout components.** Honor or extend the existing theme engine. Implement color tokens with meaningful names (`--color-accent`, `--surface-glass`, `--border-subtle`) rather than raw `orange-500` assumptions.

Use an 8px spacing rhythm with 4px micro adjustments. Aim for clear contrast and content density tuned per application rather than fixed card heights.

### 4. Construct the signature floating side menu (mandatory)

The primary navigation is **always a vertical side menu**, never a top navbar. It should look like a **separate rounded translucent glass card**, floating above the almost-black canvas with generous margins, thin bright edge, 16–24px blur, subtle reflected highlight, and localized orange active accents.

- **Desktop layout:** position at the left, inset 16–24px from the page edges, with approximate **256–284px expanded width** and **72–84px collapsed width**. Prefer `position: sticky; top: 16px; height: calc(100dvh - 32px)` within a two-column layout; fixed positioning is acceptable if content offset is handled correctly. Keep the side menu independently scrollable if its links exceed its available height.
- **Anatomy, top → bottom:** logo + brand (with collapse button), optional workspace/project switcher, optional search/command action, vertically stacked primary destinations grouped by relevant category, contextual sub-navigation when necessary, flexible spacer, and bottom-anchored settings/help/profile/account section. Keep profile and required actions accessible when collapsed.
- **Selection:** use the application's actual routing state and RBAC/permission model. The current destination has an understated orange pill/edge accent and correct `aria-current="page"`; nested routes expand/highlight their real parent section. Do not invent destinations or hardcode a permanent selected tab.
- **TWO REQUIRED DESKTOP MODES — never optional:**
  - **EXPANDED** (`is-collapsed = false`): 256–284px wide (268px default), each item displays a 20–24px icon **and a readable text label**; show brand name, group headings, and relevant context. Full navigation remains usable.
  - **COLLAPSED** (`is-collapsed = true`): 72–84px wide (80px default), show **icons only**, plus brand mark, visible active-state indicator, profile/settings icons, and one permanent expand control. Hide labels visually but retain accessible names via `aria-label` or equivalent; show tooltip on hover AND keyboard focus. Maintain 44px targets.
- **User-controlled toggle is required:** put a real button in the side-menu header in both modes (e.g. `PanelLeftClose` when expanded / `PanelLeftOpen` when collapsed); click, Enter and Space toggle immediately without navigation or a page reload. Update its label (`Collapse sidebar` ↔ `Expand sidebar`), `aria-expanded`, and visual icon. The toggle must stay visible, reachable and operable in BOTH states. Don't make collapse depend solely on hover, screen width, or a hidden control.
- **State and layout:** store a boolean in the app shell (`isCollapsed`); derive menu width, displayed labels and main-content width from the SAME state. Preserve the preference between route changes and, when safe in the current framework, across reloads using localStorage or existing settings (guard SSR/hydration and storage failures). On smaller desktop/tablet widths the *initial default* may be collapsed; never disable manual expansion.
- **Transition:** animate the sidebar/main-content width and subtle icon-label fade at 180–240ms. Avoid overlap, clipping, lost focus, pointer traps or horizontal scrolling during a transition. Honor reduced-motion settings.
- **Mobile (<768px):** collapse/expanded desktop choice is independent from mobile visibility: the menu becomes an off-canvas **expanded drawer** with readable labels, never a 80px collapsed rail on mobile. It opens from the utility-header menu button; closes via Escape, backdrop, close button or appropriate navigation. Close with focus restoration and scroll lock.
- **Content placement:** dashboard/content occupies the remaining width. Keep a deliberate 16–24px gap and responsive gutters; no content may sit underneath the side menu or be clipped on narrow screens. Optional breadcrumb/actions strip belongs **inside main content** and is not a horizontal nav replacement.
- **Interaction:** clear hover/focus/pressed states; keyboard Tab through links; semantic `<nav aria-label="Primary">`; 44px preferred targets; route-driven active indicator; support reduced motion and readable solid-color fallback if backdrop blur is unavailable.
- **Avoid:** top-floating navbar as primary navigation, two competing primary menus, giant full-height solid sidebars without the glass-card floating treatment, unreadable transparency, icon-only mystery navigation, dead destinations, and sidebar width transitions that cause content jumps or horizontal overflow.

See `references/component-patterns.md`, `examples/theme.css`, and **`examples/sidebar-demo.html` (working two-mode interactive reference)**. Implement both modes and the toggle — documenting them alone is insufficient.

### 5. Transform layout and content

Rebuild each screen around its **real content**. Establish a page header, content hierarchy, 12-column or CSS grid composition, and modular panels. Mix large anchor panels with compact supporting panels; avoid equal-size-card monotony.

Use **glass cards selectively**:

- Good: floating side menu, summaries, contextual popovers, product controls, hero overlays, profile stats, light filter bars.
- Less suitable: text-heavy documents, large tables, audit logs, long forms, and complex data-heavy panels; prefer opaque charcoals here.
- Use one dominant glass material and 1–2 surface variants. Transparent does not mean invisible.

Content remains primary. No fake KPIs, dummy charts, arbitrary icons, stock dashboard noise, decorative text, or invented metrics. Existing copy and localized strings should remain intact unless the user requested content edits.

### 6. Apply contextual visualizations

Choose visual form to fit meaning:

- Time series -> line/area chart with thin gridlines; orange for selected/main series; secondary neutral lines.
- Comparative categories -> bars with understated gray baselines and warm highlight.
- Risk or status -> color plus explicit label/icon; accessible legend; severity colors may depart from orange semantically.
- System topology / maps -> only if the product actually has geographic or graph data.
- Device/vehicle -> polished hero visual only if an asset exists; don't fabricate 3D capabilities.
- Circular progress / emotional radial -> only for meaningful proportion or well-defined category states.
- Finance -> preserve bid/ask conventions, numeric precision, and differences between gain and loss.

Display axes, units, tooltips and empty/loading/error states. Ensure chart colors are distinguishable without relying solely on hue.

### 7. State design, behavior, and motion selection

For **every** interactive component, account for default, hover, focus-visible, active/selected, disabled, loading, empty, warning, error, and success states as relevant. Preserve validation, server error handling, routes, data fetching, authentication, permissions, and user intent.

Avoid gratuitous UI libraries. Reuse the project's existing primitives when feasible. Add dependencies only when they materially improve implementation. For each changing state choose CSS, Motion or GSAP using `references/motion-gsap-playbook.md`; document reduced-motion behavior and official inspiration links. Do not animate live values, hover and every card by default.

### 8. Responsive and accessibility pass

Target 320px, 375px, 768px, 1024px, 1440px, and wide desktops. Arrange larger dashboards into nested grids rather than shrinking all cards. Financial data and tables may scroll locally with clear affordances; the whole page should not overflow horizontally.

Ensure WCAG 2.2 AA where applicable: meaningful contrast, 44px preferred touch targets, keyboard operation, logical heading order, live updates announced appropriately, readable chart alternatives, visible focus, and `prefers-reduced-motion`. Don't use transparent text as a style effect. Blur/frosting is optional under unsupported or performance-constrained environments.

### 9. Verify in the actual application

Use `references/qa-checklist.md`. Compare against both primary references and audit page-by-page. Check real data, keyboard, mobile, loading states, high-density views, and error cases. Fix regressions instead of papering over them.

**Definition of done:** dominant dark graphite + orange identity; dynamic floating translucent **side menu with working Expanded ⇄ Collapsed toggle**; contextual information architecture; consistent responsive components; readable visualizations; preserved product workflows; no broken routes or actions.

## Visual quality anti-patterns

- ❌ Generic purple/blue SaaS gradient replacing the charcoal/orange identity.
- ❌ Every surface blurred or transparent, making dense data unreadable.
- ❌ Oversized dashboard heading, endless empty space, huge radii on every card.
- ❌ Neon orange everywhere, constant pulse animations, gratuitous glow, full-screen glass.
- ❌ A pasted screenshot behind the UI, or a laptop mockup used as an application interface.
- ❌ Static side-menu labels with a fake active state; inert buttons and tabs.
- ❌ Replacing true data with invented numbers, fake alerts or lorem ipsum.
- ❌ Hiding existing tools, settings, tables, mobile navigation or accessibility features to match a reference.
- ❌ Copying domain-specific colors or visual patterns from an unrelated secondary reference.
- ❌ Introducing 3D/radial visualizations just because a secondary image shows them.

## Deliverables / answer requirements

When editing a repository, deliver:

1. A concise summary of **screens/components actually changed**.
2. A summary of the shared theme, floating side menu, and any conditional references adopted.
3. What was validated (build/tests and visual/responsive checks), plus any checks not run.
4. Any deliberate exceptions needed for data, accessibility, performance, or user requirements.

If asked only for a concept, give a concrete design direction with tokens and component choices, without claiming to have implemented it.

## Reference documents

- `references/design-tokens.md` — complete visual system and accessibility constraints.
- `references/component-patterns.md` — navigation, surfaces, data widgets and adaptive components.
- `references/context-playbook.md` — role of each uploaded image and archetype selection.
- `references/qa-checklist.md` — visual/behavioral acceptance criteria.
- `references/reference-forensics.md` — annotated visual decomposition of all supplied screenshot references.
- `references/component-inventory.md` — exhaustive component contracts and states.
- `references/design-critique.md` — original adaptation of Anthropic frontend-design principles.
- `references/motion-gsap-playbook.md` — context-driven animation decision engine, precise links to Motion/GSAP official examples.
- `examples/react/GlassSidebarMotion.tsx` — React + Motion reference for two-mode sidebar and mobile drawer.
- `examples/react/ProductHeroGSAP.tsx` — GSAP, scoped timeline and conditional ScrollTrigger recipe.
- `examples/theme.css` — portable CSS token + component starter (adapt it, don't force it wholesale).
- `examples/sidebar-demo.html` — dependency-free executable two-state sidebar demo (desktop toggle + mobile drawer).
