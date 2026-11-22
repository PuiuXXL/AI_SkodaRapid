// Chart primitives of the DriveMate dashboard: plain SVG / CSS, gradient fills, no outlines, no chart library.
// Every chart takes real readings (number | null | undefined) and shows a gap or "—" for missing data: nothing is
// interpolated across a gap and nothing is invented. Colours come from CSS (`currentColor` + the tone classes in
// fluid.css), so light and dark themes share the same components.
import {useId} from "react";
import type {ReactNode} from "react";
import type {Reading} from "./types";

export type Tone = "ink" | "soft" | "ok" | "warn" | "danger";
type Value = Reading | undefined;
const known=(v: unknown): v is number=>typeof v==="number"&&Number.isFinite(v);
const clamp=(v: number,lo=0,hi=1)=>Math.max(lo,Math.min(hi,v));
const round=(v: number)=>Math.round(v*100)/100;

/** A smooth path through the points (Catmull-Rom as cubic Béziers, clamped so the curve never overshoots a sample). */
export function smoothPath(points: [number,number][]): string {
  if(!points.length)return "";
  let d=`M${round(points[0][0])} ${round(points[0][1])}`;
  for(let i=0;i<points.length-1;i++){
    const p0=points[i-1]??points[i],p1=points[i],p2=points[i+1],p3=points[i+2]??p2;
    const lo=Math.min(p1[1],p2[1]),hi=Math.max(p1[1],p2[1]);
    const c1: [number,number]=[p1[0]+(p2[0]-p0[0])/6,clamp(p1[1]+(p2[1]-p0[1])/6,lo,hi)];
    const c2: [number,number]=[p2[0]-(p3[0]-p1[0])/6,clamp(p2[1]-(p3[1]-p1[1])/6,lo,hi)];
    d+=` C${round(c1[0])} ${round(c1[1])} ${round(c2[0])} ${round(c2[1])} ${round(p2[0])} ${round(p2[1])}`;
  }
  return d;
}

/** Runs of consecutive known values as point lists; a missing value ends a run (the gap stays visible). */
export function runs(values: Value[],x: (i: number)=>number,y: (v: number)=>number): [number,number][][] {
  const out: [number,number][][]=[];
  let run: [number,number][]=[];
  values.forEach((value,i)=>{
    if(known(value))run.push([x(i),y(value)]);
    else if(run.length){out.push(run);run=[];}
  });
  if(run.length)out.push(run);
  return out;
}

/** Area sparkline: recent samples, oldest on the left. `max` fixes the scale (default: the data's own maximum). */
export function Spark({values,max,tone="ink",height=44,label}: {values: Value[]; max?: number; tone?: Tone; height?: number; label: string}){
  const id=useId(),w=200,pad=3;
  const top=known(max)&&max>0?max:Math.max(1e-9,...values.filter(known));
  const x=(i: number)=>values.length>1?i*w/(values.length-1):w/2;
  const y=(v: number)=>pad+(1-clamp(v/top))*(height-pad*2);
  const segments=runs(values,x,y);
  return <svg className={"fx-spark tone-"+tone} viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
    <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop stopColor="currentColor" stopOpacity=".34"/><stop offset="1" stopColor="currentColor" stopOpacity="0"/></linearGradient></defs>
    {[.25,.75].map(level=><line key={level} className="fx-track" x1="0" x2={w} y1={y(top*level)} y2={y(top*level)} strokeWidth="0.7"/>)}
    {segments.map((segment,i)=>{
      const line=smoothPath(segment);
      return <g key={i}>
        {segment.length>1&&<path d={`${line} L${round(segment.at(-1)![0])} ${height} L${round(segment[0][0])} ${height} Z`} fill={`url(#${id})`}/>}
        {segment.length>1?<path d={line} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
          :<circle cx={segment[0][0]} cy={segment[0][1]} r="2.2" fill="currentColor"/>}
      </g>;
    })}
  </svg>;
}

/** Mini column chart of the last `count` samples; the newest column is the strongest. */
export function MiniBars({values,max,tone="ink",count=22,label}: {values: Value[]; max?: number; tone?: Tone; count?: number; label: string}){
  const recent=values.slice(-count),top=known(max)&&max>0?max:Math.max(1e-9,...recent.filter(known));
  return <div className={"fx-minibars tone-"+tone} role="img" aria-label={label}>
    {Array.from({length:count},(_,i)=>{
      const value=recent[i-(count-recent.length)];
      return <i key={i} data-empty={!known(value)||undefined} style={known(value)?{height:clamp(value/top)*100+"%",opacity:.35+.65*(i+1)/count}:undefined}/>;
    })}
  </div>;
}

function arc(cx: number,cy: number,r: number,from: number,to: number){
  const point=(deg: number)=>[cx+r*Math.cos(deg*Math.PI/180),cy+r*Math.sin(deg*Math.PI/180)];
  const [x0,y0]=point(from),[x1,y1]=point(to);
  return `M${round(x0)} ${round(y0)} A${r} ${r} 0 ${to-from>180?1:0} 1 ${round(x1)} ${round(y1)}`;
}

/** Half-circle gauge for a 0..1 reading. */
export function Gauge({value,tone="ink",children,label}: {value: Value; tone?: Tone; children?: ReactNode; label: string}){
  const id=useId(),share=known(value)?clamp(value):null;
  return <div className={"fx-gauge tone-"+tone} role="img" aria-label={label}>
    <svg viewBox="0 0 120 68" aria-hidden="true">
      <defs><linearGradient id={id} x1="0" x2="1" y1="0" y2="0"><stop stopColor="currentColor" stopOpacity=".35"/><stop offset="1" stopColor="currentColor"/></linearGradient></defs>
      {Array.from({length:11},(_,i)=><line key={i} x1="60" x2="60" y1="1" y2={i%5===0?"7":"4"} stroke="currentColor" strokeOpacity=".65" transform={`rotate(${i*18-90} 60 62)`}/>)}
      <path className="fx-track" d={arc(60,62,50,180,360)} fill="none" strokeWidth="11" strokeLinecap="round"/>
      {share!==null&&share>0&&<path d={arc(60,62,50,180,360)} fill="none" stroke={`url(#${id})`} strokeWidth="11" strokeLinecap="round" pathLength={100} strokeDasharray={`${share*100} 100`}/>}
    </svg>
    <div className="fx-gauge-center">{children}</div>
  </div>;
}

/** Full ring for a 0..1 share (or `value / max`). */
export function Ring({value,max=1,tone="ink",size=92,children,label}: {value: Value; max?: number; tone?: Tone; size?: number; children?: ReactNode; label: string}){
  const id=useId(),share=known(value)&&max>0?clamp(value/max):null;
  return <div className={"fx-ring tone-"+tone} style={{width:size,height:size}} role="img" aria-label={label}>
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <defs><linearGradient id={id} x1="0" x2="1" y1="1" y2="0"><stop stopColor="currentColor" stopOpacity=".3"/><stop offset="1" stopColor="currentColor"/></linearGradient></defs>
      <circle className="fx-track" cx="50" cy="50" r="41" fill="none" strokeWidth="10"/>
      {share!==null&&share>0&&<circle cx="50" cy="50" r="41" fill="none" stroke={`url(#${id})`} strokeWidth="10" strokeLinecap="round" pathLength={100} strokeDasharray={`${share*100} 100`} transform="rotate(-90 50 50)"/>}
    </svg>
    <div className="fx-ring-center">{children}</div>
  </div>;
}

export interface RankItem {label: string; value: Value; display?: ReactNode; tone?: Tone; hint?: string}
/** Ranked horizontal bars on a dotted track (label left, reading right), scaled to `max` or to the largest value. */
export function RankBars({items,max,empty="No data yet"}: {items: RankItem[]; max?: number; empty?: string}){
  const top=known(max)&&max>0?max:Math.max(1e-9,...items.map(item=>item.value).filter(known));
  if(!items.length)return <p className="fx-empty">{empty}</p>;
  return <div className="fx-rank">{items.map(item=><div key={item.label} className={"fx-rank-row tone-"+(item.tone??"ink")}>
    <span>{item.label}{item.hint&&<small>{item.hint}</small>}</span><output>{item.display??(known(item.value)?item.value:"—")}</output>
    <div className="fx-rank-track" aria-hidden="true">{known(item.value)&&item.value>0&&<i style={{width:clamp(item.value/top)*100+"%"}}/>}</div>
  </div>)}</div>;
}

export interface Share {label: string; value: number; tone?: Tone}
/** One bar split by share, with a legend; zero-value parts are left out of the bar but kept in the legend. */
export function StackBar({parts,unit="%",label}: {parts: Share[]; unit?: string; label: string}){
  const total=parts.reduce((sum,part)=>sum+Math.max(0,part.value),0);
  return <div className="fx-stack" role="img" aria-label={label}>
    <div className="fx-stack-bar">{total>0?parts.map((part,i)=>part.value>0&&<i key={part.label} className={"tone-"+(part.tone??"ink")} style={{flexGrow:part.value,opacity:part.tone?1:Math.max(.22,1-i*.2)}}/>):<i className="fx-stack-empty"/>}</div>
    <ul>{parts.map((part,i)=><li key={part.label} className={"tone-"+(part.tone??"ink")}><i style={{opacity:part.tone?1:Math.max(.22,1-i*.2)}}/>{part.label}<b>{total>0?Math.round(part.value/total*100)+unit:"—"}</b></li>)}</ul>
  </div>;
}

export interface Range {label: string; lo: Value; hi: Value}
/** p50..p95 style ranges: a solid bar to `lo` and a lighter extension to `hi`, on a shared scale. */
export function RangeBars({items,unit=" ms",empty="No measurements yet"}: {items: Range[]; unit?: string; empty?: string}){
  const measured=items.filter(item=>known(item.lo)||known(item.hi));
  const top=Math.max(1e-9,...measured.flatMap(item=>[item.lo,item.hi]).filter(known));
  if(!measured.length)return <p className="fx-empty">{empty}</p>;
  const text=(v: Value)=>known(v)?v.toLocaleString("en-GB",{maximumFractionDigits:1}):"—";
  return <div className="fx-range">{measured.map(item=><div key={item.label} className="fx-range-row">
    <span>{item.label}</span><output>{text(item.lo)} / {text(item.hi)}{unit}</output>
    <div className="fx-range-track" aria-hidden="true">
      {known(item.hi)&&<i className="fx-range-hi" style={{width:clamp(item.hi/top)*100+"%"}}/>}
      {known(item.lo)&&<i className="fx-range-lo" style={{width:clamp(item.lo/top)*100+"%"}}/>}
    </div>
  </div>)}</div>;
}

/** A strip of cells, one per sample, shaded by level (0..1); missing samples stay empty. */
export function HeatStrip({values,max=1,tone="ink",label}: {values: Value[]; max?: number; tone?: Tone; label: string}){
  return <div className={"fx-heat tone-"+tone} role="img" aria-label={label}>
    {values.length?values.map((value,i)=><i key={i} data-empty={!known(value)||undefined} style={known(value)?{opacity:.12+.88*clamp(value/max)}:undefined}/>):<i data-empty/>}
  </div>;
}

/** Head pose: yaw moves the dot sideways, pitch vertically (± `range` degrees), roll tilts the horizon line. */
export function PoseDial({yaw,pitch,roll,range=40,label}: {yaw: Value; pitch: Value; roll: Value; range?: number; label: string}){
  const has=known(yaw)&&known(pitch);
  const x=has?50+clamp(yaw!/range,-1,1)*34:50,y=has?50-clamp(pitch!/range,-1,1)*34:50;
  return <div className="fx-pose" role="img" aria-label={label}>
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <circle className="fx-pose-field" cx="50" cy="50" r="46"/>
      <circle className="fx-pose-inner" cx="50" cy="50" r="23"/>
      <g className="fx-pose-cross"><rect x="49.5" y="8" width="1" height="84" rx=".5"/><rect x="8" y="49.5" width="84" height="1" rx=".5"/></g>
      {has&&<g transform={`rotate(${known(roll)?clamp(roll,-45,45):0} ${round(x)} ${round(y)})`}>
        <rect className="fx-pose-horizon" x={round(x-15)} y={round(y-1)} width="30" height="2" rx="1"/>
        <circle className="fx-pose-dot" cx={round(x)} cy={round(y)} r="6"/>
      </g>}
    </svg>
  </div>;
}

/** Small state chip: an icon-less pill that is "on" (true), quiet (false) or unknown (undefined). */
export function Flag({label,on,tone="ink"}: {label: string; on: boolean | undefined; tone?: Tone}){
  return <span className={"fx-flag"+(on?" is-on tone-"+tone:"")} data-unknown={on===undefined||undefined}>{label}<b>{on===true?"Yes":on===false?"No":"—"}</b></span>;
}
