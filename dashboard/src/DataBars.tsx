import React from "react";
import type {Reading} from "./types";
import {fmt} from "./Panels";
import "./data-charts.css";

type Bar = {label: string; value: Reading | undefined; unit?: string};

export function DataBars({title, items, maximum}: {title: string; items: Bar[]; maximum?: number}) {
  const measured = items.flatMap(item => typeof item.value === "number" && Number.isFinite(item.value) ? [Math.max(0, item.value)] : []);
  const scale = typeof maximum==="number"&&Number.isFinite(maximum)&&maximum>0?maximum:Math.max(1, ...measured);
  return <figure className="vision-columns data-comparison">
    <figcaption>{title}<small>{maximum?"Scală fixă":"Scală adaptată datelor"}</small></figcaption>
    <div className="comparison-bars">{items.map(item => {
      const known = typeof item.value === "number" && Number.isFinite(item.value);
      return <div className="comparison-row" key={item.label}>
        <span>{item.label}</span>
        <output>{fmt(item.value, item.unit ?? "")}</output>
        <div className="comparison-track" aria-hidden="true">{known && <i style={{width: Math.min(100, Math.max(0, item.value! / scale * 100)) + "%"}}/>}</div>
      </div>;
    })}</div><div className="comparison-axis" aria-hidden="true"><span>0</span><span>{fmt(scale/2)}</span><span>{fmt(scale,items[0]?.unit??"")}</span></div>
  </figure>;
}
