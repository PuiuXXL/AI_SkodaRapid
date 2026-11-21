import type { Reading, Trip, DashboardEvent } from "./types";
import React from "react";
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
            stroke={i<lit?"var(--accent)":"#608da240"} strokeWidth="4.8"/>;
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
      <svg width="34" height="30" viewBox="0 0 34 30" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <rect x="2" y="6" width="21" height="18" rx="4"/><path d="m23 12 8-4v14l-8-4z"/>
      </svg>
      <strong>Camera în așteptare</strong><button onClick={onLive}>Treci în Live</button>
    </div>
  </div>;
}

export function TripStrip({trip}: {trip: Trip | undefined}){
  return <dl className="trip-strip">{[["Viteză",fmt(trip?.speed_kmh," km/h")],["Durată",fmt(trip?.elapsed_min," min")],["Până la destinație",fmt(trip?.eta_min," min")]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}

export function RecentEvents({events}: {events: DashboardEvent[]}){
  return <section id="recent-events" className="recent-events"><div className="event-heading"><h2>Evenimente recente</h2><a href="#assistant">Asistent și jurnal</a></div>
    {events.length?<ul>{events.slice(0,3).map((e,i)=><li key={e.ts+"-"+i} className={e.type==="alarm"?"alarm-event":""}>
      <time>{time(e.ts)}</time><strong>{words(e.explanation??e.text??e.type)}</strong>{e.source&&<small>{words(e.source)}</small>}</li>)}</ul>:
      <p>În așteptarea primului eveniment.</p>}
  </section>;
}
