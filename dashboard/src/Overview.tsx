import type { Reading, Trip, DashboardEvent } from "./types";
import React from "react";
import {Optic} from "./Optic";
import {MeasureIcon} from "./MeasureIcon";
import {fmt,time,words} from "./Panels";

export function AttentionGauge({value}: {value: Reading | undefined}){
  // Adapted from Vision UI Dashboard React's SatisfactionRate (MIT).
  const progress=Number.isFinite(value)?Math.max(0,Math.min(100,value!*100)):null;
  return <div className="vision-ring"><svg viewBox="0 0 120 120" aria-hidden="true">
    {Array.from({length:20},(_,i)=><line key={i} x1="60" x2="60" y1="2" y2={i%5===0?"7":"5"} transform={`rotate(${i*18} 60 60)`} stroke="var(--ui-stroke-strong)" strokeWidth={i%5===0?1.5:1}/>)}
    <circle cx="60" cy="60" r="49" fill="none" stroke="var(--line)" strokeWidth="9"/>
    {progress!==null&&progress>0&&<circle cx="60" cy="60" r="49" pathLength="100" strokeDasharray={progress+" 100"} transform="rotate(-90 60 60)" fill="none" stroke="var(--accent)" strokeWidth="9" strokeLinecap="round"/>}
    </svg><div><strong>{fmt(value,"",100,0)}</strong><small>Atenție / 100</small></div></div>;
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
    <div className="score-reading-track" aria-hidden="true">{measured&&<i style={{width:Math.max(0,Math.min(100,value!*100))+"%"}}/>}</div>
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
