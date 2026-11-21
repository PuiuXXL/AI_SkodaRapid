import type { ReactNode } from "react";
import type { StateProps, RowsData, Reading } from "./types";
import React,{createContext,useContext,useId,useState} from "react";
import {motion,useReducedMotion} from "motion/react";
import {DataBars} from "./DataBars";
import {Flag,RangeBars,Ring,Spark,StackBar} from "./charts";
import type {Sample} from "./telemetry";
import {integrationNames,integrationStates,label,monitoringReasons,phoneUsage,postures,seats} from "./labels";
export function fmt(value: Reading | undefined, unit="", factor=1, digits=1){
  return Number.isFinite(value)? (value!*factor).toLocaleString("ro-RO",{maximumFractionDigits:digits})+unit:"—";
}
export const yes=(value: boolean | undefined)=>value===true?"Da":value===false?"Nu":"—";
export const time=(value: Reading | undefined)=>Number.isFinite(value)?new Date(value!*1000).toLocaleTimeString("ro-RO"):"—";
export const words=(v: unknown)=> typeof v==="string"?v.replaceAll("_"," "):typeof v==="number"?String(v):"—";
export function Metrics({items}: {items: RowsData}){return <div className="scores">{items.map(([k,v])=><span key={k}>{k}<b>{v??"—"}</b></span>)}</div>}
export function Rows({items}: {items: RowsData}){return <dl>{items.map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v??"—"}</dd></div>)}</dl>}
export const InlineDetails=createContext(false);
export function Detail({title,children}: {title: string; children: ReactNode}){
 const [open,setOpen]=useState(false), id=useId(), reduced=useReducedMotion();
 const inline=useContext(InlineDetails);
 if(inline)return <div className="inline-detail"><h3>{title}</h3>{children}</div>;
 return <div className="disclosure">
   <button className="disclosure-trigger" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(!open)}>
     {title}<span aria-hidden="true">+</span>
   </button>
   <motion.div id={id} initial={false} animate={{height:open?"auto":0,opacity:open?1:0}}
     transition={{duration:reduced?0:.18,ease:[.22,.72,.2,1]}} aria-hidden={!open} inert={!open} className="disclosure-body">
     {children}
   </motion.div>
 </div>;
}
export function Panel({id,label,title,children}: {id: string; label: string; title: string; children: ReactNode}){return <section id={id}><small>{label}</small><h2>{title}</h2>{children}</section>}

export function VisionDiagnostics({s,connection}: StateProps & {connection:string}){
 const driver=s.driver, camera=s.perf?.cameras?.driver;
 const tracked=driver?.monitoring_ok===true && camera?.available!==false;
 return <Panel id="vision" label="DIAGNOSTIC LIVE" title="Semnalul camerei șoferului">
   <Metrics items={[
     ["Conexiune Core",connection],
     ["Cadru disponibil",yes(camera?.available)],
     ["Vârsta cadrului la publicare",fmt(camera?.age_ms," ms")],
   ]}/>
   <Rows items={[
     ["Monitorizare",driver?.monitoring_ok===true?"Activă":driver?.monitoring_ok===false?"Întreruptă":"—"],
     ["Motiv raportat",driver?.monitoring_reason],
     ["Avertismente",driver?.monitoring_warnings?.join(", ")||"—"],
     ["Mod cameră",words(driver?.camera_mode)],
     ["Încredere față",fmt(driver?.face_conf,"%",100)],
     ["Calibrare privire",tracked?yes(driver?.gaze?.calibrated):"—"],
     ["Timp în afara drumului · ultimele 60 s",tracked && driver?.gaze?.calibrated?fmt(driver.gaze.off_road_60s_ms," s",.001,2):"—"],
     ["Rezultate pierdute",fmt(camera?.dropped_results)],
   ]}/>
 </Panel>;
}

export function Performance({s,samples=[]}: StateProps & {samples?: Sample[]}){
 const p=s.perf??{}, cameras=p.cameras??{};
 const models={face_driver:"Față șofer",face_passenger:"Față pasager",pose:"Postură",phone:"Telefon",gesture:"Gest",sface:"Identitate"};
 const modelRows: RowsData=Object.entries(models).map(([k,name])=>[name,fmt(p[`${k}_ms_p50`]," ms")+" / "+fmt(p[`${k}_ms_p95`]," ms")]);
 return <Panel id="performance" label="TELEMETRIE" title="Performanța sistemului">
 <Metrics items={[["CPU",fmt(p.cpu,"%")],["RAM",fmt(p.ram_mb," MB")],["GPU",fmt(p.gpu,"%")]]}/>
 <div className="fx-resources">
   <Ring value={p.cpu} max={100} size={84} label="Procesor"><b>{fmt(p.cpu,"%",1,0)}</b><small>CPU</small></Ring>
   <Ring value={p.gpu} max={100} size={84} tone="soft" label="Placă grafică"><b>{fmt(p.gpu,"%",1,0)}</b><small>GPU</small></Ring>
   <figure><figcaption>Captură → publicare · p95<b>{fmt(p.e2e_ms_p95," ms",1,0)}</b></figcaption><Spark values={samples.map(sample=>sample.e2e)} tone={typeof p.e2e_ms_p95==="number"&&p.e2e_ms_p95>150?"warn":"ink"} label="Latența cap-coadă în ultimul minut"/><small>țintă sub 150 ms{typeof p.degrade_level==="number"&&p.degrade_level>0?" · degradare treapta "+p.degrade_level:""}</small></figure>
 </div>
 <DataBars title="Procesare camere" items={[{label:"Șofer",value:cameras.driver?.process_fps,unit:" fps"},{label:"Pasager",value:cameras.passenger?.process_fps,unit:" fps"}]}/>
 <Detail title="Camere și latențe"><Rows items={[
 ...["driver","passenger"].map<[string, ReactNode]>((c,i)=>[i?"Cameră pasager":"Cameră șofer",fmt(cameras[c]?.capture_fps)+" fps captură · "+fmt(cameras[c]?.process_fps)+" fps procesare · "+fmt(cameras[c]?.dropped_frames)+" pierdute"]),
 ["Captură → publicare (p95)",fmt(p.e2e_ms_p95," ms")],["Alarmă · țintă <300 ms",fmt(s.safety?.alarm_ms_last??p.alarm_ms_last," ms")],
 ...Object.entries({llm_ttft_ms:"LLM · primul token",llm_total_ms:"LLM · total",stt_final_ms:"Voce → text final",tts_first_audio_ms:"Text → primul sunet",msg_to_voice_ms:"Mesaj → voce"}).map<[string, ReactNode]>(([k,v])=>[v,fmt(p[k as "llm_ttft_ms" | "llm_total_ms" | "stt_final_ms" | "tts_first_audio_ms" | "msg_to_voice_ms"]," ms")])]}/></Detail>
 <Detail title="Latențe pe etape · p50 / p95"><RangeBars items={Object.entries(p.stages_ms??{}).flatMap(([camera,stages])=>Object.entries(stages??{}).map(([stage,times])=>({label:(camera==="driver"?"Șofer":camera==="passenger"?"Pasager":camera)+" · "+stage.replaceAll("_"," "),lo:times?.p50,hi:times?.p95}))).sort((a,b)=>(b.hi??0)-(a.hi??0)).slice(0,8)}/></Detail>
 <Detail title="Integrări"><div className="fx-flags">{Object.entries(s.integrations??{}).map(([name,state])=><span key={name} className={"fx-flag"+(state==="ok"?" is-on tone-ok":state==="down"?" is-on tone-danger":"")}>{label(integrationNames,name)}<b>{label(integrationStates,state)}</b></span>)}{!s.integrations&&<p className="fx-empty">Starea integrărilor vine de la core, în Live.</p>}</div></Detail>
 <Detail title="Modele · p50 / p95"><Rows items={modelRows}/></Detail></Panel>
}

export function Cabin({s}: StateProps){
 const people=Array.isArray(s.occupants)?s.occupants:null,msg=Array.isArray(s.messages)?s.messages:null,rem=Array.isArray(s.reminders)?s.reminders:null;
 return <Panel id="cabin" label="LA BORD" title="Cabină și telefon"><Metrics items={[
 ["Ocupanți",fmt(people?.length)],["Telefon conectat",yes(s.phone?.connected)],["Mesaje în așteptare",fmt(msg?.filter(m=>["pending","deferred"].includes(m.state??"")).length)]]}/>
 <DataBars title="Telefon și audio" maximum={100} items={[{label:"Baterie",value:s.phone?.battery,unit:"%"},{label:"Volum",value:typeof s.media?.volume==="number"?s.media.volume*100:s.media?.volume,unit:"%"}]}/>
 <Detail title="Ocupanți și conversație"><div className="fx-people">{people?.map((p,i)=><div key={p.id??i} className="fx-person"><span aria-hidden="true">{(p.profile??"?").slice(0,1).toUpperCase()}</span><div><strong>{p.profile??"Profil necunoscut"}</strong><small>{label(seats,p.seat)} · {p.source==="declared"?"declarat":"văzut de cameră"}{p.role==="child"?" · copil":""}{typeof p.profile_score==="number"?" · potrivire "+fmt(p.profile_score,"%",100,0):""}</small></div></div>)}</div>
 <div className="fx-flags"><Flag label="Pasager prezent" on={s.passenger?.present}/><Flag label="Treaz" on={s.passenger?.awake}/><Flag label="Vorbește" on={s.passenger?.speaking}/><Flag label="Telefon în mână" on={s.passenger?.holding_phone} tone="warn"/><Flag label="Conversație" on={s.conversation}/></div>
 <Rows items={[["Ochi închiși · pasager",fmt(s.passenger?.eyes_closed_s," s")],["Gest pasager",words(s.passenger?.gesture)],["Răspuns din cap · pasager",s.passenger?.answer==="yes"?"Da":s.passenger?.answer==="no"?"Nu":"—"],["Cameră pasager",s.passenger?.monitoring_ok===false?label(monitoringReasons,s.passenger.monitoring_reason??"face_lost"):s.passenger?.monitoring_ok===true?"Activă":"—"],["Telefon șofer",s.driver?.phone?.in_use?label(phoneUsage,s.driver.phone.usage??"visible"):s.driver?.phone?.foreign_seen?"Văzut la pasager":yes(s.driver?.phone?.in_use)],["Postură șofer",Object.entries(s.driver?.posture??{}).filter(([,on])=>on).map(([name])=>label(postures,name)).join(", ")||(s.driver?.posture?"Normală":"—")]]}/></Detail>
 <Detail title="Mesaje, muzică și mementouri"><Rows items={[["Contact de încredere",s.safe_contact?.name],["Contact configurat",yes(s.safe_contact?.configured)],["Acord notificare",yes(s.safe_contact?.consent)],["Ultima notificare",time(s.safe_contact?.notified_ts)],["Apel în curs",s.call?words((s.call as {state?: unknown}).state??"activ"):s.call===null?"Nu":"—"],["Redare activă",yes(s.media?.playing)],["Piesă",s.media?.title],["Motivul alegerii",words(s.media?.reason)],["Potrivită pentru copii",s.media?.playing?yes(s.media?.kid_safe):"—"]]}/>
 <h3>Mesaje</h3>{msg?.length?msg.map((m,i)=><p key={m.id??i}>{m.from} · {m.app} · {words(m.state)} {m.deferred_reason&&"· "+words(m.deferred_reason)}</p>):<p>{msg?"Niciun mesaj":"—"}</p>}
 <h3>Mementouri</h3>{rem?.length?rem.map((r,i)=><p key={r.id??i}>{r.task} · {words(r.state)} · {words(r.trigger?.category)}</p>):<p>{rem?"Niciun memento":"—"}</p>}</Detail></Panel>
}

export function Scorecard({s}: StateProps){
 const c=s.scorecard??{};
 return <Panel id="scorecard" label="REZULTATE" title="Fișa călătoriei"><Metrics items={[["Alerte prag simplu",fmt(s.ab?.naive_alerts)],["Alerte DriveMate",fmt(s.ab?.our_alerts)],["Concentrare maximă",fmt(c.longest_focus_min," min")]]}/>
 <DataBars title="Comparația alertelor" items={[{label:"Prag simplu",value:s.ab?.naive_alerts},{label:"DriveMate",value:s.ab?.our_alerts}]}/>
 <DataBars title="Rezultatul sugestiilor" items={[{label:"Acceptate",value:c.suggestions_accepted},{label:"Respinse",value:c.suggestions_rejected},{label:"Mementouri rezolvate",value:c.reminders_done}]}/>
 <figure className="fx-block"><figcaption>Sugestii · acceptate față de respinse</figcaption><StackBar label="Sugestii acceptate și respinse" parts={[{label:"Acceptate",value:c.suggestions_accepted??0,tone:"ok"},{label:"Respinse",value:c.suggestions_rejected??0,tone:"soft"}]}/></figure>
 <Rows items={[["Mesaje fără mâini",fmt(c.hands_free_messages)],["Atingeri telefon",fmt(c.phone_touches)],["Metri orbi · episod / total",fmt(s.blind_m?.last," m")+" / "+fmt(s.blind_m?.trip," m")],["Sugestii acceptate / respinse",fmt(c.suggestions_accepted)+" / "+fmt(c.suggestions_rejected)],["Mementouri rezolvate",fmt(c.reminders_done)],["Ultima intervenție",words(s.intervention?.last)],["Efect în această sesiune",fmt(s.intervention?.effect_pct,"%")]]}/>
 </Panel>
}
