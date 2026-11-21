import React, {useId, useState} from "react";
import type {SessionData} from "./types";
import {fmt} from "./Panels";

const series = [
  {key:"attention",label:"Atenție"},
  {key:"fatigue",label:"Oboseală"},
  {key:"disengagement",label:"Dezinteres"}
] as const;

export function ScoreHistory({points}: {points: SessionData["history"]}) {
  const id=useId();
  const [selected,setSelected]=useState<number | null>(null);
  const index=Math.min(selected??points.length-1,points.length-1);
  const sample=points[index];
  const x=(i: number)=>40+i*840/Math.max(1,points.length-1);
  return <section className="score-history" id="score-history">
    <small>SCORURI ȘI TENDINȚE</small><h2>Evoluția stării șoferului</h2>
    <p>Scală comună 0–100 · ultimele {points.length} mostre</p>
    <div className="history-values">{series.map(({key,label})=><span key={key} className={key}>{label}<strong>{fmt(sample?.[key],"",100,0)}<small>/100</small></strong></span>)}</div>
    <svg viewBox="0 0 900 240" role="img" aria-label="Evoluția atenției, oboselii și dezinteresului, de la cea mai veche la cea mai recentă mostră">
      <defs>{series.map(({key})=><linearGradient id={id+key} key={key} x1="0" y1="0" x2="0" y2="1"><stop stopColor="currentColor" stopOpacity=".25"/><stop offset="1" stopColor="currentColor" stopOpacity=".01"/></linearGradient>)}</defs>
      {[0,25,50,75,100].map(value=><g className="history-grid" key={value}><line x1="40" x2="880" y1={210-value*1.8} y2={210-value*1.8}/><text x="26" y={214-value*1.8} textAnchor="end">{value}</text></g>)}
      {series.map(({key})=>{
        const segments: {x:number;y:number}[][]=[];
        let current: {x:number;y:number}[]=[];
        points.forEach((point,i)=>{
          const value=point?.[key];
          if(typeof value==="number"&&Number.isFinite(value)) current.push({x:x(i),y:210-Math.max(0,Math.min(1,value))*180});
          else if(current.length){segments.push(current);current=[];}
        });
        if(current.length)segments.push(current);
        return <g key={key} className={key}>{segments.map((segment,i)=>{
          const path=segment.map((p,j)=>(j?"L":"M")+p.x+" "+p.y).join(" ");
          return <g key={i}><path d={path+" L"+segment.at(-1)!.x+" 210 L"+segment[0].x+" 210 Z"} fill={"url(#"+id+key+")"}/><path d={path} fill="none" stroke="currentColor" strokeWidth="2.5" vectorEffect="non-scaling-stroke"/></g>;
        })}</g>;
      })}
      {points.length>0&&<line className="history-cursor" x1={x(index)} x2={x(index)} y1="25" y2="210"/>}
      <text x="40" y="235" className="history-axis">Cea mai veche</text><text x="880" y="235" textAnchor="end" className="history-axis">Cea mai recentă</text>
    </svg>
    {points.length>1&&<label className="history-selector">Explorează mostrele<input type="range" min={0} max={points.length-1} value={index} onChange={e=>setSelected(Number(e.target.value))}/><output>{index+1} / {points.length}</output><button onClick={()=>setSelected(null)} aria-pressed={selected===null}>Urmărește Live</button></label>}
  </section>;
}
