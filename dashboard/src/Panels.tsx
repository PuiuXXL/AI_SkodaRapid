import type { ReactNode } from "react";
import type { StateProps, RowsData, Reading } from "./types";
import React,{useId,useState} from "react";
import {motion,useReducedMotion} from "motion/react";
import {DataBars} from "./DataBars";
export function fmt(value: Reading | undefined, unit="", factor=1, digits=1){
  return Number.isFinite(value)? (value!*factor).toLocaleString("ro-RO",{maximumFractionDigits:digits})+unit:"—";
}
export const yes=(value: boolean | undefined)=>value===true?"Da":value===false?"Nu":"—";
export const time=(value: Reading | undefined)=>Number.isFinite(value)?new Date(value!*1000).toLocaleTimeString("ro-RO"):"—";
export const words=(v: unknown)=> typeof v==="string"?v.replaceAll("_"," "):typeof v==="number"?String(v):"—";
export function Metrics({items}: {items: RowsData}){return <div className="scores">{items.map(([k,v])=><span key={k}>{k}<b>{v??"—"}</b></span>)}</div>}
export function Rows({items}: {items: RowsData}){return <dl>{items.map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v??"—"}</dd></div>)}</dl>}
export function Detail({title,children}: {title: string; children: ReactNode}){
 const [open,setOpen]=useState(false), id=useId(), reduced=useReducedMotion();
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

export function Performance({s}: StateProps){
 const p=s.perf??{}, cameras=p.cameras??{};
 const models={face_driver:"Față șofer",face_passenger:"Față pasager",pose:"Postură",phone:"Telefon",gesture:"Gest",sface:"Identitate"};
 const modelRows: RowsData=Object.entries(models).map(([k,name])=>[name,fmt(p[`${k}_ms_p50`]," ms")+" / "+fmt(p[`${k}_ms_p95`]," ms")]);
 for(const [camera,stages] of Object.entries(p.stages_ms??{}))
   for(const [stage,times] of Object.entries(stages??{}))
     modelRows.push([camera+" · "+stage,fmt(times?.p50," ms")+" / "+fmt(times?.p95," ms")]);
 return <Panel id="performance" label="TELEMETRIE" title="Performanța sistemului">
 <Metrics items={[["CPU",fmt(p.cpu,"%")],["RAM",fmt(p.ram_mb," MB")],["GPU",fmt(p.gpu,"%")]]}/>
 <DataBars title="Utilizarea resurselor" maximum={100} items={[{label:"CPU",value:p.cpu,unit:"%"},{label:"GPU",value:p.gpu,unit:"%"}]}/>
 <DataBars title="Procesare camere" items={[{label:"Șofer",value:cameras.driver?.process_fps,unit:" fps"},{label:"Pasager",value:cameras.passenger?.process_fps,unit:" fps"}]}/>
 <Detail title="Camere și latențe"><Rows items={[
 ...["driver","passenger"].map<[string, ReactNode]>((c,i)=>[i?"Cameră pasager":"Cameră șofer",fmt(cameras[c]?.capture_fps)+" fps captură · "+fmt(cameras[c]?.process_fps)+" fps procesare · "+fmt(cameras[c]?.dropped_frames)+" pierdute"]),
 ["Captură → publicare (p95)",fmt(p.e2e_ms_p95," ms")],["Alarmă · țintă <300 ms",fmt(s.safety?.alarm_ms_last??p.alarm_ms_last," ms")],
 ...Object.entries({llm_ttft_ms:"LLM · primul token",llm_total_ms:"LLM · total",stt_final_ms:"Voce → text final",tts_first_audio_ms:"Text → primul sunet",msg_to_voice_ms:"Mesaj → voce"}).map<[string, ReactNode]>(([k,v])=>[v,fmt(p[k as "llm_ttft_ms" | "llm_total_ms" | "stt_final_ms" | "tts_first_audio_ms" | "msg_to_voice_ms"]," ms")])]}/></Detail>
 <Detail title="Modele · p50 / p95"><Rows items={modelRows}/></Detail></Panel>
}

export function Cabin({s}: StateProps){
 const people=Array.isArray(s.occupants)?s.occupants:null,msg=Array.isArray(s.messages)?s.messages:null,rem=Array.isArray(s.reminders)?s.reminders:null;
 return <Panel id="cabin" label="LA BORD" title="Cabină și telefon"><Metrics items={[
 ["Ocupanți",fmt(people?.length)],["Telefon conectat",yes(s.phone?.connected)],["Mesaje în așteptare",fmt(msg?.filter(m=>["pending","deferred"].includes(m.state??"")).length)]]}/>
 <DataBars title="Telefon și audio" maximum={100} items={[{label:"Baterie",value:s.phone?.battery,unit:"%"},{label:"Volum",value:typeof s.media?.volume==="number"?s.media.volume*100:s.media?.volume,unit:"%"}]}/>
 <Detail title="Ocupanți și conversație">{people?.map((p,i)=><p key={p.id??i}><strong>{p.profile??"Profil necunoscut"}</strong> · {words(p.seat)} · {words(p.source)} · {words(p.role)}</p>)}
 <Rows items={[["Pasager prezent",yes(s.passenger?.present)],["Treaz",yes(s.passenger?.awake)],["Vorbește",yes(s.passenger?.speaking)],["Telefon în mână",yes(s.passenger?.holding_phone)],["Conversație",yes(s.conversation)],["Gest pasager",words(s.passenger?.gesture)]]}/></Detail>
 <Detail title="Mesaje, muzică și mementouri"><Rows items={[["Baterie telefon",fmt(s.phone?.battery,"%")],["Contact de încredere",s.safe_contact?.name],["Acord notificare",yes(s.safe_contact?.consent)],["Ultima notificare",time(s.safe_contact?.notified_ts)],["Redare activă",yes(s.media?.playing)],["Piesă",s.media?.title],["Volum",fmt(s.media?.volume,"%",100)]]}/>
 <h3>Mesaje</h3>{msg?.length?msg.map((m,i)=><p key={m.id??i}>{m.from} · {m.app} · {words(m.state)} {m.deferred_reason&&"· "+words(m.deferred_reason)}</p>):<p>{msg?"Niciun mesaj":"—"}</p>}
 <h3>Mementouri</h3>{rem?.length?rem.map((r,i)=><p key={r.id??i}>{r.task} · {words(r.state)} · {words(r.trigger?.category)}</p>):<p>{rem?"Niciun memento":"—"}</p>}</Detail></Panel>
}

export function Scorecard({s}: StateProps){
 const c=s.scorecard??{};
 return <Panel id="scorecard" label="REZULTATE" title="Fișa călătoriei"><Metrics items={[["Alerte prag simplu",fmt(s.ab?.naive_alerts)],["Alerte DriveMate",fmt(s.ab?.our_alerts)],["Concentrare maximă",fmt(c.longest_focus_min," min")]]}/>
 <DataBars title="Comparația alertelor" items={[{label:"Prag simplu",value:s.ab?.naive_alerts},{label:"DriveMate",value:s.ab?.our_alerts}]}/>
 <DataBars title="Rezultatul sugestiilor" items={[{label:"Acceptate",value:c.suggestions_accepted},{label:"Respinse",value:c.suggestions_rejected},{label:"Mementouri rezolvate",value:c.reminders_done}]}/>
 <Rows items={[["Mesaje fără mâini",fmt(c.hands_free_messages)],["Atingeri telefon",fmt(c.phone_touches)],["Metri orbi · episod / total",fmt(s.blind_m?.last," m")+" / "+fmt(s.blind_m?.trip," m")],["Sugestii acceptate / respinse",fmt(c.suggestions_accepted)+" / "+fmt(c.suggestions_rejected)],["Mementouri rezolvate",fmt(c.reminders_done)],["Ultima intervenție",words(s.intervention?.last)],["Efect în această sesiune",fmt(s.intervention?.effect_pct,"%")]]}/>
 </Panel>
}
