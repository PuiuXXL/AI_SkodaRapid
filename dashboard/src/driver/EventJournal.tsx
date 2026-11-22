import {useState} from "react";
import type {DashboardEvent} from "../types";
import {fmt,time,words} from "../Panels";

export function EventJournal({events,id,onSelect,pageSize}: {events:DashboardEvent[];id?:string;onSelect?:(ts:number)=>void;pageSize?:number}) {
  const [selection,setSelection]=useState<DashboardEvent|null>(null);
  const [page,setPage]=useState(0);
  const pages=pageSize?Math.max(1,Math.ceil(events.length/pageSize)):1;
  const currentPage=Math.min(page,pages-1);
  const visible=pageSize?events.slice(currentPage*pageSize,(currentPage+1)*pageSize):events;
  const same=(event:DashboardEvent)=>selection!==null&&
    event.ts===selection.ts&&event.type===selection.type&&event.text===selection.text&&event.source===selection.source;
  const current=events.find(same)??events[0];
  return <section id={id} className="event-journal">
    <h2>Trip journal</h2>
    {current?<><div className="journal-list"><div className="journal-entries" aria-label="Evenimente">{visible.map((event,i)=>
      <button key={event.ts+"-"+i} aria-pressed={event===current} onClick={()=>{setSelection(event);onSelect?.(event.ts);}}>
        <time>{time(event.ts)}</time><span>{words(event.text??event.explanation??event.type)}</span>
      </button>)}</div>
      {pages>1&&<div className="journal-pagination"><button disabled={currentPage===0} onClick={()=>setPage(currentPage-1)} aria-label="Previous events">←</button><span>{currentPage+1} / {pages}</span><button disabled={currentPage===pages-1} onClick={()=>setPage(currentPage+1)} aria-label="Next events">→</button></div>}</div>
      <div className="journal-detail"><small>{time(current.ts)} · {words(current.type)}</small>
        <h3>{words(current.explanation??current.text??current.type)}</h3>
        {current.source&&<p>Source · {words(current.source)}</p>}
        {current.channel&&<p>Canal · {words(current.channel)}</p>}
        {typeof current.latency_ms==="number"&&<p>Latency · {fmt(current.latency_ms," ms")}</p>}
      </div></>:<p>Waiting for the first event.</p>}
  </section>;
}
