import React from "react";
import type {Reading} from "./types";
import {fmt} from "./Panels";

type Bar = {label: string; value: Reading | undefined; unit?: string};

export function DataBars({title, items, maximum}: {title: string; items: Bar[]; maximum?: number}) {
  const measured = items.flatMap(item => typeof item.value === "number" && Number.isFinite(item.value) ? [Math.max(0, item.value)] : []);
  const scale = maximum ?? Math.max(1, ...measured);
  return <figure className="vision-columns">
    <figcaption>{title}{maximum && <small>0–{maximum}{items[0]?.unit}</small>}</figcaption>
    <div className="vision-bars">{items.map(item => {
      const known = typeof item.value === "number" && Number.isFinite(item.value);
      return <div className="vision-column" key={item.label}>
        <output>{fmt(item.value, item.unit ?? "")}</output>
        <div className="vision-bar-track" aria-hidden="true">{known && <i style={{height: Math.min(100, Math.max(0, item.value! / scale * 100)) + "%"}}/>}</div><small>{item.label}</small>
      </div>;
    })}</div>
  </figure>;
}
