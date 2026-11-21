import React,{useState,useRef,useEffect} from "react";
import {createRoot} from "react-dom/client";
import {useSession,videoOrigin} from "./session";
import {drawPortrait,drawHistory} from "./canvas";
import {Performance,Cabin,Scorecard,Metrics,Detail,Panel,Rows,fmt,words,time,yes} from "./Panels";
import {Assistant} from "./Assistant";
import "./monitor.css";

const zones={road:"Drum",passenger:"Pasager",lap:"Poală",mirror_left:"Oglinda stângă",mirror_right:"Oglinda dreaptă",mirror_rear:"Oglinda centrală",cluster:"Bord",infotainment:"Ecran",away:"În altă direcție",rear_seat:"Bancheta din spate"};
function History({points}){
 const ref=useRef(null);useEffect(()=>drawHistory(ref.current,points),[points]);
 return <canvas ref={ref} id="history" width="720" height="74" aria-label="Istoric atenție, oboseală și dezinteres"/>;
}
function Portrait(){
 const ref=useRef(null);useEffect(()=>drawPortrait(ref.current),[]);
 return <canvas ref={ref} width="600" height="420" aria-label="Portret sintetic al șoferului"/>;
}
function Feed({src,label}){
 const [attempt,retry]=useState(0),[error,setError]=useState(false);
 return error?<div className="feed-error">{label} · indisponibil <button onClick={()=>{retry(attempt+1);setError(false)}}>Reîncearcă</button></div>:
 <img key={attempt} src={src} alt={label} onError={()=>setError(true)}/>;
}
function Cameras({live,socket,cue}){
 const [passenger,showPassenger]=useState(false),[requested,setRequested]=useState(null);
 const camera=useRef(null);
 useEffect(()=>{if(cue && !matchMedia("(prefers-reduced-motion: reduce)").matches)camera.current.animate([{outline:"3px solid #24a393"},{outline:"3px solid transparent"}],300)},[cue]);
 function debug(){
   if(socket?.readyState!==WebSocket.OPEN)return;
   const on=!requested;socket.send(JSON.stringify({type:"command",cmd:"debug",on}));setRequested(on);
 }
 useEffect(()=>{const key=e=>{if(e.key.toLowerCase()==="d" && !e.repeat && !e.ctrlKey && !e.metaKey && !["SELECT","INPUT","TEXTAREA"].includes(e.target.tagName))debug()};
 window.addEventListener("keydown",key);return ()=>window.removeEventListener("keydown",key)},[socket,requested]);
 return <aside><section ref={camera} className="camera"><div className="camHead"><small>CAMERA 01</small><strong>Șofer</strong></div>
 {live?<Feed src={videoOrigin+"/video/driver"} label="Camera șoferului"/>:<Portrait/>}
 <div className="videoNote">{live?"Flux MJPEG local":"Simulat · portret sintetic"} {live&&<button disabled={!socket} onClick={debug}>Debug · D</button>}{requested!==null&&socket&&<span> · {requested?"Activare cerută":"Dezactivare cerută"}</span>}</div></section>
 <details onToggle={e=>showPassenger(e.currentTarget.open)}><summary>Camera pasagerului</summary>{passenger&&(live?<Feed src={videoOrigin+"/video/passenger"} label="Camera pasagerului"/>:<p>Indisponibilă în simulare</p>)}</details></aside>;
}
function General({s,points}){
 const a=s.assessment??{},safe=s.safety??{},g=s.driver?.gaze??{},h=s.driver?.head??{},c=s.cause??{};
 return <section id="general"><small>STARE GENERALĂ</small><h2>{safe.monitoring_ok===false?"Monitorizare întreruptă":safe.alert?"Alertă activă":g.zone==="road"?"Privirea pe drum":zones[g.zone]??"Direcție nedeterminată"}</h2>
 {safe.alert&&<p role="alert">{words(safe.alert?.text??safe.alert)}</p>}<p>{safe.level??"—"} · Risc {fmt(a.risk)}/3 · {fmt(s.trip?.speed_kmh," km/h")}</p>
 <Metrics items={[["Atenție",fmt(a.attention,"",100,0)],["Oboseală",fmt(a.fatigue,"",100,0)],["Dezinteres",fmt(a.disengagement,"",100,0)]]}/><History points={points}/><div className="caption">Scoruri din 100 · ultimele 120 de mostre</div>
 <Detail title="Șofer și context"><Rows items={[["Timp pe traseu",fmt(s.trip?.elapsed_min," min")],["Până la destinație",fmt(s.trip?.eta_min," min")],["Tip drum",words(s.trip?.road)],["Următoarea oprire",s.trip?.next_poi?.name],["Distanță până la oprire",fmt(s.trip?.next_poi?.dist_km," km")],["Ultima stare",time(s.ts)],["Cauză",words(c.label)],["Țintă / priviri în 30 s",words(c.target)+" / "+fmt(c.glances_30s)],["Surse",c.sources?.join?.(", ")||"—"],["Încredere cauză",fmt(c.conf,"%",100)],["Poziție cap · yaw / pitch / roll",[h.yaw,h.pitch,h.roll].map(v=>fmt(v,"°")).join(" / ")],["Cădere de cap",yes(h.nodding)],["Căscat",yes(s.driver?.yawn)],["Vorbește",yes(s.driver?.speaking)],["Telefon folosit",yes(s.driver?.phone?.in_use)],["Sursă telefon",words(s.driver?.phone?.source)],["Încredere telefon",fmt(s.driver?.phone?.conf,"%",100)]]}/></Detail></section>;
}
function Eyes({s,live}){
 const e=s.driver?.eyes??{},g=s.driver?.gaze??{},crop=import.meta.env.VITE_EYE_STREAM_URL;
 const known=Boolean(zones[g.zone]);
 return <section id="eyes" className="optical"><small>ANALIZĂ OCULARĂ</small><h2>Privire</h2>
 <div className="ocular">{live&&crop&&e.reliable===true?<Feed src={crop} label="Decupaj ocular"/>:!live&&e.reliable&&<div className="opticArt" aria-hidden="true"><i/></div>}
 <div><strong>{zones[g.zone]??"Direcție nedeterminată"}</strong><p>{live?(e.reliable===false?"Semnal ocular nesigur":crop&&e.reliable?"Decupaj ocular live":"Decupaj ocular indisponibil"):"Schemă ilustrativă · simulare"}</p></div></div>
 <Metrics items={[["PERCLOS · 60 s",fmt(e.perclos_60s,"%",100)],["Ultima clipire",fmt(e.blink_ms," ms")],["În afara drumului",known?fmt(g.off_road_ms," s",.001,2):"—"]]}/>
 <Detail title="Calitatea semnalului ocular"><Rows items={[["Deschidere relativă (EAR)",fmt(e.ear,"",1,2)],["Ochi folosit",({left:"Stâng",right:"Drept"})[e.eye_used]],["Semnal fiabil",yes(e.reliable)],["Sursa privirii",words(g.source)],["Încredere zonă",known?fmt(g.conf,"%",100):"—"],["Priviri scurte · 60 s",known?fmt(g.vats_60s):"—"],["Entropie · 60 s",fmt(g.entropy_60s)],["Microsomn",yes(e.microsleep)],["Închidere curentă",fmt(e.closed_ms," ms")],["Referință ochi deschis",fmt(e.open_baseline,"",1,2)],["Frecvență clipire",fmt(e.blink_rate," /min")],["Ochi mijiți",yes(e.squint)],["Starea pleoapei",words(e.state)],["Închidere prelungită",yes(e.long_closure)]]}/></Detail></section>;
}
function Reaction({s}){
 const r=s.driver?.reaction??{},input=s.interaction?.last_input;
 return <Panel id="reaction" label="INPUT ȘOFER" title="Reacție"><p>Ultima reacție / referința personală</p>{Object.entries({visual:"Vizual",verbal:"Verbal",gesture:"Gest"}).map(([key,label])=>{
 const ms=r[key+"_ms"],base=r.baseline_ms?.[key],ratio=Number.isFinite(ms)&&base>0?ms/base:null;
 return <div className="response" key={key}><span>{label}</span><div className="track" aria-hidden="true">{ratio!==null&&<i style={{left:Math.min(98,Math.max(0,ratio*50))+"%"}}/>}</div><output>{fmt(ms," ms")} / {fmt(base," ms")}</output></div>;
 })}<Detail title="Răspunsuri și canale"><Rows items={[["Ultimul canal",words(input?.channel)],["Răspuns",words(input?.value)],["Ora",time(input?.ts)],["Gest",words(s.driver?.gesture)],["Răspuns din cap",words(s.driver?.head?.answer)],["Răspunsuri ratate",fmt(r.missed)],["Rată răspuns · 10 min",fmt(r.response_rate_10min,"%",100)]]}/></Detail></Panel>
}
function Monitor({live,change}){
 const data=useSession(live),s=data.state,p=s.perf??{};
 const bar=useRef(null);
 useEffect(()=>{const obs=new ResizeObserver(()=>document.documentElement.style.setProperty("--sticky",bar.current.offsetHeight+10+"px"));obs.observe(bar.current);return ()=>obs.disconnect()},[]);
 return <><header><a href="#general" className="brand"><span className="mark">◒</span> DriveMate</a><label>Sursă <select value={live?"live":"demo"} onChange={e=>change(e.target.value==="live")}><option value="demo">Simulat</option><option value="live">Live · local</option></select></label></header><main>
 <div className="title"><div><small>DRIVEMATE / MONITORIZARE</small><h1>Starea șoferului</h1></div><span role="status">{data.connection}</span></div>
 <section className="perf" ref={bar}><a href="#performance">Performanță</a>{[["FPS șofer",fmt(p.cameras?.driver?.process_fps)],["FPS pasager",fmt(p.cameras?.passenger?.process_fps)],["Captură → publicare",fmt(p.e2e_ms_p95," ms")],["Ultima alarmă",fmt(s.safety?.alarm_ms_last??p.alarm_ms_last," ms")]].map(([k,v])=><span key={k}>{k} <b>{v}</b></span>)}</section>
 <div className="columns"><Cameras live={live} socket={data.socket} cue={data.cue}/><div className="content">
 <General s={s} points={data.history}/><nav aria-label="Module">{Object.entries({eyes:"Privire",reaction:"Reacție",cabin:"Cabină",assistant:"Asistent",scorecard:"Fișă"}).map(([id,name])=><a key={id} href={"#"+id}>{name}</a>)}</nav>
 <Eyes s={s} live={live}/><Reaction s={s}/><Cabin s={s}/><Assistant s={s} data={data} live={live}/><Scorecard s={s}/><Performance s={s}/></div></div></main></>
}
function App(){const [live,setLive]=useState(false);return <Monitor key={String(live)} live={live} change={setLive}/>}
createRoot(document.getElementById("root")).render(<App/>);
