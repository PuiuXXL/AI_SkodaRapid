import {MotionConfig} from "motion/react";
import type {StateProps, SessionData, Trip} from "./types";
import React,{useState,useRef,useEffect} from "react";
import {videoOrigin} from "./driver/session";
import {Panel,Metrics,Detail,Rows,fmt,words,time,yes} from "./Panels";

import "./design.css";
import "./obsidian.css";
import {DriverApp} from "./driver/DriverApp";
import {DataBars} from "./DataBars";

import {AttentionGauge,ScoreReading,TripStrip} from "./Overview";
import {zones} from "./labels";
import {Spark} from "./charts";
import type {Sample} from "./telemetry";
function Feed({src,label}: {src: string; label: string}){
 const [attempt,retry]=useState(0),[error,setError]=useState(false);
 useEffect(()=>setError(false),[src]);
 return error?<div className="feed-error"><span>{label} · unavailable</span> <button onClick={()=>{retry(attempt+1);setError(false)}}>Retry</button></div>:
 <img key={attempt} src={src} alt={label} onError={()=>setError(true)}/>;
}
/** P1's two MJPEG streams (perception/stream.py). A stream that cannot be loaded says so and offers a retry. */
export function Cameras({socket,cue,trip,onDock}: {socket: SessionData["socket"]; cue: number; trip: Trip | undefined; onDock: (docked: boolean) => void}){
 const [requested,setRequested]=useState<boolean | null>(null);
 const camera=useRef<HTMLElement>(null), boundary=useRef<HTMLDivElement>(null);
 const [compact,setCompact]=useState(false);
 useEffect(()=>setRequested(null),[socket]);
 useEffect(()=>{

   const el=boundary.current;
   if(!el)return;
   const observer=new IntersectionObserver(([entry])=>{
     const docked=entry.boundingClientRect.bottom<(entry.rootBounds?.top??0);
     setCompact(docked);onDock(docked);
   },{threshold:0,root:el.closest(".dashboard")});
   observer.observe(el);
   return ()=>observer.disconnect();
 },[onDock]);
 // Docked: the preview sits exactly over a reserved slot ([data-camera-slot]: beside the overview, then in the
 // band under the instrument stack), so it is larger than a floating thumbnail and never covers content. Without a
 // visible slot (narrow screens) it falls back to the corner, and the page keeps a bottom margin for it.
 useEffect(()=>{
   const el=camera.current,page=el?.closest<HTMLElement>(".dashboard");
   if(!el)return;
   const clear=()=>{el.removeAttribute("style");delete el.dataset.dock;delete el.dataset.dockLayout;el.classList.remove("dock-moving");};
   if(!compact||!page){clear();return;}
   let frame=0,current="",moving:ReturnType<typeof setTimeout>|undefined;
   function place(){
     frame=0;
     if(!el)return;
     const view=window.innerHeight;
     const slots=Array.from(document.querySelectorAll<HTMLElement>("[data-camera-slot]"),node=>({name:node.dataset.cameraSlot??"",rect:node.getBoundingClientRect()}))
       .filter(({rect})=>rect.width>80&&rect.height>60&&rect.top>=-2&&rect.bottom<=view+2);
     const slot=slots.find(({name})=>name==="stack")??slots.find(({name})=>name==="overview");
     const name=slot?.name??"float";
     if(name!==current){
       if(current){el.classList.add("dock-moving");clearTimeout(moving);moving=setTimeout(()=>el.classList.remove("dock-moving"),340);}
       current=name;
     }
     el.dataset.dock=name;
     if(slot){
       const {left,top,width,height}=slot.rect;
       Object.assign(el.style,{left:left+"px",top:top+"px",width:width+"px",height:height+"px",right:"auto",bottom:"auto"});
       el.dataset.dockLayout=width/height>1.9?"row":"column";
     }else{el.removeAttribute("style");el.dataset.dockLayout="row";}
   }
   const schedule=()=>{if(!frame)frame=requestAnimationFrame(place);};
   place();
   // the slots open (CSS) only after the page has rendered the docked state: place again once that has happened
   const settle=[setTimeout(schedule,80),setTimeout(schedule,320)];
   page.addEventListener("scroll",schedule,{passive:true});
   window.addEventListener("resize",schedule);
   const observer=new ResizeObserver(schedule);
   observer.observe(page);
   document.querySelectorAll("[data-camera-slot]").forEach(slot=>observer.observe(slot));
   return ()=>{page.removeEventListener("scroll",schedule);window.removeEventListener("resize",schedule);observer.disconnect();cancelAnimationFrame(frame);clearTimeout(moving);settle.forEach(clearTimeout);clear();};
 },[compact]);
 function returnToCamera(){

   boundary.current?.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth",block:"start"});
   camera.current?.focus({preventScroll:true});
 }
 useEffect(()=>{if(cue && !matchMedia("(prefers-reduced-motion: reduce)").matches)camera.current?.animate([{outline:"3px solid var(--ui-info)"},{outline:"3px solid transparent"}],300)},[cue]);
 function debug(){
   if(socket?.readyState!==WebSocket.OPEN)return;
   const on=!requested;socket.send(JSON.stringify({type:"command",cmd:"debug",on}));setRequested(on);
 }
 useEffect(()=>{const key=(e: KeyboardEvent)=>{if(e.key.toLowerCase()==="d" && !e.repeat && !e.ctrlKey && !e.metaKey && !["SELECT","INPUT","TEXTAREA"].includes((e.target as HTMLElement)?.tagName))debug()};
 window.addEventListener("keydown",key);return ()=>window.removeEventListener("keydown",key)},[socket,requested]);
 return <div className="monitor-cameras">
   <div className="camera-anchor" ref={boundary}>
     <section ref={camera} tabIndex={-1} aria-label="Cabin cameras" className={"camera-pair"+(compact?" is-docked":"")}>
       {(["driver","passenger"] as const).map(seat=>{
         const label=seat==="driver"?"Driver":"Passenger";
         return <figure key={seat} className="seat-feed">
           <figcaption><span>{label}</span><small className="feed-live">LIVE</small></figcaption>
           <div className="camera-stage"><Feed src={videoOrigin+"/video/"+seat} label={"Camera · "+label}/></div>
         </figure>;
       })}
       {compact&&<button className="camera-return" onClick={returnToCamera} aria-label="Back to cameras">↗</button>}
     </section>
   </div>
   {<div className="camera-controls"><button disabled={!socket} onClick={debug}>Debug · D</button>{requested!==null&&socket&&<span>{requested?"Enable requested":"Disable requested"}</span>}</div>}
   <TripStrip trip={trip}/>
 </div>;
}
export function General({s}: StateProps & {points: SessionData["history"]}){
 const a=s.assessment??{},safe=s.safety??{},g=s.driver?.gaze??{},h=s.driver?.head??{},c=s.cause??{};
 return <section id="general"><small>DRIVER OVERVIEW</small><h2>{safe.monitoring_ok===false?"Monitoring interrupted":safe.alert?"Active alert":g.zone==="road"?"Eyes on the road":zones[g.zone??""]??"Gaze direction unknown"}</h2>
 {safe.alert&&<p role="alert">{words(typeof safe.alert === "object" ? safe.alert.text : safe.alert)}</p>}<p>{safe.level??"—"} · Risk {fmt(a.risk)}/3 · {fmt(s.trip?.speed_kmh," km/h")}</p>
 <div className="overview">
  <AttentionGauge value={a.attention}/>
  <div className="trends">
    <div className="mini-scores"><ScoreReading label="Fatigue" icon="fatigue" value={a.fatigue}/><ScoreReading label="Disengagement" icon="focus" value={a.disengagement}/></div>

  </div>
</div>
 <Detail title="Driver & context"><Rows items={[["Time on route",fmt(s.trip?.elapsed_min," min")],["Arrival in",fmt(s.trip?.eta_min," min")],["Road type",words(s.trip?.road)],["Next stop",s.trip?.next_poi?.name],["Distance to stop",fmt(s.trip?.next_poi?.dist_km," km")],["Last update",time(s.ts)],["Cause",words(c.label)],["Target / glances in 30 s",words(c.target)+" / "+fmt(c.glances_30s)],["Sources",c.sources?.join?.(", ")||"—"],["Cause confidence",fmt(c.conf,"%",100)],["Head pose · yaw / pitch / roll",[h.yaw,h.pitch,h.roll].map(v=>fmt(v,"°")).join(" / ")],["Head nodding",yes(h.nodding)],["Yawning",yes(s.driver?.yawn)],["Speaking",yes(s.driver?.speaking)],["Phone in use",yes(s.driver?.phone?.in_use)],["Phone source",words(s.driver?.phone?.source)],["Phone confidence",fmt(s.driver?.phone?.conf,"%",100)]]}/></Detail></section>;
}
export function Eyes({s,samples=[]}: StateProps & {samples?: Sample[]}){
 const rawEyes=s.driver?.eyes??{},g=s.driver?.gaze??{},crop=import.meta.env.VITE_EYE_STREAM_URL;
 const monitored=s.driver?.monitoring_ok!==false && s.perf?.cameras?.driver?.available!==false;
 const known=monitored && g.calibrated!==false && Boolean(zones[g.zone??""]);
 const e=monitored && rawEyes.reliable===true?rawEyes:{reliable:rawEyes.reliable,state:"UNKNOWN"};
 return <section id="eyes" className="optical"><small>EYE TRACKING</small><h2>Gaze</h2>
 <div className="ocular">{crop&&monitored&&e.reliable===true&&<Feed src={crop} label="Decupaj ocular"/>}
 <div><strong>{known?zones[g.zone!]:"Gaze direction unknown"}</strong><p>{e.reliable===false?"Unreliable eye signal":crop&&monitored&&e.reliable?"Live eye crop":"Eye crop unavailable"}</p></div></div>
 <Metrics items={[["PERCLOS · 60 s",fmt(e.perclos_60s,"%",100)],["Last blink",fmt(e.blink_ms," ms")],["Off road",known?fmt(g.off_road_ms," s",.001,2):"—"]]}/>
 <div className="fx-trends">
   <figure><figcaption>Eye opening (EAR)<b>{fmt(e.ear,"",1,2)}</b></figcaption><Spark values={samples.map(sample=>sample.ear)} label="Eye opening over the last minute"/></figure>
   <figure><figcaption>Off road<b>{known?fmt(g.off_road_ms," s",.001,1):"—"}</b></figcaption><Spark values={samples.map(sample=>sample.offRoad)} tone="warn" label="Off-road gaze time over the last minute"/></figure>
 </div>
 <Detail title="Eye signal quality"><Rows items={[["Relative opening (EAR)",fmt(e.ear,"",1,2)],["Tracked eye",({left:"Left",right:"Right"} as Record<string,string>)[e.eye_used??""]],["Reliable signal",yes(e.reliable)],["Gaze source",words(g.source)],["Zone confidence",known?fmt(g.conf,"%",100):"—"],["Short glances · 60 s",known?fmt(g.vats_60s):"—"],["Entropy · 60 s",known?fmt(g.entropy_60s," bit"):"—"],["Microsleep",yes(e.microsleep)],["Lap pattern (phone)",known?yes(g.lap_pattern):"—"],["Blink count",fmt(e.blink_count,"",1,0)],["Current closure",fmt(e.closed_ms," ms")],["Open-eye baseline",fmt(e.open_baseline,"",1,2)],["Blink rate",fmt(e.blink_rate," /min")],["Squinting",yes(e.squint)],["Eyelid state",words(e.state)],["Prolonged closure",yes(e.long_closure)]]}/></Detail></section>;
}
export function Reaction({s}: StateProps){
 const r=s.driver?.reaction??{},input=s.interaction?.last_input;
 return <Panel id="reaction" label="DRIVER INPUT" title="Response"><p>Last response / personal baseline</p>{Object.entries({visual:"Visual",verbal:"Verbal",gesture:"Gesture"}).map(([key,label])=>{
 const ms=r[`${key}_ms` as "visual_ms" | "verbal_ms" | "gesture_ms"],base=r.baseline_ms?.[key as "visual" | "verbal" | "gesture"],ratio=Number.isFinite(ms)&&typeof base === "number"&&base>0?ms!/base:null;
 const scale=Math.max(1,typeof ms==="number"&&Number.isFinite(ms)?ms:0,typeof base==="number"&&Number.isFinite(base)?base:0);
 return <div className="response" key={key}><span>{label}</span><strong className="ratio-reading">{ratio===null?"—":fmt(ratio,"×",1,2)}</strong><output>{fmt(ms," ms")} / {fmt(base," ms")}</output>
 <div className="response-comparison" aria-label={label+" · response / baseline"}>
   <span>Response<i>{Number.isFinite(ms)&&<b style={{width:Math.max(0,ms!)/scale*100+"%"}}/>}</i></span>
   <span>Baseline<i>{Number.isFinite(base)&&<b style={{width:Math.max(0,base!)/scale*100+"%"}}/>}</i></span>
 </div></div>;
 })}<Detail title="Responses & channels"><Rows items={[["Last channel",words(input?.channel)],["Response",words(input?.value)],["Time",time(input?.ts)],["Gesture",words(s.driver?.gesture)],["Head response",words(s.driver?.head?.answer)],["Missed responses",fmt(r.missed)],["Response rate · 10 min",fmt(r.response_rate_10min,"%",100)]]}/></Detail></Panel>
}
type View = "overview" | "history" | "signals" | "reaction" | "cabin" | "report" | "system" | "assistant" | "events";
const views: {id: View; label: string; icon: string}[] = [
 {id:"overview",label:"General",icon:"grid"},
 {id:"history",label:"Score history",icon:"pulse"},
 {id:"signals",label:"Semnale",icon:"eye"},
 {id:"reaction",label:"Response",icon:"pulse"},
 {id:"cabin",label:"Cabin",icon:"voice"},
 {id:"report",label:"Trip",icon:"route"},
 {id:"system",label:"System",icon:"pulse"},
 {id:"assistant",label:"Assistant",icon:"voice"},
 {id:"events",label:"Evenimente",icon:"route"}
];
export function Icon({name}: {name: string}) {
 const paths: Record<string, string> = {
  chart:"M3 4v16h18 M7 15l4-5 4 2 5-7",
  cabin:"M3 15l2-7h13l3 7v4H3z M4 14h16 M6 19v2m12-2v2",
  report:"M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8m-8 4h6",
  chip:"M6 6h12v12H6z M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4",
  journal:"M5 3h15v18H5z M3 7h4m-4 5h4m-4 5h4 M10 8h7m-7 5h7",
  sound:"M3 9h4l5-4v14l-5-4H3z M16 8q4 4 0 8 M19 5q7 7 0 14",
  grid:"M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  eye:"M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  voice:"M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5Z M5 11v1a7 7 0 0 0 14 0v-1 M12 19v3 M8 22h8",
  route:"M5 5h10a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h10 M5 2v6 M19 18v6",
  pulse:"M2 12h5l3-8 4 16 3-8h5",
  music:"M9 18V5l12-2v13 M9 8l12-2 M9 18a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Z M21 16a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Z",
  message:"M4 4h16v12H9l-5 4V4Z M8 8h8 M8 12h5",
  sliders:"M4 6h9 M17 6h3 M4 12h3 M11 12h9 M4 18h11 M19 18h1 M15 4v4 M9 10v4 M17 16v4"
 };
 return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]??paths.grid}/></svg>;
}
export default function App(){return <MotionConfig reducedMotion="user" transition={{type:"spring",bounce:0,visualDuration:.22}}><DriverApp/></MotionConfig>}
