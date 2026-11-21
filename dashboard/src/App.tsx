import {useDashboardEntrance} from "./useDashboardEntrance";
import {MotionConfig, motion, useReducedMotion} from "motion/react";
import type {StateProps, SessionData, Trip} from "./types";
import React,{useState,useRef,useEffect} from "react";
import {useSession,videoOrigin} from "./session";
import {drawHistory} from "./canvas";
import {Performance,Cabin,Scorecard,Metrics,Detail,Panel,Rows,fmt,words,time,yes} from "./Panels";
import {Assistant} from "./Assistant";

import "./design.css";
import {Optic} from "./Optic";
import {DataBars} from "./DataBars";
import {ScoreHistory} from "./ScoreHistory";
import {Simulator} from "./Simulator";
import type {SimulationSettings} from "./session";
import {useRouteSimulation} from "./route-simulation";

import {AttentionGauge,CameraStandby,RecentEvents,ScoreReading,TripStrip} from "./Overview";
const zones: Record<string,string>={road:"Drum",passenger:"Pasager",lap:"Poală",mirror_left:"Oglinda stângă",mirror_right:"Oglinda dreaptă",mirror_rear:"Oglinda centrală",cluster:"Bord",infotainment:"Ecran",away:"În altă direcție",rear_seat:"Bancheta din spate"};
function History({points}: {points: SessionData["history"]}){
 const ref=useRef<HTMLCanvasElement>(null), latest=useRef(points);
 useEffect(()=>{latest.current=points;drawHistory(ref.current,points)},[points]);
 useEffect(()=>{
  const canvas=ref.current;
  if(!canvas)return;
  const resize=new ResizeObserver(()=>drawHistory(canvas,latest.current));
  resize.observe(canvas);
  return ()=>resize.disconnect();
 },[]);
 return <canvas ref={ref} id="history" width="720" height="74" aria-label="Istoric atenție, oboseală și dezinteres"/>;
}
function Feed({src,label}: {src: string; label: string}){
 const [attempt,retry]=useState(0),[error,setError]=useState(false);
 useEffect(()=>setError(false),[src]);
 return error?<div className="feed-error">{label} · indisponibil <button onClick={()=>{retry(attempt+1);setError(false)}}>Reîncearcă</button></div>:
 <img key={attempt} src={src} alt={label} onError={()=>setError(true)}/>;
}
function Cameras({live,socket,cue,trip,onLive,onDock,mini=false,onExpand}: {live: boolean; socket: WebSocket | null; cue: number; trip: Trip | undefined; onLive: () => void; onDock: (docked: boolean) => void; mini?:boolean; onExpand?:()=>void}){
 const [passenger,showPassenger]=useState(false),[requested,setRequested]=useState<boolean | null>(null);
 const camera=useRef<HTMLElement>(null), boundary=useRef<HTMLDivElement>(null);
 const [compact,setCompact]=useState(false);
 useEffect(()=>setRequested(null),[socket]);
 useEffect(()=>{
   if(mini)return;
   const el=boundary.current;
   if(!el)return;
   const observer=new IntersectionObserver(([entry])=>{
     const docked=entry.boundingClientRect.bottom<(entry.rootBounds?.top??0);
     setCompact(docked);onDock(docked);
   },{threshold:0,root:el.closest(".dashboard")});
   observer.observe(el);
   return ()=>observer.disconnect();
 },[onDock,mini]);
 function returnToCamera(){
   if(onExpand){onExpand();return;}
   boundary.current?.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth",block:"start"});
   camera.current?.focus({preventScroll:true});
 }
 useEffect(()=>{if(cue && !matchMedia("(prefers-reduced-motion: reduce)").matches)camera.current?.animate([{outline:"3px solid #6699cd"},{outline:"3px solid transparent"}],300)},[cue]);
 function debug(){
   if(socket?.readyState!==WebSocket.OPEN)return;
   const on=!requested;socket.send(JSON.stringify({type:"command",cmd:"debug",on}));setRequested(on);
 }
 useEffect(()=>{const key=(e: KeyboardEvent)=>{if(e.key.toLowerCase()==="d" && !e.repeat && !e.ctrlKey && !e.metaKey && !["SELECT","INPUT","TEXTAREA"].includes((e.target as HTMLElement)?.tagName))debug()};
 window.addEventListener("keydown",key);return ()=>window.removeEventListener("keydown",key)},[socket,requested]);
 return <aside className={"camera-home"+(mini?" simulator-camera":"")} aria-label="Camere și traseu"><div ref={boundary} className="camera-placeholder"><section ref={camera} tabIndex={-1} className={"camera"+(compact||mini?" camera-docked":"")}><div className="camHead"><span className="camera-label">Camera șoferului</span><small>{live?"LIVE":"SIMULAT"}</small>{(compact||mini)&&<button className="camera-expand" onClick={returnToCamera} aria-label="Mărește și revino la camera principală" title="Revino la camera principală"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg></button>}</div>
 <div className="camera-stage">{live?<Feed src={videoOrigin+"/video/driver"} label="Camera șoferului"/>:<CameraStandby onLive={onLive}/>}</div>
 <div className="videoNote">{live?"Flux MJPEG local":"Flux video oprit în simulare"} {live&&<button disabled={!socket} onClick={debug}>Debug · D</button>}{requested!==null&&socket&&<span> · {requested?"Activare cerută":"Dezactivare cerută"}</span>}</div></section></div>
 {!mini&&<><TripStrip trip={trip}/><details onToggle={e=>showPassenger(e.currentTarget.open)}><summary>Camera pasagerului</summary>{passenger&&(live?<Feed src={videoOrigin+"/video/passenger"} label="Camera pasagerului"/>:<p>Indisponibilă în simulare</p>)}</details></>}</aside>;
}
export function General({s,points}: StateProps & {points: SessionData["history"]}){
 const a=s.assessment??{},safe=s.safety??{},g=s.driver?.gaze??{},h=s.driver?.head??{},c=s.cause??{};
 return <section id="general"><small>STARE GENERALĂ</small><h2>{safe.monitoring_ok===false?"Monitorizare întreruptă":safe.alert?"Alertă activă":g.zone==="road"?"Privirea pe drum":zones[g.zone??""]??"Direcție nedeterminată"}</h2>
 {safe.alert&&<p role="alert">{words(typeof safe.alert === "object" ? safe.alert.text : safe.alert)}</p>}<p>{safe.level??"—"} · Risc {fmt(a.risk)}/3 · {fmt(s.trip?.speed_kmh," km/h")}</p>
 <div className="overview">
  <AttentionGauge value={a.attention}/>
  <div className="trends">
    <div className="mini-scores"><ScoreReading label="Oboseală" icon="fatigue" value={a.fatigue}/><ScoreReading label="Dezinteres" icon="focus" value={a.disengagement}/></div>
    <div className="trend-chart"><strong className="chart-title">Evoluția scorurilor</strong><div className="chart-plot"><div className="chart-scale" aria-hidden="true"><span>100</span><span>50</span><span>0</span></div><History points={points}/></div><div className="legend"><span>Atenție</span><span>Oboseală</span><span>Dezinteres</span></div><div className="caption">{points.length ? "Istoric recent · maximum 120 de mostre" : "În așteptarea mostrelor"}</div></div>
  </div>
</div>
 <Detail title="Șofer și context"><Rows items={[["Timp pe traseu",fmt(s.trip?.elapsed_min," min")],["Până la destinație",fmt(s.trip?.eta_min," min")],["Tip drum",words(s.trip?.road)],["Următoarea oprire",s.trip?.next_poi?.name],["Distanță până la oprire",fmt(s.trip?.next_poi?.dist_km," km")],["Ultima stare",time(s.ts)],["Cauză",words(c.label)],["Țintă / priviri în 30 s",words(c.target)+" / "+fmt(c.glances_30s)],["Surse",c.sources?.join?.(", ")||"—"],["Încredere cauză",fmt(c.conf,"%",100)],["Poziție cap · yaw / pitch / roll",[h.yaw,h.pitch,h.roll].map(v=>fmt(v,"°")).join(" / ")],["Cădere de cap",yes(h.nodding)],["Căscat",yes(s.driver?.yawn)],["Vorbește",yes(s.driver?.speaking)],["Telefon folosit",yes(s.driver?.phone?.in_use)],["Sursă telefon",words(s.driver?.phone?.source)],["Încredere telefon",fmt(s.driver?.phone?.conf,"%",100)]]}/></Detail></section>;
}
export function Eyes({s,live}: StateProps & {live: boolean}){
 const e=s.driver?.eyes??{},g=s.driver?.gaze??{},crop=import.meta.env.VITE_EYE_STREAM_URL;
 const known=Boolean(zones[g.zone??""]);
 return <section id="eyes" className="optical"><small>ANALIZĂ OCULARĂ</small><h2>Privire</h2>
 <div className="ocular">{live&&crop&&e.reliable===true?<Feed src={crop} label="Decupaj ocular"/>:!live&&e.reliable&&<Optic sideways={g.zone?.startsWith("mirror")}/>}
 <div><strong>{zones[g.zone??""]??"Direcție nedeterminată"}</strong><p>{live?(e.reliable===false?"Semnal ocular nesigur":crop&&e.reliable?"Decupaj ocular live":"Decupaj ocular indisponibil"):"Schemă ilustrativă · simulare"}</p></div></div>
 <Metrics items={[["PERCLOS · 60 s",fmt(e.perclos_60s,"%",100)],["Ultima clipire",fmt(e.blink_ms," ms")],["În afara drumului",known?fmt(g.off_road_ms," s",.001,2):"—"]]}/>
 <DataBars title="Închidere oculară · ultimele 60 s" maximum={100} items={[{label:"PERCLOS",value:typeof e.perclos_60s==="number"?e.perclos_60s*100:e.perclos_60s,unit:"%"}]}/>
 <Detail title="Calitatea semnalului ocular"><Rows items={[["Deschidere relativă (EAR)",fmt(e.ear,"",1,2)],["Ochi folosit",({left:"Stâng",right:"Drept"} as Record<string,string>)[e.eye_used??""]],["Semnal fiabil",yes(e.reliable)],["Sursa privirii",words(g.source)],["Încredere zonă",known?fmt(g.conf,"%",100):"—"],["Priviri scurte · 60 s",known?fmt(g.vats_60s):"—"],["Entropie · 60 s",fmt(g.entropy_60s)],["Microsomn",yes(e.microsleep)],["Închidere curentă",fmt(e.closed_ms," ms")],["Referință ochi deschis",fmt(e.open_baseline,"",1,2)],["Frecvență clipire",fmt(e.blink_rate," /min")],["Ochi mijiți",yes(e.squint)],["Starea pleoapei",words(e.state)],["Închidere prelungită",yes(e.long_closure)]]}/></Detail></section>;
}
export function Reaction({s}: StateProps){
 const r=s.driver?.reaction??{},input=s.interaction?.last_input;
 return <Panel id="reaction" label="INPUT ȘOFER" title="Reacție"><p>Ultima reacție / referința personală</p>{Object.entries({visual:"Vizual",verbal:"Verbal",gesture:"Gest"}).map(([key,label])=>{
 const ms=r[`${key}_ms` as "visual_ms" | "verbal_ms" | "gesture_ms"],base=r.baseline_ms?.[key as "visual" | "verbal" | "gesture"],ratio=Number.isFinite(ms)&&typeof base === "number"&&base>0?ms!/base:null;
 return <div className="response" key={key}><span>{label}</span><div className="track" aria-hidden="true">{ratio!==null&&<motion.i layout="position" layoutDependency={ratio} transition={{type:"spring",bounce:0,visualDuration:.2}} style={{left:Math.min(98,Math.max(0,ratio*50))+"%"}}/>}</div><output>{fmt(ms," ms")} / {fmt(base," ms")}</output></div>;
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
function Icon({name}: {name: string}) {
 const paths: Record<string, string> = {
  grid:"M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  eye:"M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  voice:"M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5Z M5 11v1a7 7 0 0 0 14 0v-1 M12 19v3 M8 22h8",
  route:"M5 5h10a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h10 M5 2v6 M19 18v6",
  pulse:"M2 12h5l3-8 4 16 3-8h5"
 };
 return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]??paths.grid}/></svg>;
}
function Monitor({live,change}: {live: boolean; change: (live: boolean) => void}){
 const [simulation,setSimulation]=useState<SimulationSettings>({running:true,speed:118,rate:1,reset:0});
 const [page,setPage]=useState<"dashboard"|"simulator">(()=>location.hash.startsWith("#/simulator")?"simulator":"dashboard");
 const [sectionsOpen,setSectionsOpen]=useState(true);
 const data=useSession(live,simulation),s=data.state,p=s.perf??{};
 const routeSimulation=useRouteSimulation(simulation,()=>setSimulation(old=>({...old,running:false})));
 useEffect(()=>{
  const navigate=()=>setPage(location.hash.startsWith("#/simulator")?"simulator":"dashboard");
  window.addEventListener("hashchange",navigate);
  return ()=>window.removeEventListener("hashchange",navigate);
 },[]);
 const shell=useRef<HTMLDivElement>(null);
 useDashboardEntrance(shell);
 const [view,setView]=useState<View>("overview"),[compact,setCompact]=useState(false),[docked,setDocked]=useState(false),[sidebarCollapsed,setSidebarCollapsed]=useState(false);
 const reduced=useReducedMotion(),bar=useRef<HTMLElement>(null),tabButtons=useRef<(HTMLButtonElement | null)[]>([]);
 const alarm=s.safety?.alarm_ms_last??p.alarm_ms_last;
 const alert=s.safety?.alert;
 useEffect(()=>{
  const el=bar.current;if(!el)return;
  const obs=new ResizeObserver(()=>document.documentElement.style.setProperty("--sticky",el.offsetHeight+12+"px"));
  obs.observe(el);return ()=>obs.disconnect();
 },[]);
 function selectView(next: View){
  setView(next);
  const destinations={overview:"camera-overview",history:"score-history",signals:"eyes",reaction:"reaction",cabin:"cabin",report:"scorecard",system:"performance",assistant:"assistant",events:"recent-events"};
  const scroll=()=>document.getElementById(destinations[next])?.scrollIntoView({behavior:reduced?"instant":"smooth",block:"start"});
  if(page!=="dashboard"){navigatePage("dashboard");requestAnimationFrame(scroll)}
  else scroll();
 }
 function navigatePage(next: "dashboard"|"simulator"){
  setPage(next);location.hash="/"+next;
  shell.current?.scrollTo({top:0,behavior:"instant"});
 }
 const submenuVisible=sectionsOpen&&!sidebarCollapsed;
 const navTransition={type:"spring" as const,bounce:0,visualDuration:reduced?0:.28};
 const navigation=(<nav className="page-nav" aria-label="Pagini">
  <div className="page-nav-group">
   <motion.div layout="position" layoutDependency={submenuVisible} transition={navTransition} className={"page-nav-row"+(page==="dashboard"?" page-current":"")}>
    {page==="dashboard"&&<motion.span className="page-active" layoutId="page-indicator" transition={navTransition}/>}
    <motion.button className="page-link" title="Dashboard" aria-current={page==="dashboard"?"page":undefined} whileHover={reduced?undefined:{x:2}} whileTap={reduced?undefined:{scale:.97}} onClick={()=>{navigatePage("dashboard");setSectionsOpen(true)}}><Icon name="grid"/><span>Dashboard</span></motion.button>
    <motion.button className="sections-toggle" aria-label={sectionsOpen?"Ascunde secțiunile Dashboard":"Arată secțiunile Dashboard"} aria-expanded={submenuVisible} aria-controls="dashboard-sections" onClick={()=>{setSectionsOpen(!sectionsOpen);if(sidebarCollapsed)setSidebarCollapsed(false)}}><motion.svg animate={{rotate:submenuVisible?180:0}} transition={navTransition} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m6 9 6 6 6-6"/></motion.svg></motion.button>
   </motion.div>
   <motion.div id="dashboard-sections" className="nav-submenu" aria-hidden={!submenuVisible} inert={!submenuVisible} initial={false}
    animate={submenuVisible?"expanded":"collapsed"}
    variants={{
     expanded:{height:"auto",opacity:1,transition:{height:{duration:reduced?0:.28},opacity:{duration:reduced?0:.16},delayChildren:reduced?0:.03,staggerChildren:reduced?0:.022}},
     collapsed:{height:0,opacity:0,transition:{duration:reduced?0:.18}}
    }}>
   <div className="section-nav" aria-label="Secțiuni dashboard">{views.map((item,i)=><motion.button key={item.id} variants={{expanded:{opacity:1,x:0},collapsed:{opacity:0,x:reduced?0:-8}}} transition={{duration:reduced?0:.16}} ref={el=>{tabButtons.current[i]=el}} aria-pressed={page==="dashboard"&&view===item.id} onClick={()=>{
    selectView(item.id);
   }} onKeyDown={e=>{
    if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Home","End"].includes(e.key))return;e.preventDefault();
    const next=e.key==="Home"?0:e.key==="End"?views.length-1:(i+(e.key==="ArrowRight"||e.key==="ArrowDown"?1:-1)+views.length)%views.length;
    selectView(views[next].id);tabButtons.current[next]?.focus();
   }} title={item.label} aria-label={item.label} whileHover={reduced?undefined:{x:3}} whileTap={reduced?undefined:{scale:.97}}>{page==="dashboard"&&view===item.id&&<motion.span className="nav-active" layoutId="section-indicator" transition={navTransition}/>}<Icon name={item.icon}/><span>{item.label}</span></motion.button>)}</div></motion.div>
  </div>
  <motion.div layout="position" layoutDependency={submenuVisible} transition={navTransition} className={"page-nav-row"+(page==="simulator"?" page-current":"")}>{page==="simulator"&&<motion.span className="page-active" layoutId="page-indicator" transition={navTransition}/>}<motion.button className="page-link" title="Simulator" aria-current={page==="simulator"?"page":undefined} whileHover={reduced?undefined:{x:2}} whileTap={reduced?undefined:{scale:.97}} onClick={()=>navigatePage("simulator")}><Icon name="pulse"/><span>Simulator</span></motion.button></motion.div>
 </nav>);
 return <div ref={shell} className={"dashboard"+(compact?" density-compact":"")+(page==="simulator"||docked?" has-camera-dock":"")+(sidebarCollapsed?" sidebar-collapsed":"")}>
 <a className="skip-link" href="#workspace">Sari la conținut</a>
 <header className="app-header">
  <div className="sidebar-brand"><a href="#workspace" className="brand" aria-label="DriveMate · General" onClick={()=>selectView("overview")}><span className="road-mark" aria-hidden="true"><i/><i/></span><span className="brand-label">DriveMate</span></a><button className="nav-collapse" onClick={()=>setSidebarCollapsed(!sidebarCollapsed)} aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed?"Extinde navigarea":"Restrânge navigarea"} title={sidebarCollapsed?"Extinde navigarea":"Restrânge navigarea"}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d={sidebarCollapsed?"m9 5 7 7-7 7":"m15 5-7 7 7 7"}/></svg></button></div>
  {navigation}
  <div className="header-meta"><div className="sidebar-session"><span className="session-dot" aria-hidden="true"/><span>{data.connection}</span></div><label className="source-select"><span>Sursă</span><select aria-label="Sursa datelor" title="Sursa datelor" value={live?"live":"demo"} onChange={e=>change(e.target.value==="live")}><option value="demo">Simulat</option><option value="live">Live · local</option></select></label><button className="density-button" aria-label="Mod compact" aria-pressed={compact} onClick={()=>setCompact(!compact)} title="Schimbă densitatea cardurilor"><Icon name="grid"/><span>Mod compact</span></button></div>
 </header>
 <main id="workspace">
 {page==="dashboard"?<>
  <div className="title"><div className="title-copy"><h1>Monitorizare șofer</h1><p>Ultima actualizare <time>{time(s.ts)}</time></p></div><span className={"status-pill "+(live && data.connection!=="Live · conectat"?"waiting":"")} role="status">{data.connection}</span></div>
  {(alert||s.safety?.monitoring_ok===false)&&<div className="safety-banner" role="alert"><Icon name="pulse"/><strong>{s.safety?.monitoring_ok===false?"Monitorizare întreruptă":typeof alert==="object"?alert?.text??"Alertă activă":alert}</strong><span>Verifică starea șoferului.</span></div>}
  <section className="perf" ref={bar} aria-label="Performanță în timp real">
   <button className="perf-title" onClick={()=>selectView("system")}><Icon name="pulse"/><span>Performanță</span></button>
   {[["FPS șofer",fmt(p.cameras?.driver?.process_fps)],["FPS pasager",fmt(p.cameras?.passenger?.process_fps)],["Captură → publicare · p95",fmt(p.e2e_ms_p95," ms")]].map(([k,v])=><div className="perf-reading" key={k}><span>{k}</span><b>{v}</b></div>)}
   <div className={"perf-reading alarm-reading "+(typeof alarm==="number"&&alarm>=300?"alarm-slow":"")}><span>Ultima alarmă <small>{typeof alarm !== "number" ? "FĂRĂ MĂSURARE" : alarm >= 300 ? "ȚINTĂ RATATĂ" : "ÎN ȚINTĂ"} · &lt;300 MS</small></span><b>{fmt(alarm," ms")}</b></div>
  </section>
  <div className="columns" id="camera-overview">
   <Cameras live={live} socket={data.socket} cue={data.cue} trip={s.trip} onLive={()=>change(true)} onDock={setDocked}/>
   <div className="content">
    <General s={s} points={data.history}/>
   </div>
  </div>
  <div className="expanded-sections content" aria-label="Analiză detaliată">
   <div className="section-heading"><small>ANALIZĂ ÎN TIMP REAL</small><h2>Dincolo de primul ecran</h2><p>Semnale, context și performanță pe parcursul călătoriei.</p></div>
   <ScoreHistory points={data.history}/>
   <div className="signal-sections"><Eyes s={s} live={live}/><Reaction s={s}/></div>
   <Cabin s={s}/>
   <Scorecard s={s}/>
   <Performance s={s}/>
   <Assistant s={s} data={data} live={live}/>
   <RecentEvents events={data.log}/>
  </div>
  </>:<><div className="title"><div className="title-copy"><h1>Simulator</h1><p>Adaugă opriri pe hartă și simulează deplasarea mașinii.</p></div></div><Cameras mini live={live} socket={data.socket} cue={data.cue} trip={s.trip} onLive={()=>change(true)} onDock={setDocked} onExpand={()=>navigatePage("dashboard")}/><Simulator data={data} settings={simulation} onChange={setSimulation} routeSimulation={routeSimulation}/></>}
  <footer className="dashboard-footer"><span>DriveMate · AI driver copilot</span><span>{live?"Date primite de la core":"Date sintetice · mod demonstrativ"} · istoric de 120 de mostre</span></footer>
 </main></div>;
}
export default function App(){const [live,setLive]=useState(false);return <MotionConfig reducedMotion="user" transition={{type:"spring",bounce:0,visualDuration:.22}}><Monitor live={live} change={setLive}/></MotionConfig>}
