# DriveMate Graphite — Anthropic Fusion × Motion.dev × GSAP

A reusable **web-design agent skill** (v2.0) for transforming real web apps into the charcoal/silver CY·FOCUS visual style based on 12 user-provided screenshots.

**Priority**: DriveMate landing colors; image 01 composition; image 08 dashboard anatomy; user-requested vertical FLOATING GLASS SIDEBAR with functional **Expanded 268px ↔ Collapsed 80px** modes; all other images provide domain-specific patterns only. Responsive mobile drawer with full labels. Preserve existing app routing, authentication, forms, data, real charts and accessibility.

## Contents

- `SKILL.md` — main agent instructions, Anthropic-inspired critique, design system and implementation workflow.
- `references/reference-forensics.md` — detailed visual analysis of the 12 image references.
- `references/component-inventory.md` — full component anatomy and interaction contracts.
- `references/design-critique.md` — domain-specific adaptation of Anthropic visual-design heuristics.
- `references/motion-gsap-playbook.md` — choosing CSS, Motion or GSAP by user action and domain, with source links.
- `references/design-tokens.md` — palette, surfaces, typography, geometry, motion and accessibility.
- `references/component-patterns.md` — detailed floating sidebar and card/dashboard patterns.
- `references/context-playbook.md` — app archetypes and reference routing.
- `references/qa-checklist.md` — detailed QA gates for visual, functionality, a11y and motion.
- `references/images/` — all 12 visual reference screenshots (01 and 08 primary).
- `examples/theme.css` — CSS design tokens/components and motion fallbacks.
- `examples/sidebar-demo.html` — dependency-free interactive prototype of both sidebar modes and mobile drawer.
- `examples/react/GlassSidebarMotion.tsx` — Motion React integration recipe.
- `examples/react/ProductHeroGSAP.tsx` — GSAP timeline + ScrollTrigger recipe for product storytelling (not operations UI).

## Install / use

Copy this directory to a location your coding agent recognizes as a skill (for example `.claude/skills/obsidian-orange-adaptive-web/`), keeping relative references intact. The root `SKILL.md` can also be used as a standalone prompt if your agent does not support skill directories.

**Suggested agent request**:

> Apply `obsidian-orange-adaptive-web` to my actual app. Audit every existing route and component before writing code. Anchor the visual system in reference images 01 and 08, implement the floating translucent left sidebar with working Expanded/Collapsed modes and accessible mobile drawer, extract contextual UI patterns from the other references without changing product functionality, and propose only context-appropriate animations. Prefer CSS for simple effects, Motion for React state/layout, and GSAP for justified cinematic product storytelling. Provide official motion.dev/gsap.com links for animation choices and test reduced motion, responsiveness, routes and data accuracy.

## External sources / relationship

Independent user-specific synthesis informed by:

- Anthropic frontend-design skill: https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md
- Motion official docs: https://motion.dev/docs
- Motion examples: https://motion.dev/examples
- GSAP official docs: https://gsap.com/docs/v3/
- GSAP React integration: https://gsap.com/resources/React/
- GSAP ScrollTrigger: https://gsap.com/docs/v3/Plugins/ScrollTrigger/

This package does **not** reproduce the full Anthropic skill or proprietary Motion/GSAP examples; it contains original adaptations, URLs and original implementation sketches. It is not affiliated with or endorsed by Anthropic, Motion or GSAP. Vendor examples and commercial tiers may have separate licensing/access terms.
