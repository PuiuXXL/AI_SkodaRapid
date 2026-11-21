# Component extraction and implementation contracts

This is a catalog, not a directive to force every widget into every platform. **Only implement components justified by existing content.** Each component must preserve keyboard behavior, data wiring and relevant disabled/loading/error/empty states. Primary reference IDs: 01 + 08.

## Shell and navigation — mandatory for platform pages

| Component | Anatomy / appearance | Functional contract | Animation recommendation |
|---|---|---|---|
| `AppShell` | Near-black canvas, 16–24px outer padding, sidebar + main unequal columns | Actual routes, resize and overflow, responsive, skip-to-content | CSS grid or Motion layout, not both on same property |
| `GlassSidebar` | Floating smoked glass, thin rim, inner reflection, rounded 20px | Desktop expanded 268px / collapsed 80px; mobile label drawer | Motion layout or CSS width; 180–240ms |
| `SidebarBrand` | monochrome logo, concise text, tiny subtitle | Collapse hides full text, not accessible brand | short crossfade only |
| `SidebarToggle` | always visible compact icon button | click/Enter/Space; aria-label/aria-expanded; persist state; tooltip | 160–220ms rotation or icon swap |
| `SidebarNavItem` | icon 18–22px, muted label, silver active pill/left mark | real href, router active, nested route, permission gating, tooltip when collapsed | Motion layoutId active indicator or CSS |
| `SidebarSection` | concise group labels, compact separators | nested expand/collapse if genuine hierarchy | Motion AnimatePresence on labels or submenu |
| `WorkspaceSwitch` | small selector with icon and chevron | actual available workspaces only, keyboard menu | 150ms opacity+translate |
| `SidebarFooter` | help/settings/avatar mini sheet | remain reachable in both states | no auto entrance |
| `UtilityHeader` | optional breadcrumb, search, notification, avatar | not horizontal primary navbar | no scroll theatrics |
| `MobileDrawer` | readable full-label glass overlay | modal focus trap, Escape/backdrop/close, restore focus, scroll lock | Motion AnimatePresence 220ms or native dialog |
| `CommandSearch` | dark search well, keyboard shortcut glyph | real search, keyboard shortcut only if implemented | results fade 120ms |

## Hierarchy, controls and surfaces

| Component | Anatomy / appearance | Functional contract | Animation recommendation |
|---|---|---|---|
| `PageHeader` | small path, substantial title, quiet subtitle, right aligned actions | heading semantics, breadcrumb URLs | generally static |
| `PrimaryCTA` | tight silver fill, near-black label | working action, loading/disabled/focus | CSS hover/press |
| `SecondaryButton` | graphite or translucent, white outline | clear accessible label, proper type | CSS |
| `IconButton` | bordered circle or rounded-square | accessible name, 44px target | CSS |
| `SegmentedTabs` | flat dark bar, understated active pill | keyboard arrows/selection semantics | Motion `layoutId` active pill |
| `StatusBadge` | small tinted capsule, icon/word | semantic severity, no color-only signal | CSS |
| `FilterChip` | compact rounded capsule | selected states and clear/filter reset | CSS; tab indicator if grouped |
| `Select` / `DateRange` | dark outlined control/popover | keyboard, validation, timezone labels | 140ms opacity popover |
| `GlassCard` | only elevated contextual cards use blur | preserve contrast and readability | no default hover float |
| `OpaqueDataPanel` | graphite body, 1px divider | charts/tables remain readable | static surface |
| `KpiTile` | tiny label, 28–44px number, trend line, delta | real data, formatted units and change | subtle data change feedback only |
| `MiniSparkline` | fine lines or bars, one accent | accurate trend axis/label alternative | animate initial draw once if meaningful |
| `MetadataGrid` | compact label-value columns | empty value, localization, units | static |
| `EmptyState` | explanation + next action | never mask data load failure | minimal fade |
| `Skeleton` | tonal placeholder matching layout | no fictitious content, reduced-motion static | subtle shimmer only if allowed |
| `Toast` | corner overlay, small status indicator | live region and dismiss | Motion AnimatePresence |
| `Dialog` / `Popover` | dark heavy glass, crisp outline | focus trap/return, escape, backdrop, placement | Motion enter/exit 160–240ms |
| `FormField` | label, helper, input, error | auth/validation/server state/autofill | status change only |
| `DataTable` | quiet dividers, dense aligned numbers | sort/search/pagination/actions, scroll locally | rows do not repeatedly fly in |
| `Pagination` | compact page control | working cursors/page links and totals | static |
| `ActivityFeed` | time/status icon/title/details per row | real events and timestamps, click action | new event gentle highlight |
| `Timeline` | precise causal sequence | only if events are sequential | optional timeline progress |

## Domain-specific dashboards — conditional only

| Component | Source | Presentation and data rules | Animation choice |
|---|---|---|---|
| `ThreatRegionMap` | 08 | real geography + warm amber dots/heat clusters, location legend | Motion dot emphasis; no constant pulse |
| `RiskRadar` | 01 | radial labeled axes, readable grid, accurate domain | CSS hover / Motion shape transition only |
| `FindingsDonut` | 01 | categories, count, legend and alternative table | animate initial angle if actual data |
| `BarRanking` | 08 | horizontal region values, silver selected, precise total | short bar length only on data change |
| `TrendChart` | 04 | date axis, hover crosshair, tooltip period/value/delta | Motion tooltip; chart library for curves |
| `Candlestick` | 05 | correct OHLC units, high-contrast up/down | avoid fanciful easing of values |
| `OrderTicket` | 05 | quote, buy/sell, quantity, fees, confirm | no theatrical trade confirmation |
| `OrderBook` | 05 | bid/ask ladder, readable exact numbers | incremental highlight on real update |
| `IoTDevicePanel` | 03/10 | live units, device states, optional actual 3D model | purposeful reveal of active module |
| `IndustrialLog` | 03 | status, timestamps, identifiers, diagnostics | new event subtle opacity |
| `ExtractionBarChart` | 03 | hourly units, selected period and accurate scale | tooltip + subtle selection |
| `VehicleHero` | 02/11 | actual 2D/3D asset, model info, peripheral specs | GSAP hero only for product stories |
| `HotspotOverlay` | 02/11 | anchor on object geometry, numbered labels if meaningful | Motion 120ms tooltip / GSAP guided tour |
| `RouteMap` | 09 | true geodata, route controls, geographical integrity | respect map SDK, no fake path |
| `CircularCategories` | 06 | legible values, meaningful categories, keyboard options | Motion selected segment if useful |
| `ProfileCard` | 07 | avatar/role/chips/metrics/CTA | glass appearance, no obligatory motion |
| `WellnessRing` | 12 | labeled actual proportion, trend details | simple SVG progress and reduced-motion |
| `Recommendations` | 10/12 | actionable source-based suggestions, priority | show/hide with Motion if dynamic |
| `ProductStory` | 11 | one scene and sequenced features | GSAP timeline/ScrollTrigger if warranted |

## Component use contract

- **Inventory** every existing component/route before choosing from the table.
- **Map** reference pattern to user job, data source, interaction state, error and empty cases.
- **Style** with centralized tokens; do not duplicate pixel literals across files.
- **Integrate** actual router, roles and domain semantics; do not replace actions with dummy handlers.
- **Test** expanded/collapsed side menu and reflow; mobile dialog and keyboard; chart fidelity and reduced motion.
- **Animate** only if motion explains cause/effect or guides attention; document official examples in `motion-gsap-playbook.md`.
