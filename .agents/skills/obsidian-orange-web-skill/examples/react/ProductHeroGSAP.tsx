/**
 * GSAP recipe for visual product story routes only — not the default dashboard.
 * Install: npm i gsap @gsap/react
 * Docs: https://gsap.com/resources/React/
 *       https://gsap.com/docs/v3/GSAP/Timeline/
 *       https://gsap.com/docs/v3/Plugins/ScrollTrigger/
 *       https://gsap.com/docs/v3/GSAP/gsap.matchMedia%28%29/
 */
import { useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";

// Register once at module scope; no window or DOM access during render.
gsap.registerPlugin(ScrollTrigger, useGSAP);

type Props = {
  heading: string;
  description: string;
  heroImageUrl: string; // Existing product asset, not an invented image.
  callouts: string[];    // Real features only.
};

export function ProductHeroGSAP({ heading, description, heroImageUrl, callouts }: Props) {
  const root = useRef<HTMLElement>(null);

  useGSAP(() => {
    const media = gsap.matchMedia();
    media.add({
      cinematic: "(min-width: 900px)",
      reduceMotion: "(prefers-reduced-motion: reduce)",
    }, context => {
      // Skip sequencing on mobile and for reduced-motion users.
      if (!context.conditions?.cinematic || context.conditions?.reduceMotion) return;
      const selector = gsap.utils.selector(root);
      const targets = [selector(".story-heading"), selector(".story-image"), selector(".story-callout")];
      gsap.set(targets.flat(), { opacity: 0, y: 16 });
      const timeline = gsap.timeline({
        defaults: { duration: .42, ease: "power2.out" },
        scrollTrigger: { trigger: root.current, start: "top 76%", once: true },
      });
      timeline
        .to(selector(".story-heading"), { opacity: 1, y: 0 })
        .to(selector(".story-image"), { opacity: 1, y: 0, duration: .55 }, "-=.20")
        .to(selector(".story-callout"), { opacity: 1, y: 0, stagger: .11 }, "-=.18");
    });
    // Clean up media-specific ScrollTriggers and animations on route unmount.
    return () => media.revert();
  }, { scope: root, dependencies: [heading, heroImageUrl, callouts.join("|")], revertOnUpdate: true });

  return (
    <section ref={root} className="story-section" aria-label={heading}
      style={{ background: "#121315", border: "1px solid #ffffff18", borderRadius: 22,
        padding: "clamp(20px,4vw,48px)", color: "#f5f5f5" }}>
      <h1 className="story-heading" style={{ fontSize: "clamp(28px,4vw,54px)", lineHeight: 1.08 }}>
        {heading}
      </h1>
      <p className="story-heading" style={{ color: "#b4b0ad", maxWidth: 640 }}>{description}</p>
      <img className="story-image" src={heroImageUrl} alt={heading}
        style={{ width: "100%", maxHeight: 500, objectFit: "contain", display: "block" }} />
      <ul style={{ display: "flex", gap: 12, flexWrap: "wrap", padding: 0, listStyle: "none" }}>
        {callouts.map(feature => (
          <li key={feature} className="story-callout" style={{ border: "1px solid #cecece55",
            borderRadius: 14, padding: "12px 18px", background: "#cecece1a" }}>{feature}</li>
        ))}
      </ul>
    </section>
  );
}
