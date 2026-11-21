# Context playbook: choose references based on product meaning

The screenshots are **visual references**, not templates to recreate wholesale. Always retain the primary identity from `01-cyfocus-primary.png` + `08-cyfocus-dashboard.png`. Secondary references may contribute only the appropriate patterns.

| Reference | Original visual character | Pattern to borrow | Use when | Do not borrow blindly |
|---|---|---|---|---|
| 01 — CY·FOCUS primary | Charcoal-black / copper-orange cyber product, sophisticated screen depth | **Core palette, warm glow, serious tone, layered depth** | **Always** | Device mockup as the application shell |
| 02 — CarWhisperer | Vehicle centerpiece with structured floating tools | Product-first stage, 360 controls, modules surrounding hero | Vehicle products, product explorers, 3D configurators | Blue automotive palette; fake 3D interactions |
| 03 — Industrial overview | Modular monitoring tiles, physical device, bar chart, logs | Asymmetric monitoring grid, main telemetry + supporting tiles | IoT, manufacturing, laboratory, observability | Light gray main theme; invented physical render |
| 04 — Sales trend | Minimal time-series chart and filter pills | Small, precise trend chart; hover tooltip; filter ribbon | Analytics, sales, growth, admin dashboards | Pastel background and original purple palette |
| 05 — Finance dashboard | Dense dark trading interface, multi-panel financial charts | High-information layout, precise figures, distinct chart types | Finance, capital markets, real-time operations | Unrelated chart types or decorative glowing ROI shapes |
| 06 — Segmented radial | Circular multi-segment categorical / emotional widget | Radial categorical grouping when encoding is defensible | Mood, assessment, gamified progress | Radial chart for arbitrary metrics |
| 07 — Glass profile | Light translucent personal identity pane | Biography hierarchy, badges, concise profile metrics, frosted floating sheet | Portfolio, account, creator marketplace | Pale cyan/pink color as global identity |
| 08 — CY·FOCUS dashboard | Full dark-orange operational product with sidebar, cards, activity and map | **Core dashboard structure, information density, orange hierarchy, real navigation** | **Always consult, especially software platforms** | Cybersecurity-specific feature naming on unrelated products |
| 09 — Electra mobility | Geospatial/vehicle UI with immersive purple gradients | Route/map as an anchored feature and side context | Mobility, delivery, logistics | Purple accent or map when no geo data exists |
| 10 — Energy monitoring | Compact low-light operational analytics | Status summary, consumption panels, recommendations, diagnostics | Utilities, device analytics, infrastructure | Dense microtext where audience requires simpler UI |
| 11 — TechCool | Cinematic product pages, central hero object | Hero composition, contextual detail callouts, high-quality material | Product launches, marketing, ecommerce | Generic tech product copy or unrelated imagery |
| 12 — Wellness dashboard | Calming data, charts, circular health metaphor | Gentle cadence, progress rings, supportive insights | Wellness, lifestyle insights, self-tracking | Light lavender as the site's primary color |

## Decision algorithm

1. Determine the **core user task**: monitor, compare, decide, configure, discover, purchase, edit, or manage.
2. Determine **information density**: sparse (marketing/profile), medium (product/SaaS), dense (ops/finance).
3. Determine **key content media**: form, chart, table, map, 3D, editorial, user identity.
4. Select the single most relevant secondary reference, optionally one more for a minor element.
5. Recolor and rematerialize every borrowed pattern into the dark charcoal/orange base.
6. Remove elements that do not carry real content or support actual actions.

### Archetype application sketches

**Cyber / security / operations:** Floating glass side menu for primary destinations and nested workflows, main summary metrics, threat/activity area, quick-action controls. Anchor panels are dark/opaque, with orange severity/selective activity markers. Don't equate every warning with orange.

**General SaaS / CRM / ERP:** Floating glass side menu for all main destinations, large page title and filtering controls, 2–4 genuine KPIs, core table/workflow panel. Avoid styling everything as security instrumentation.

**Finance / trading:** Compact glass side menu, clearly separated markets/portfolio/orders, high-density numeric panels, meaningful red/green signals, precision-first. Extra-neon charts are optional and must not harm interpretability.

**Analytics / sales:** Focus on one primary time series, narrow filter rail, small supporting metrics, details table. Anchor attention with orange selected series, not many competing accent colors.

**IoT / energy / manufacturing:** Device/plant panel (when real imagery exists), monitoring telemetry, measurements and unit labels, alerts, diagnostic log, system status. Favor scannable panels over visual noise.

**Automotive / industrial product:** Dominant render/image or 3D canvas, small overlay controls, specifications and structured actions. Keep image legible; nav and popovers use glass.

**Profile / portfolio:** One strong identity sheet with avatar, role, stats, skill chips and CTA. Use subtle gradients behind translucent glass; avoid oversized dashboard tables.

**Wellness:** Balanced main score/progress element + interpretable trends + insights. Warmer desaturated background accents allowed, but still charcoal/orange. Avoid inferential health claims.

**Marketing / landing:** Hero visual, articulate brand proposition, concise differentiators, clear CTA, sparing glass feature callouts. Do not create meaningless admin KPI cards.

## Invariants across contexts

- Primary dark and orange identity.
- Dynamic, collapsible floating glass vertical side menu.
- Real app content/behavior and accessible interactions.
- A clear focal point and intentional visual hierarchy.
- Restrained, selected translucency and gentle premium depth.

## Domain-specific exceptions

Meaningful semantic colors (loss = red; success = green; caution = amber) supersede the orange brand accent. Existing legal/financial/health warnings and regulated disclosures must retain prominence and not be obscured by styling. If a product has important existing brand colors, keep them as subordinate semantic identity markers while retaining the new material and layout direction, unless the user directs otherwise.
