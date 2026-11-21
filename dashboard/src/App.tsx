import {MotionConfig} from "motion/react";
import type {StateProps, SessionData, Trip} from "./types";
import React,{useState,useRef,useEffect} from "react";
import {videoOrigin} from "./session";
import {Panel,Metrics,Detail,Rows,fmt,words,time,yes} from "./Panels";

import "./design.css";
import "./obsidian.css";
import {DriverApp} from "./driver/DriverApp";
import {Optic} from "./Optic";
import {DataBars} from "./DataBars";

import {AttentionGauge,CameraStandby,ScoreReading,TripStrip} from "./Overview";
const zones: Record<string,string>={road:"Drum",passenger:"Pasager",lap:"Poală",mirror_left:"Oglinda stângă",mirror_right:"Oglinda dreaptă",mirror_rear:"Oglinda centrală",cluster:"Bord",infotainment:"Ecran",away:"În altă direcție",rear_seat:"Bancheta din spate"};
function Feed({src,label}: {src: string; label: string}){
 const [attempt,retry]=useState(0),[error,setError]=useState(false);
 useEffect(()=>setError(false),[src]);
 return error?<div className="feed-error">{label} · indisponibil <button onClick={()=>{retry(attempt+1);setError(false)}}>Reîncearcă</button></div>:
 <img key={attempt} src={src} alt={label} onError={()=>setError(true)}/>;
}
export function Cameras({live,socket,cue,trip,onLive,onDock}: {live: boolean; socket: SessionData["socket"]; cue: number; trip: Trip | undefined; onLive: () => void; onDock: (docked: boolean) => void}){
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
     <section ref={camera} tabIndex={-1} aria-label="Camere habitaclu" className={"camera-pair"+(compact?" is-docked":"")}>
       {(["driver","passenger"] as const).map(seat=>{
         const label=seat==="driver"?"Șofer":"Pasager";
         return <figure key={seat} className="seat-feed">
           <figcaption><span>{label}</span><small>{live?"LIVE":"SIMULAT"}</small></figcaption>
           <div className="camera-stage">{live?<Feed src={videoOrigin+"/video/"+seat} label={"Camera · "+label}/>:<CameraStandby onLive={onLive}/>}</div>
         </figure>;
       })}
       {compact&&<button className="camera-return" onClick={returnToCamera} aria-label="Revino la camere">↗</button>}
     </section>
   </div>
   {live&&<div className="camera-controls"><button disabled={!socket} onClick={debug}>Debug · D</button>{requested!==null&&socket&&<span>{requested?"Activare cerută":"Dezactivare cerută"}</span>}</div>}
   <TripStrip trip={trip}/>
 </div>;
}
export function General({s}: StateProps & {points: SessionData["history"]}){
 const a=s.assessment??{},safe=s.safety??{},g=s.driver?.gaze??{},h=s.driver?.head??{},c=s.cause??{};
 return <section id="general"><small>STARE GENERALĂ</small><h2>{safe.monitoring_ok===false?"Monitorizare întreruptă":safe.alert?"Alertă activă":g.zone==="road"?"Privirea pe drum":zones[g.zone??""]??"Direcție nedeterminată"}</h2>
 {safe.alert&&<p role="alert">{words(typeof safe.alert === "object" ? safe.alert.text : safe.alert)}</p>}<p>{safe.level??"—"} · Risc {fmt(a.risk)}/3 · {fmt(s.trip?.speed_kmh," km/h")}</p>
 <div className="overview">
  <AttentionGauge value={a.attention}/>
  <div className="trends">
    <div className="mini-scores"><ScoreReading label="Oboseală" icon="fatigue" value={a.fatigue}/><ScoreReading label="Dezinteres" icon="focus" value={a.disengagement}/></div>

  </div>
</div>
 <Detail title="Șofer și context"><Rows items={[["Timp pe traseu",fmt(s.trip?.elapsed_min," min")],["Până la destinație",fmt(s.trip?.eta_min," min")],["Tip drum",words(s.trip?.road)],["Următoarea oprire",s.trip?.next_poi?.name],["Distanță până la oprire",fmt(s.trip?.next_poi?.dist_km," km")],["Ultima stare",time(s.ts)],["Cauză",words(c.label)],["Țintă / priviri în 30 s",words(c.target)+" / "+fmt(c.glances_30s)],["Surse",c.sources?.join?.(", ")||"—"],["Încredere cauză",fmt(c.conf,"%",100)],["Poziție cap · yaw / pitch / roll",[h.yaw,h.pitch,h.roll].map(v=>fmt(v,"°")).join(" / ")],["Cădere de cap",yes(h.nodding)],["Căscat",yes(s.driver?.yawn)],["Vorbește",yes(s.driver?.speaking)],["Telefon folosit",yes(s.driver?.phone?.in_use)],["Sursă telefon",words(s.driver?.phone?.source)],["Încredere telefon",fmt(s.driver?.phone?.conf,"%",100)]]}/></Detail></section>;
}
export function Eyes({s,live}: StateProps & {live: boolean}){
 const rawEyes=s.driver?.eyes??{},g=s.driver?.gaze??{},crop=import.meta.env.VITE_EYE_STREAM_URL;
 const monitored=s.driver?.monitoring_ok!==false && s.perf?.cameras?.driver?.available!==false;
 const known=monitored && g.calibrated!==false && Boolean(zones[g.zone??""]);
 const e=monitored && rawEyes.reliable===true?rawEyes:{reliable:rawEyes.reliable,state:"UNKNOWN"};
 return <section id="eyes" className="optical"><small>ANALIZĂ OCULARĂ</small><h2>Privire</h2>
 <div className="ocular">{live&&crop&&monitored&&e.reliable===true?<Feed src={crop} label="Decupaj ocular"/>:!live&&e.reliable&&<Optic sideways={g.zone?.startsWith("mirror")}/>}
 <div><strong>{known?zones[g.zone!]:"Direcție nedeterminată"}</strong><p>{live?(e.reliable===false?"Semnal ocular nesigur":crop&&monitored&&e.reliable?"Decupaj ocular live":"Decupaj ocular indisponibil"):"Schemă ilustrativă · simulare"}</p></div></div>
 <Metrics items={[["PERCLOS · 60 s",fmt(e.perclos_60s,"%",100)],["Ultima clipire",fmt(e.blink_ms," ms")],["În afara drumului",known?fmt(g.off_road_ms," s",.001,2):"—"]]}/>
 <DataBars title="Închidere oculară · ultimele 60 s" maximum={100} items={[{label:"PERCLOS",value:typeof e.perclos_60s==="number"?e.perclos_60s*100:e.perclos_60s,unit:"%"}]}/>
 <Detail title="Calitatea semnalului ocular"><Rows items={[["Deschidere relativă (EAR)",fmt(e.ear,"",1,2)],["Ochi folosit",({left:"Stâng",right:"Drept"} as Record<string,string>)[e.eye_used??""]],["Semnal fiabil",yes(e.reliable)],["Sursa privirii",words(g.source)],["Încredere zonă",known?fmt(g.conf,"%",100):"—"],["Priviri scurte · 60 s",known?fmt(g.vats_60s):"—"],["Entropie · 60 s",known?fmt(g.entropy_60s," bit"):"—"],["Microsomn",yes(e.microsleep)],["Închidere curentă",fmt(e.closed_ms," ms")],["Referință ochi deschis",fmt(e.open_baseline,"",1,2)],["Frecvență clipire",fmt(e.blink_rate," /min")],["Ochi mijiți",yes(e.squint)],["Starea pleoapei",words(e.state)],["Închidere prelungită",yes(e.long_closure)]]}/></Detail></section>;
}
export function Reaction({s}: StateProps){
 const r=s.driver?.reaction??{},input=s.interaction?.last_input;
 return <Panel id="reaction" label="INPUT ȘOFER" title="Reacție"><p>Ultima reacție / referința personală</p>{Object.entries({visual:"Vizual",verbal:"Verbal",gesture:"Gest"}).map(([key,label])=>{
 const ms=r[`${key}_ms` as "visual_ms" | "verbal_ms" | "gesture_ms"],base=r.baseline_ms?.[key as "visual" | "verbal" | "gesture"],ratio=Number.isFinite(ms)&&typeof base === "number"&&base>0?ms!/base:null;
 const scale=Math.max(1,typeof ms==="number"&&Number.isFinite(ms)?ms:0,typeof base==="number"&&Number.isFinite(base)?base:0);
 return <div className="response" key={key}><span>{label}</span><strong className="ratio-reading">{ratio===null?"—":fmt(ratio,"×",1,2)}</strong><output>{fmt(ms," ms")} / {fmt(base," ms")}</output>
 <div className="response-comparison" aria-label={label+" · răspuns / referință"}>
   <span>Răspuns<i>{Number.isFinite(ms)&&<b style={{width:Math.max(0,ms!)/scale*100+"%"}}/>}</i></span>
   <span>Referință<i>{Number.isFinite(base)&&<b style={{width:Math.max(0,base!)/scale*100+"%"}}/>}</i></span>
 </div></div>;
 })}<Detail title="Răspunsuri și canale"><Rows items={[["Ultimul canal",words(input?.channel)],["Răspuns",words(input?.value)],["Ora",time(input?.ts)],["Gest",words(s.driver?.gesture)],["Răspuns din cap",words(s.driver?.head?.answer)],["Răspunsuri ratate",fmt(r.missed)],["Rată răspuns · 10 min",fmt(r.response_rate_10min,"%",100)]]}/></Detail></Panel>
}
type View = "overview" | "history" | "signals" | "reaction" | "cabin" | "report" | "system" | "assistant" | "events";
const views: {id: View; label: string; icon: string}[] = [
 {id:"overview",label:"General",icon:"grid"},
 {id:"history",label:"Evoluție scoruri",icon:"pulse"},
 {id:"signals",label:"Semnale",icon:"eye"},
 {id:"reaction",label:"Reacție",icon:"pulse"},
 {id:"cabin",label:"Cabină",icon:"voice"},
 {id:"report",label:"Călătorie",icon:"route"},
 {id:"system",label:"Sistem",icon:"pulse"},
 {id:"assistant",label:"Asistent",icon:"voice"},
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
  message:"M4 4h16v12H9l-5 4V4Z M8 8h8 M8 12h5"
 };
 return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]??paths.grid}/></svg>;
}
export default function App(){return <MotionConfig reducedMotion="user" transition={{type:"spring",bounce:0,visualDuration:.22}}><DriverApp/></MotionConfig>}
