import type { Reading, Trip, DashboardEvent } from "./types";
import React from "react";
import {Optic} from "./Optic";
import {MeasureIcon} from "./MeasureIcon";
import {fmt,time,words} from "./Panels";

export function AttentionGauge({value}: {value: Reading | undefined}){
  const count=32;
  const lit=Number.isFinite(value)?Math.round(Math.max(0,Math.min(1,value!))*count):0;
  return <div className="gauge-card">
    <div className="gauge-art">
      <svg viewBox="0 0 200 110" aria-hidden="true">
        {Array.from({length:count},(_,i)=>{
          const angle=Math.PI*(1-i/(count-1));
          return <line key={i} x1={100+78*Math.cos(angle)} y1={98-78*Math.sin(angle)}
            x2={100+92*Math.cos(angle)} y2={98-92*Math.sin(angle)}
            stroke={i<lit?"var(--accent)":"var(--ui-stroke-strong)"} strokeWidth="4.8"/>;
        })}
      </svg>
      <div className="gauge-number"><b>{fmt(value,"",100,0)}</b><span>/ 100</span></div>
    </div>
    <strong>Atenție</strong>
  </div>;
}

export function CameraStandby({onLive}: {onLive: () => void}){
  return <div className="camera-standby">
    <div className="viewfinder" aria-hidden="true"><i/><i/><i/><i/></div>
    <div className="standby-info">
      <div className="optical-field" aria-hidden="true"><Optic/></div>
      <strong>Camera în așteptare</strong><button onClick={onLive}>Treci în Live</button>
    </div>
  </div>;
}

export function ScoreReading({label, icon, value}: {
  label: string;
  icon: "fatigue" | "focus";
  value: Reading | undefined;
}) {
  const measured = typeof value === "number" && Number.isFinite(value);
  return <div>
    <span><MeasureIcon name={icon}/>{label}</span>
    <b>{fmt(value, "", 100, 0)}{measured && <em>/100</em>}</b>
    {measured && <div className="score-meter" aria-hidden="true"><i style={{width: Math.min(100, Math.max(0, value * 100)) + "%"}}/></div>}
  </div>;
}

export function TripStrip({trip}: {trip: Trip | undefined}){
  const readings = [
    ["Viteză", "speed", fmt(trip?.speed_kmh, " km/h")],
    ["Durată", "clock", fmt(trip?.elapsed_min, " min")],
    ["Până la destinație", "arrival", fmt(trip?.eta_min, " min")]
  ] as const;
  return <dl className="trip-strip">{readings.map(([label,icon,value]) =>
    <div key={label}><dt><MeasureIcon name={icon}/>{label}</dt><dd>{value}</dd></div>
  )}</dl>;
}

export function RecentEvents({events}: {events: DashboardEvent[]}){
  return <section id="recent-events" className="recent-events"><div className="event-heading"><h2>Evenimente recente</h2><a href="#assistant">Asistent și jurnal</a></div>
    {events.length?<ul>{events.slice(0,3).map((e,i)=><li key={e.ts+"-"+i} className={e.type==="alarm"?"alarm-event":""}>
      <time>{time(e.ts)}</time><strong>{words(e.explanation??e.text??e.type)}</strong>{e.source&&<small>{words(e.source)}</small>}</li>)}</ul>:
      <p>În așteptarea primului eveniment.</p>}
  </section>;
}
