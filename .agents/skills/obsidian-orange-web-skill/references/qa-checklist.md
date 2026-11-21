# QA & acceptance checklist

## Visual identity

- [ ] Near-black / graphite is the dominant color, with intentional silver accents.
- [ ] Primary screenshot 01 guides atmosphere; screenshot 08 guides application layout.
- [ ] Visual mimicry targets the actual CY·FOCUS app UI, **not** the surrounding gallery framing, laptop/tablet hardware or video scrubber.
- [ ] Sidebar follows user override (floating glass + both functional widths) rather than treating the screenshot rail literally.
- [ ] One key anchor panel + compact supporting panels mimic the reference composition where real data allows.
- [ ] Secondary patterns are chosen based on content, not copied indiscriminately.
- [ ] Primary navigation is a **vertical floating translucent side-menu card** (not a horizontal navbar), with enough contrast and correct inset spacing.
- [ ] Consistent radius, spacing, typography, borders, and surface layering.
- [ ] Glass is restrained; data-intensive cards retain strong legibility.
- [ ] Clear visual hierarchy and a differentiated anchor area (not monotonous equal cards).
- [ ] Actual product name, terminology, assets, and information architecture remain recognizable.

## Functional preservation

- [ ] All existing routes and navigation targets still work.
- [ ] Active route state works on direct URL loads and nested routes.
- [ ] Tabs, menus, filters, forms, sorting, search, dropdowns and modals are functional.
- [ ] Auth, roles, permissions, loading/error state and data wiring are preserved.
- [ ] Charts display actual data with correct units and ranges.
- [ ] No invented KPIs, dead CTAs, placeholder content, fake 3D interactions or broken assets.
- [ ] Existing tests still pass, or failures and limitations are reported honestly.

## Responsive / accessibility

- [ ] Checked at 320px, 375px, 768px, 1024px, 1440px where feasible.
- [ ] No unexpected page-wide horizontal overflow.
- [ ] Mobile drawer is usable, opened from a visible utility-header trigger, and does not obscure essential content when closed.
- [ ] Touch targets are comfortably tappable; dialogs and menus support keyboard navigation.
- [ ] **Expanded** state shows brand + icon-and-text nav labels at ~268px and the visible **Collapse sidebar** button.
- [ ] **Collapsed** state shows icons only at ~80px, retains logo/profile and active route, and the visible **Expand sidebar** button.
- [ ] Toggle works repeatedly by click, Enter and Space; label, icon and `aria-expanded` stay synchronized.
- [ ] Main content reflows smoothly between both widths without overlap, clipping or horizontal overflow.
- [ ] Icon-only nav links retain accessible names and tooltips on hover/keyboard focus; tab order remains logical.
- [ ] Navigation and refresh do not unexpectedly reset a manually selected mode when persistence is provided.
- [ ] On mobile the same menu becomes an expanded readable drawer, not an icon-only rail.
- [ ] Drawer Escape/backdrop/close behavior, focus management and background scroll-lock work.
- [ ] Main content offsets correctly for expanded and collapsed menu; no top primary-navbar duplication.
- [ ] Focus-visible is clear; `aria-current` is correct for active nav items.
- [ ] Ordinary text and UI controls meet contrast targets in real rendered backgrounds.
- [ ] Semantics, alt text, heading order, form labels and chart alternatives are maintained.
- [ ] `prefers-reduced-motion` is respected; blur fallback is readable.

## Implementation quality

- [ ] Colors and motion are tokens instead of duplicated magic values.
- [ ] No unnecessary new libraries or oversized visual assets.
- [ ] Expensive blur/glow is not applied globally.
- [ ] Shared components support variants rather than one-off copies.
- [ ] Dark-mode styling works with form autofill, scrollbars and browser defaults where applicable.
- [ ] Build/lint/type check and existing test suite run if available.

## Animation fidelity and contextual engine choice

- [ ] Screen-specific animation plan identifies trigger, purpose, engine, duration, accessible fallback and official URL.
- [ ] Motion used only where state/layout continuity benefits, or CSS chosen for simpler cases.
- [ ] GSAP used only for justified sequences/scroll product storytelling; no unnecessary dual-library installation.
- [ ] Sidebar expansion/collapse can be interrupted, reversed or repeated without fighting CSS transitions.
- [ ] Animated active pill follows router state rather than a fake hardcoded tab.
- [ ] `prefers-reduced-motion` disables spatial transformations and scroll pinning as appropriate.
- [ ] GSAP timelines, ScrollTriggers and event listeners are scoped and cleaned up on unmount/navigation.
- [ ] No looping background, misrepresented numerical values, flashing alarms or scroll hijacking.
- [ ] No single DOM transform/opacity animated concurrently by Motion and GSAP.
- [ ] Tested keyboard, mobile, slow device where possible, and reduced-motion mode.
- [ ] First visual comparison and final critique follow `reference-forensics.md`; claimed fidelity reflects actual inspection.

## Final report

- [ ] List screens and shared components changed.
- [ ] Name secondary references used and why.
- [ ] State actual verification performed and what remains unchecked.
- [ ] Report any functionality/content exceptions or tradeoffs.

## Quick scoring heuristic

1. **Identity (25%)** — dark graphite, silver and strong screenshot-01 atmosphere.
2. **Navigation (20%)** — vertical side menu, collapsible glass card, route-driven state, accessible mobile drawer.
3. **Context fit (20%)** — widgets, architecture and charts match the product.
4. **Readability (15%)** — hierarchy, accessibility, readable glass and density.
5. **Functionality (15%)** — routes, actions, state, data and permission continuity.
6. **Polish (5%)** — purposeful motion, depth, finishing details.

A high score in visual identity does not compensate for broken user workflows or inaccurate data.
