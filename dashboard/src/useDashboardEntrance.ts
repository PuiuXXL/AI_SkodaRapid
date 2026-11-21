import type {RefObject} from "react";
import {gsap} from "gsap";
import {useGSAP} from "@gsap/react";

gsap.registerPlugin(useGSAP);

export function useDashboardEntrance(scope: RefObject<HTMLDivElement | null>) {
  useGSAP(() => {
    const media = gsap.matchMedia();
    media.add("(prefers-reduced-motion: no-preference)", () => {
      const entrance = gsap.timeline({defaults: {duration: .32, ease: "power2.out", clearProps: "transform,opacity,visibility"}})
        .from(".brand", {y: -5, autoAlpha: .6}, 0)
        .from(".title-copy", {y: 10, autoAlpha: .6}, .04);
      const field = scope.current?.querySelector(".optical-field");
      if (field) entrance.from(field, {scale: .93, autoAlpha: .4, duration: .5}, .08);
    }, scope);
    return () => media.revert();
  }, {scope});
}
