# Deliberate design, critique and writing — Anthropic-inspired synthesis

Official reference: https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md

This is an original synthesis tailored to the user’s CY·FOCUS screenshots, **not a replacement copy of Anthropic’s skill** and not affiliated with Anthropic.

## Intent first, interface second

State the platform audience, domain, and three most common actions. Map the existing route tree and actual content before selecting component patterns. The distinct aesthetic has already been chosen by the user: cinematic warm-black and silver, high signal-to-noise, compact software-product density, and translucent card-like vertical navigation. Do not drift to a pale template, generic gradient, equal-card grids, large marketing typography or a random cyber UI.

## Two-pass design plan

**Pass A — visual charter**: list the 5–6 central colors, one primary typeface and numeric treatment, 8px spacing, two spatial zones (floating sidebar / content), dominant content region, one quiet support region, animation budget, mobile adaptation. Draft a wireframe that includes *real* component names and content.

**Pass B — critical review**: ask whether any element would look identical on a finance app, an industrial telemetry dashboard and a designer portfolio; if so, contextualize it. Ask whether each line, border, badge, glow, pill and label reveals hierarchy, grouping, urgency or an action. Remove useless decoration. Keep typography intentionally compact in operational pages, spacious in showcase pages, and readable in both.

## Hero vs operation surfaces

A landing page may use one strong visual hero; an operations dashboard's "hero" is its primary user task, often a status overview, map or data panel rather than large copy. Prioritize the object that matters (incident list, portfolio order ticket, industrial machine, vehicle, service catalog). Avoid default KPI+chart+activity grids when they don't help the job.

## Microcopy and data meaning

Use real labels, plain action verbs, sentence case, consistent terminology across buttons and notifications, clear empty/error states with next steps, and realistic localized currency/date/number formatting. Do not rename product entities or invent alerts, transactions, statuses or KPIs. A status color must not be the only way to interpret risk.

## Motion discipline

Prefer transitions that clarify an explicit change: side menu expanded, filter applied, view switched, detail opened, save confirmed. One orchestrated marketing entrance may be defensible; cascading every card on every route is not. Separate information feedback (must be conveyed) from decorative choreography (may be removed).

## Delivery critique

If possible, inspect screenshots instead of trusting code structure. Compare geometry, text and contrast. Ask: what is the strongest focal point? Is it the same object the user needs? Does the first 2 seconds look like screenshot 01/08? Are all important actions retained? Are empty, error and reduced-motion states genuinely implemented? Repeat until the same graphite identity is unmistakable without importing unrelated features.
