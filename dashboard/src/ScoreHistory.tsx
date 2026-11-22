import React, {useId, useState} from "react";
import type {SessionData} from "./types";
import {fmt,time} from "./Panels";
import {smoothPath} from "./charts";

const series = [
  {key:"attention",label:"Attention"},
  {key:"fatigue",label:"Fatigue"},
  {key:"disengagement",label:"Disengagement"}
] as const;

export function ScoreHistory({points,sectionId,eventTime}: {points: SessionData["history"];sectionId?:string;eventTime?:number}) {
  const id=useId();
  const [selected,setSelected]=useState<number | null>(null);
  const index=Math.min(selected??points.length-1,points.length-1);
  const sample=points[index];
  const x=(i: number)=>36+i*856/Math.max(1,points.length-1);
  const eventIndex=eventTime===undefined?-1:points.findIndex((point,i)=>{
    const before=points[i-1]?.ts,after=point?.ts;
    return after===eventTime||(before!==undefined&&after!==undefined&&before<eventTime&&eventTime<=after);
  });
  return <section className="score-history" id={sectionId}>
    <small>SCORES & TRENDS</small><h2>Driver state over time</h2>
    <p>Shared scale 0–100 · {points.filter(Boolean).length} available samples · gaps indicate missing data</p>
    <div className="history-values">{series.map(({key,label})=><span key={key} className={key}>{label}<strong>{fmt(sample?.[key],"",100,0)}<small>/100</small></strong></span>)}</div>
    <div className="vision-timelines">{series.map(({key,label})=>{
      const traces:{x:number;y:number}[][]=[];
      let trace:{x:number;y:number}[]=[];
      points.forEach((point,i)=>{
        const value=point?.[key];
        if(typeof value==="number"&&Number.isFinite(value))trace.push({x:x(i),y:56-Math.max(0,Math.min(1,value))*48});
        else if(trace.length){traces.push(trace);trace=[];}
      });
      if(trace.length)traces.push(trace);
      return <figure key={key} className={key}><figcaption>{label}</figcaption>
        <div className="timeline-plot"><div className="timeline-scale" aria-hidden="true"><span>100</span><span>50</span><span>0</span></div>
        {!traces.length&&<span className="timeline-note">Waiting for data</span>}
        <svg viewBox="30 0 868 66" preserveAspectRatio="none" role="img" aria-label={label+" · trend from 0 to 100"}>
          <defs><linearGradient id={id+key} x1="0" x2="0" y1="0" y2="1"><stop stopColor="currentColor" stopOpacity=".2"/><stop offset="1" stopColor="currentColor" stopOpacity=".02"/></linearGradient></defs>
          {[8,32,56].map(y=><g key={y}><line x1="36" x2="892" y1={y} y2={y} stroke="var(--line)" strokeDasharray="4 5"/></g>)}
          {traces.map((segment,i)=>{
            const line=smoothPath(segment.map(p=>[p.x,p.y]));
            return <g key={i}><path d={line+" L"+segment.at(-1)!.x+" 56 L"+segment[0].x+" 56 Z"} fill={"url(#"+id+key+")"}/>
              <path d={line} fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray={key==="fatigue"?"6 3":key==="disengagement"?"2 3":undefined} vectorEffect="non-scaling-stroke"/>
              {segment.length===1&&<circle cx={segment[0].x} cy={segment[0].y} r="3" fill="currentColor"/>}</g>;
          })}
          {index>=0&&<line x1={x(index)} x2={x(index)} y1="4" y2="60" stroke="var(--muted)"/>}
          {typeof sample?.[key]==="number"&&Number.isFinite(sample[key])&&<circle cx={x(index)} cy={56-Math.max(0,Math.min(1,sample[key]!))*48} r="3" fill="currentColor"><title>{label+" · "+fmt(sample[key]," /100",100,0)+" · "+time(sample.ts)}</title></circle>}
          {eventIndex>=0&&<line x1={x(eventIndex)} x2={x(eventIndex)} y1="4" y2="60" stroke="var(--accent)" strokeDasharray="3 3"/>}
        </svg></div></figure>;
    })}</div>
    <div className="timeline-time-axis"><span>{time(points.find(point=>point?.ts!==undefined)?.ts)}</span><span>{sample?.ts!==undefined?"Selected · "+time(sample.ts):"Samples in order received"}</span><span>{time([...points].reverse().find(point=>point?.ts!==undefined)?.ts)}</span></div>
    {eventTime!==undefined&&<p>Selected event · {time(eventTime)} · {eventIndex>=0?"marked on chart":"outside the available dated samples"}</p>}
    {points.length>1&&<label className="history-selector">Explore samples<input type="range" min={0} max={points.length-1} value={index} onChange={e=>setSelected(Number(e.target.value))}/><output>{index+1} / {points.length}</output><button onClick={()=>setSelected(null)} aria-pressed={selected===null}>Follow live</button></label>}
  </section>;
}
