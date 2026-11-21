# Reference forensics — design elements visible in the 12 supplied images

The color descriptions below document the original screenshots. For every implementation use the DriveMate landing palette in design-tokens.md; these images guide composition and material.

These are **qualitative interpretations**, not source Figma data or guaranteed pixel measurements. Screenshots are inspiration for the inner user interface. Do not copy photo/gallery margins, tablet outlines, video progress bars or unrelated labels into the product.

## 01 — CY·FOCUS product showcase (PRIMARY, highest weight)

**Look:** muted warm-black charcoal dashboard mounted inside a dark cinematic monitor environment; upper-left copper/ember glow, deep near-black lower/right surfaces. A compact, functional left nav rail against a denser content column. Burnt orange localizes primary creation, diagram highlights, polar/radar shapes and severity. Surfaces have minute border separation and almost invisible elevation rather than bright framed cards.

**Visible anatomy:** tiny product lockup; orange `New task` CTA; vertical icon+text nav (dashboard/findings/incidents/compliance/vault/integrations); left footer help/account; screen breadcrumb and incident title; incident metadata columns (assignee/created/due/update/status/severity); small horizontal tabs (overview, detections, notes, logs, beyond); nested card grid; `Information` key/value panel; multi-axis radar / threat source map; circular findings chart; compact entity table with numeric columns. Thin rules, high-density labels, concise numbers, few large headlines.

**Implementable components:** app shell, smoked sidebar, icon nav items, shortcut primary CTA, breadcrumb, page header, status chips, filter tabs, metadata definition list, chart panel, radar plot, donut chart, entities data grid, compact user menu, chart legend and tooltip, actions and help.

**Updated user requirement overriding screenshot:** sidebar must now FLOAT 16–24px from boundaries with blurred translucent surface and have **expanded ≈268px** and **collapsed ≈80px** states, toggle ALWAYS visible. The screenshot itself does not show both modes; this is a deliberate design extension, not a claim about original behavior.

## 08 — CY·FOCUS operational dashboard (CO-PRIMARY)

**Look:** dark warm-black page with narrow red-brown atmospheric illumination near top; nearly black sections below, tiny orange highlights, 1px rows/dividers, activity cards with differentiated weight. Designed as serious operations console, not luminous game UI.

**Visible anatomy:** left brand/primary creation CTA; dashboard/findings/incidents/compliance/vault/integrations nav; footer help and avatar; top status row with open vulnerabilities number, active incident count, compliance semicircle gauge and remediation duration; trend mini-sparklines or mini-bars; large threat/heat map with orange expanding points; several ranked regional bars; separate right recent-activity feed with time/label/action icons; status and time delta pills; date range, report CTA.

**Density:** roughly 4 compact KPIs above two unequal large panels, with modest gutters and many crisp micro-labels. Primary panel is not a generic colorful gradient card. Orange intensity focused on activity/selected data; green and yellow are used only for semantic contrast.

**Transfer to other domains:** replace vulnerability KPIs with real domain KPIs; use maps only for true geo data, activity timeline only when actual event data exists; keep warm dark material and disciplined micro-hierarchy.

## 02 — Automotive showroom

Product image (center, full-width hero), dark blue-gray studio environment, floating control rail, model/year selection, discreet top control icons, 360-degree rotation affordance, three bottom cards for vehicle health, reminders, and operating cost. Borrow *central media + peripheral controls*, not the blue palette, car labels or imaginary 3D capabilities.

## 03 — Industrial extraction overview

Light technical dashboard with main 3D machine/scan status, hourly extraction bar chart, identification log, module port inspection, process matrix and precise engineering units. Borrow technical card compartmentalization, measurement units, scan progress and small annotated diagrams; recolor into charcoal/orange; 3D visualization only with actual assets.

## 04 — Sales time series

Sparse white line chart, filter pills, active selected filter, tooltip with period/value/delta, thin axis lines and curved series. Borrow category chips, hover crosshair, focused selected line and clear numeric tooltip. In Obsidian Orange use dark inset chart and orange primary series.

## 05 — Markets/trading

Near-black multi-panel analytics; candlestick and area line charts, purple/orange return distribution, buy/sell ticket, depth-of-market ladder, watchlist table, numerical side cards, soft glows. Borrow information density, card asymmetry and purpose-built order controls. Preserve financial gain/loss and bid/ask colors; avoid decorative ROI art if unsupported by data.

## 06 — Radial emotional dashboard

Eight petal-like segmented categories with inner/outer rings, text and counts. Borrow circular categorical navigation only when categories have bounded measurable meaning. Never substitute for conventional search/tables on complex data.

## 07 — Frosted profile card

Soft translucent identity sheet, circular avatar, prominent name + role, capability chips, three quick metrics and two clear actions. Borrow layered glass, calm personal hierarchy and primary/secondary CTA layout. Map colors to charcoal/orange, not blue/pink gradient.

## 09 — Mobility/route panel

Dark purple vehicle/battery representation paired with route mapping and GPS overlay. Borrow route-as-primary-canvas and segmented data controls for geographic apps only; retain real map geometry and locations.

## 10 — Energy monitor

Very low-key graphite operating dashboard, 3-column telemetry and compact metric plots; consumption, connected devices, recommendations, health indicators, dark-to-neutral supporting surfaces. Borrow dense operational status, recommendations, proper unit labels and sober state colors.

## 11 — Tech product showcase

Large cinematic hero with a lit fan, strong editorial left heading, compact feature callouts, inset rotating device card and downstream product story tiles. Borrow one vivid focal visual, hotspot callouts and guided storytelling for commerce/landing pages. Only apply scroll choreography where a real product narrative exists.

## 12 — Wellness overview

Pastel lavender screen with large floral health ring, compact physiological chart cards, current score, sleep, recovery and battery status. Borrow circular overview and gentle trend grouping; keep user-approved dark/orange brand globally and avoid misleading diagnostic statements.

## Final hierarchy and composition rules

1. **01 decides colors and mood.** 08 decides dense dashboard/operational hierarchy.
2. User's floating Collapsed ⇄ Expanded sidebar replaces the visually flat reference rail.
3. Use **one hero/anchor panel** and several secondary sizes; not 12 identical cards.
4. Use glass for the sidebar, floating filters/overlays, selected large cards; solid for dense tables and logs.
5. Use orange for primary action, selected state, important signal and primary series. Avoid orange on everything.
6. Keep thin white translucent borders, compact stats, small glyphs, subdued legends, precision numeric spacing and restrained depth.
7. Compare final implementation to real reference images before claiming high fidelity.
