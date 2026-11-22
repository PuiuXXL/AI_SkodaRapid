import type { ReactNode } from "react";
import type { StateProps, RowsData, Reading } from "./types";
import {CardArt, type ArtSubject} from "./CardArt";
import React,{createContext,useContext,useId,useState} from "react";
import {motion,useReducedMotion} from "motion/react";
import {DataBars} from "./DataBars";
import {Flag,RangeBars,Ring,Spark,StackBar} from "./charts";
import type {Sample} from "./telemetry";
import {integrationNames,integrationStates,label,monitoringReasons,phoneUsage,postures,seats} from "./labels";
export function fmt(value: Reading | undefined, unit="", factor=1, digits=1){
  return Number.isFinite(value)? (value!*factor).toLocaleString("en-GB",{maximumFractionDigits:digits})+unit:"—";
}
export const yes=(value: boolean | undefined)=>value===true?"Yes":value===false?"No":"—";
export const time=(value: Reading | undefined)=>Number.isFinite(value)?new Date(value!*1000).toLocaleTimeString("en-GB"):"—";
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
export function Panel({id,label,title,children,art}: {art?: ArtSubject; id: string; label: string; title: string; children: ReactNode}){return <section id={id}>{art?<header className="art-heading"><CardArt subject={art}/><div><small>{label}</small><h2>{title}</h2></div></header>:<><small>{label}</small><h2>{title}</h2></>}{children}</section>}

export function VisionDiagnostics({s,connection}: StateProps & {connection:string}){
 const driver=s.driver, camera=s.perf?.cameras?.driver;
 const tracked=driver?.monitoring_ok===true && camera?.available!==false;
 return <Panel art="camera" id="vision" label="LIVE DIAGNOSTICS" title="Driver camera signal">
   <Metrics items={[
     ["Core connection",connection],
     ["Frame available",yes(camera?.available)],
     ["Frame age at publication",fmt(camera?.age_ms," ms")],
   ]}/>
   <Rows items={[
     ["Monitoring",driver?.monitoring_ok===true?"Active":driver?.monitoring_ok===false?"Interrupted":"—"],
     ["Reported reason",driver?.monitoring_reason],
     ["Warnings",driver?.monitoring_warnings?.join(", ")||"—"],
     ["Camera mode",words(driver?.camera_mode)],
     ["Face confidence",fmt(driver?.face_conf,"%",100)],
     ["Gaze calibration",tracked?yes(driver?.gaze?.calibrated):"—"],
     ["Off-road time · last 60 s",tracked && driver?.gaze?.calibrated?fmt(driver.gaze.off_road_60s_ms," s",.001,2):"—"],
     ["Dropped results",fmt(camera?.dropped_results)],
   ]}/>
 </Panel>;
}

export function Performance({s,samples=[]}: StateProps & {samples?: Sample[]}){
 const p=s.perf??{}, cameras=p.cameras??{};
 const models={face_driver:"Driver face",face_passenger:"Passenger face",pose:"Posture",phone:"Phone",gesture:"Gesture",sface:"Identity"};
 const modelRows: RowsData=Object.entries(models).map(([k,name])=>[name,fmt(p[`${k}_ms_p50`]," ms")+" / "+fmt(p[`${k}_ms_p95`]," ms")]);
 return <Panel id="performance" label="TELEMETRY" title="System performance">
 <Metrics items={[["CPU",fmt(p.cpu,"%")],["RAM",fmt(p.ram_mb," MB")],["GPU",fmt(p.gpu,"%")]]}/>
 <div className="fx-resources">
   <Ring value={p.cpu} max={100} size={84} label="Processor"><b>{fmt(p.cpu,"%",1,0)}</b><small>CPU</small></Ring>
   <Ring value={p.gpu} max={100} size={84} tone="soft" label="Graphics card"><b>{fmt(p.gpu,"%",1,0)}</b><small>GPU</small></Ring>
   <figure><figcaption>Capture → publish · p95<b>{fmt(p.e2e_ms_p95," ms",1,0)}</b></figcaption><Spark values={samples.map(sample=>sample.e2e)} tone={typeof p.e2e_ms_p95==="number"&&p.e2e_ms_p95>150?"warn":"ink"} label="End-to-end latency over the last minute"/><small>target below 150 ms{typeof p.degrade_level==="number"&&p.degrade_level>0?" · degradation level "+p.degrade_level:""}</small></figure>
 </div>
 <DataBars title="Camera processing" items={[{label:"Driver",value:cameras.driver?.process_fps,unit:" fps"},{label:"Passenger",value:cameras.passenger?.process_fps,unit:" fps"}]}/>
 <Detail title="Cameras & latency"><Rows items={[
 ...["driver","passenger"].map<[string, ReactNode]>((c,i)=>[i?"Passenger camera":"Driver camera",fmt(cameras[c]?.capture_fps)+" fps capture · "+fmt(cameras[c]?.process_fps)+" fps processing · "+fmt(cameras[c]?.dropped_frames)+" dropped"]),
 ["Capture → publish (p95)",fmt(p.e2e_ms_p95," ms")],["Alarm · target <300 ms",fmt(s.safety?.alarm_ms_last??p.alarm_ms_last," ms")],
 ...Object.entries({llm_ttft_ms:"LLM · first token",llm_total_ms:"LLM · total",stt_final_ms:"Speech → final text",tts_first_audio_ms:"Text → first audio",msg_to_voice_ms:"Message → speech"}).map<[string, ReactNode]>(([k,v])=>[v,fmt(p[k as "llm_ttft_ms" | "llm_total_ms" | "stt_final_ms" | "tts_first_audio_ms" | "msg_to_voice_ms"]," ms")])]}/></Detail>
 <Detail title="Stage latency · p50 / p95"><RangeBars items={Object.entries(p.stages_ms??{}).flatMap(([camera,stages])=>Object.entries(stages??{}).map(([stage,times])=>({label:(camera==="driver"?"Driver":camera==="passenger"?"Passenger":camera)+" · "+stage.replaceAll("_"," "),lo:times?.p50,hi:times?.p95}))).sort((a,b)=>(b.hi??0)-(a.hi??0)).slice(0,8)}/></Detail>
 <Detail title="Integrations"><div className="fx-flags">{Object.entries(s.integrations??{}).map(([name,state])=><span key={name} className={"fx-flag"+(state==="ok"?" is-on tone-ok":state==="down"?" is-on tone-danger":"")}>{label(integrationNames,name)}<b>{label(integrationStates,state)}</b></span>)}{!s.integrations&&<p className="fx-empty">Integration status arrives from core.</p>}</div></Detail>
 <Detail title="Models · p50 / p95"><Rows items={modelRows}/></Detail></Panel>
}

export function Cabin({s}: StateProps){
 const people=Array.isArray(s.occupants)?s.occupants:null,msg=Array.isArray(s.messages)?s.messages:null,rem=Array.isArray(s.reminders)?s.reminders:null;
 return <Panel id="cabin" label="ON BOARD" title="Cabin & phone"><Metrics items={[
 ["Occupants",fmt(people?.length)],["Phone connected",yes(s.phone?.connected)],["Pending messages",fmt(msg?.filter(m=>["pending","deferred"].includes(m.state??"")).length)]]}/>
 <DataBars title="Phone & audio" maximum={100} items={[{label:"Battery",value:s.phone?.battery,unit:"%"},{label:"Volume",value:typeof s.media?.volume==="number"?s.media.volume*100:s.media?.volume,unit:"%"}]}/>
 <Detail title="Occupants & conversation"><div className="fx-people">{people?.map((p,i)=><div key={p.id??i} className="fx-person"><span aria-hidden="true">{(p.profile??"?").slice(0,1).toUpperCase()}</span><div><strong>{p.profile??"Unknown profile"}</strong><small>{label(seats,p.seat)} · {p.source==="declared"?"declared":"seen by camera"}{p.role==="child"?" · child":""}{typeof p.profile_score==="number"?" · match "+fmt(p.profile_score,"%",100,0):""}</small></div></div>)}</div>
 <div className="fx-flags"><Flag label="Passenger present" on={s.passenger?.present}/><Flag label="Awake" on={s.passenger?.awake}/><Flag label="Speaking" on={s.passenger?.speaking}/><Flag label="Phone in hand" on={s.passenger?.holding_phone} tone="warn"/><Flag label="Conversation" on={s.conversation}/></div>
 <Rows items={[["Passenger · eyes closed",fmt(s.passenger?.eyes_closed_s," s")],["Passenger gesture",words(s.passenger?.gesture)],["Passenger head response",s.passenger?.answer==="yes"?"Yes":s.passenger?.answer==="no"?"No":"—"],["Passenger camera",s.passenger?.monitoring_ok===false?label(monitoringReasons,s.passenger.monitoring_reason??"face_lost"):s.passenger?.monitoring_ok===true?"Active":"—"],["Driver phone",s.driver?.phone?.in_use?label(phoneUsage,s.driver.phone.usage??"visible"):s.driver?.phone?.foreign_seen?"Seen with passenger":yes(s.driver?.phone?.in_use)],["Driver posture",Object.entries(s.driver?.posture??{}).filter(([,on])=>on).map(([name])=>label(postures,name)).join(", ")||(s.driver?.posture?"Normal":"—")]]}/></Detail>
 <Detail title="Messages, music & reminders"><Rows items={[["Trusted contact",s.safe_contact?.name],["Contact configured",yes(s.safe_contact?.configured)],["Notification consent",yes(s.safe_contact?.consent)],["Last notification",time(s.safe_contact?.notified_ts)],["Call in progress",s.call?words((s.call as {state?: unknown}).state??"active"):s.call===null?"No":"—"],["Playback active",yes(s.media?.playing)],["Track",s.media?.title],["Reason for selection",words(s.media?.reason)],["Child-friendly",s.media?.playing?yes(s.media?.kid_safe):"—"]]}/>
 <h3>Messages</h3>{msg?.length?msg.map((m,i)=><p key={m.id??i}>{m.from} · {m.app} · {words(m.state)} {m.deferred_reason&&"· "+words(m.deferred_reason)}</p>):<p>{msg?"No messages":"—"}</p>}
 <h3>Reminders</h3>{rem?.length?rem.map((r,i)=><p key={r.id??i}>{r.task} · {words(r.state)} · {words(r.trigger?.category)}</p>):<p>{rem?"No reminders":"—"}</p>}</Detail></Panel>
}

export function Scorecard({s}: StateProps){
 const c=s.scorecard??{};
 return <Panel id="scorecard" label="TRIP RESULTS" title="Trip report"><Metrics items={[["Threshold alerts",fmt(s.ab?.naive_alerts)],["DriveMate alerts",fmt(s.ab?.our_alerts)],["Longest focus",fmt(c.longest_focus_min," min")]]}/>
 <DataBars title="Alert comparison" items={[{label:"Simple threshold",value:s.ab?.naive_alerts},{label:"DriveMate",value:s.ab?.our_alerts}]}/>
 <DataBars title="Suggestion outcomes" items={[{label:"Accepted",value:c.suggestions_accepted},{label:"Declined",value:c.suggestions_rejected},{label:"Completed reminders",value:c.reminders_done}]}/>
 <figure className="fx-block"><figcaption>Suggestions · accepted vs declined</figcaption><StackBar label="Accepted and declined suggestions" parts={[{label:"Accepted",value:c.suggestions_accepted??0,tone:"ok"},{label:"Declined",value:c.suggestions_rejected??0,tone:"soft"}]}/></figure>
 <Rows items={[["Hands-free messages",fmt(c.hands_free_messages)],["Phone touches",fmt(c.phone_touches)],["Blind metres · episode / total",fmt(s.blind_m?.last," m")+" / "+fmt(s.blind_m?.trip," m")],["Accepted / declined suggestions",fmt(c.suggestions_accepted)+" / "+fmt(c.suggestions_rejected)],["Completed reminders",fmt(c.reminders_done)],["Last intervention",words(s.intervention?.last)],["Effect in this session",fmt(s.intervention?.effect_pct,"%")]]}/>
 </Panel>
}
