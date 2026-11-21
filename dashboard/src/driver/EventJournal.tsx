import {useState} from "react";
import type {DashboardEvent} from "../types";
import {fmt,time,words} from "../Panels";

export function EventJournal({events,id,onSelect}: {events:DashboardEvent[];id?:string;onSelect?:(ts:number)=>void}) {
  const [selection,setSelection]=useState<DashboardEvent|null>(null);
  const same=(event:DashboardEvent)=>selection!==null&&
    event.ts===selection.ts&&event.type===selection.type&&event.text===selection.text&&event.source===selection.source;
  const current=events.find(same)??events[0];
  return <section id={id} className="event-journal">
    <h2>Jurnalul călătoriei</h2>
    {current?<><div className="journal-entries" aria-label="Evenimente">{events.map((event,i)=>
      <button key={event.ts+"-"+i} aria-pressed={event===current} onClick={()=>{setSelection(event);onSelect?.(event.ts);}}>
        <time>{time(event.ts)}</time><span>{words(event.text??event.explanation??event.type)}</span>
      </button>)}</div>
      <div className="journal-detail"><small>{time(current.ts)} · {words(current.type)}</small>
        <h3>{words(current.explanation??current.text??current.type)}</h3>
        {current.source&&<p>Sursă · {words(current.source)}</p>}
        {current.channel&&<p>Canal · {words(current.channel)}</p>}
        {typeof current.latency_ms==="number"&&<p>Latență · {fmt(current.latency_ms," ms")}</p>}
      </div></>:<p>În așteptarea primului eveniment.</p>}
  </section>;
}
