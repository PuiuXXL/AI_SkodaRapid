# Design tokens & material language

## Identity

**Reference priority:** the DriveMate landing for color, images 01 and 08 for layout and material. The effect must feel precise, quiet, engineered and premium rather than loudly cyberpunk. Silver should guide attention and communicate product hierarchy.

## Color system

| Token | Suggested value | Usage |
|---|---|---|
| `--ui-bg` | `#151515` | Primary canvas |
| `--ui-bg-raised` | `#1b1b1b` | Alternate page section |
| `--ui-surface-1` | `#202020` | Primary card |
| `--ui-surface-2` | `#292929` | Elevated, interactive panel |
| `--ui-surface-soft` | `rgba(255,255,255,.035)` | Soft translucent overlay |
| `--ui-glass` | `rgba(32,32,32,.68)` | Floating side menu and modal surfaces |
| `--ui-glass-heavy` | `rgba(27,27,27,.86)` | Text-heavy translucent panels |
| `--ui-stroke` | `rgba(255,255,255,.10)` | 1px quiet border |
| `--ui-stroke-strong` | `rgba(255,255,255,.17)` | Dividers / controls |
| `--ui-text` | `#f5f5f5` | Headlines and body |
| `--ui-text-muted` | `#b5b5b5` | Secondary content |
| `--ui-text-subtle` | `#a3a3a3` | Tertiary metadata; verify contrast |
| `--ui-accent` | `#cecece` | Primary silver |
| `--ui-accent-hover` | `#e4e4e4` | Hover and focus enhancement |
| `--ui-accent-dim` | `rgba(206,206,206,.14)` | Selected states |
| `--ui-accent-stroke` | `rgba(206,206,206,.34)` | Highlight border |
| `--ui-success` | `#49C89E` | Good / available |
| `--ui-danger` | `#F46D72` | Destructive / critical |
| `--ui-warning` | `#FFBC65` | Warning |
| `--ui-info` | `#78B9FF` | Independent information color |

Do not use low-contrast silver body copy on graphite surfaces without testing. On bright silver buttons, use a near-black label (`#151515`) rather than white. Maintain semantic colors where users expect them; silver does not replace green for gains, red for losses, or severity semantics.

## Backdrop & glow

- Main canvas: charcoal with an extremely subtle directional neutral light, not a saturated gradient.
- Local highlight: one low-opacity silver blur behind a hero/important chart or hovered control.
- Optional secondary cool illumination (very low saturation) in technical or automotive product showcases; it must stay subordinate.
- No heavy grain/noise texture unless the user requests it. No global backdrop blur on all cards.

## Surfaces

- **Glass 1 (floating side menu):** 60–75% dark translucent opacity, 16–24px backdrop blur, 1px white border at ~10–16%, soft shadow.
- **Glass 2 (floating contextual card):** 78–88% opacity, 12–18px blur; prioritizes readability.
- **Solid 1 (dashboard/table):** opaque graphite, 1px subtle border, no blur.
- **Inset:** deeper charcoal for charts, code, logs and plot wells.
- **Silver-active:** dark silver-tinted surface, thin silver stroke, tiny inner highlight.

If browser support or performance is limited: use solid color fallbacks before `backdrop-filter`; do not make content illegible if transparency is disabled.

## Typography

- Preferred: `Geist`, `Inter`, or an existing project sans-serif. Avoid gratuitous font installation.
- Hero headline: 42–64px where appropriate, not in dense dashboards.
- Dashboard page title: 26–34px desktop, 22–28px mobile.
- Section heading: 16–20px; panel heading: 14–17px.
- Body: 14–16px; dense data: 12–14px with sufficient line-height.
- Numeric KPI: 28–44px depending on density. Use `font-variant-numeric: tabular-nums`.
- Eyebrows: 10–12px, moderate tracking, never ultra-tiny informational text.
- Use weight and hierarchy rather than many different font sizes.

## Radius & spacing

- Space scale: 4, 8, 12, 16, 24, 32, 40, 48, 64px.
- Tiny chips: 9–12px radius or pill.
- Cards: 14–18px radius. Outer hero/modals: 20–24px.
- Floating side-menu card: 18–24px radius; inner selected menu row can be a pill. Expanded width 256–284px; collapsed width 72–84px; inset 16–24px from viewport edges.
- Card padding: 16–24px; dense table cell: 10–14px.
- Desktop page gutter: 32–56px; tablet 20–32px; mobile 16px.
- Standard grid gap: 16px desktop, 12px mobile.

## Borders, highlights, shadows

- Card border: translucent 1px; show separation through tonality, not deep black borders.
- Shadow: soft `0 16px 45px rgba(0,0,0,.24)` for elevated elements; cards use much less.
- Optional top-edge gradient border / reflection on only a few premium surfaces.
- Silver bloom: `0 0 30px rgba(206,206,206,.10)` behind primary CTAs or selected plot elements. Don't put this everywhere.

## Motion

- Fast: 120–160ms for hover/focus.
- Standard: 180–240ms for panels, active nav indicators, filter changes.
- Long: 260–360ms only for major drawers or reveals.
- Easing: smooth deceleration; avoid bounce-heavy motion on data tools.
- Never animate statistical values misleadingly. Support `prefers-reduced-motion` by removing nonessential transforms and transitions.

## Chart colors

- Primary series: accent silver.
- Secondary: desaturated slate, neutral gray, pale gold.
- Semantic: green/red/warning based on meaning, not theme.
- Line grid: white 6–9% opacity; axes and legends must remain readable.
- Tooltips: heavy glass or opaque dark; strong numbers, subdued labels, thin border.
- Preserve meaningful comparison and numeric integrity; don't blend multiple series into one silver glow.

## Accessibility / perceptual constraints

- Minimum WCAG AA contrast: 4.5:1 for ordinary text and 3:1 for large text/UI boundaries where applicable.
- The exact token pairing matters; test it in actual rendered contexts, especially muted labels and charts.
- Active states need shape/label/border as well as hue.
- Keyboard focus must have a visible outline on dark and silver surfaces.
- Preferred interactive target 44×44px where feasible.
- Avoid unnecessary horizontal layout shifts, overlay obstruction and high-cost full-screen blurs.
