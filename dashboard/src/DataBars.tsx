import React from "react";
import type {Reading} from "./types";
import {fmt} from "./Panels";

type Bar = {label: string; value: Reading | undefined; unit?: string};

export function DataBars({title, items, maximum}: {title: string; items: Bar[]; maximum?: number}) {
  const measured = items.flatMap(item => typeof item.value === "number" && Number.isFinite(item.value) ? [Math.max(0, item.value)] : []);
  const scale = maximum ?? Math.max(1, ...measured);
  return <figure className="data-bars">
    <figcaption>{title}{maximum && <small>0–{maximum}{items[0]?.unit}</small>}</figcaption>
    {items.map(item => {
      const known = typeof item.value === "number" && Number.isFinite(item.value);
      return <div className="data-bar" key={item.label}>
        <div><span>{item.label}</span><output>{fmt(item.value, item.unit ?? "")}</output></div>
        <div className="data-bar-track" aria-hidden="true">{known && <i style={{width: Math.min(100, Math.max(0, item.value! / scale * 100)) + "%"}}/>}</div>
      </div>;
    })}
  </figure>;
}
