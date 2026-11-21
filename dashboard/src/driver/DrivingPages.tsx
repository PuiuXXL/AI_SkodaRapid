import {useId,useRef,useState} from "react";
import {useDriver} from "./context";
import {navigate} from "./routes";
import {categoryNames,tripPhase} from "./contracts";
import {Metrics,fmt,words} from "../Panels";
import {Optic} from "../Optic";
import {RouteDiagram} from "./RouteDiagram";

export const phaseLabels={ready:"Înainte de plecare",moving:"În deplasare",parked:"La oprire",finished:"Călătorie încheiată",unknown:"Stare necunoscută"};
export function PageHeading({label,title,description}: {label:string;title:string;description?:string}){
  return <div className="driver-heading"><small>{label}</small><h1>{title}</h1>{description&&<p>{description}</p>}</div>;
}
export function AudioControls(){const {audio}=useDriver();return <div className="driver-audio-controls">
  <button type="button" onClick={audio.audio?audio.silence:audio.activateAudio}>{audio.audio?"Dezactivează sunetul":"Activează sunetul"}</button>
  <button type="button" onClick={audio.microphone==="Activ"?audio.stopMicrophone:audio.activateMicrophone}>{audio.microphone==="Activ"?"Oprește microfonul":"Activează vocea"}</button>
  <span>Microfon: {audio.microphone}</span>
  {audio.error&&<p role="status">{audio.error}</p>}
</div>;}
export function Copilot(){
  const requestId=useId();
  const {data,audio,command,busy,live,fresh,locked}=useDriver();
  const [request,setRequest]=useState("");
  const pending=data.state.driver_ui?.pending;
  const status=audio.speaking?"Vorbesc":data.state.interaction?.dialog_window_open?"Aștept răspunsul":audio.audio?"Sunet activ":"Sunet oprit";
  return <section className="copilot-card"><div className="copilot-heading"><span className="copilot-symbol" aria-hidden="true"><Optic/></span><div><small>COPILOT</small><h2>{status}</h2></div></div>
    <p className="copilot-speech">{data.speech||"Sunt aici pentru drum, muzică și mementouri."}</p>
    {!!data.state.assistant?.muted_until&&data.state.assistant.muted_until>Date.now()/1000&&<p>Sugestii în pauză până la {new Date(data.state.assistant.muted_until*1000).toLocaleTimeString("ro-RO")}.</p>}
    {pending&&!locked&&<div className="pending-answer"><strong>{pending.question}</strong>{["kss","quiz"].includes(pending.kind)?<p>Răspunde prin voce sau din câmpul de mai jos.</p>:<div className="action-row"><button disabled={busy||!fresh} onClick={()=>command("answer",{id:pending.id,value:"da"})}>Da, confirm</button><button disabled={busy||!fresh} onClick={()=>command("answer",{id:pending.id,value:"nu"})}>Nu acum</button></div>}</div>}
    {!locked&&<form className="copilot-request" onSubmit={async e=>{e.preventDefault();if(await command("request",{text:request}))setRequest("");}}><label htmlFor={requestId}>Vorbește cu copilotul sau scrie la oprire</label><div><input id={requestId} value={request} maxLength={300} placeholder="De exemplu: amintește-mi să iau apă la benzinărie" onChange={e=>setRequest(e.target.value)} disabled={live||!fresh}/><button type="submit" disabled={busy||!request.trim()||live||!fresh}>Trimite</button></div></form>}
    <div className="copilot-caption">Spune „Copilot” înaintea unei cereri. {audio.transcript&&<span>Ai spus: {audio.transcript}</span>}</div>
  </section>;
}
export function StartPage(){
  const {profile,profileError,reloadProfile,live}=useDriver();
  return <div className="arrival-scene"><div className="arrival-optic" aria-hidden="true"><Optic/></div>
    <div className="arrival-copy"><h1>Tu conduci.<br/><span>Rămânem atenți.</span></h1>
    <p>Pregătește drumul și muzica înainte de plecare. În mers, vorbește cu copilotul.</p>
    <button className="primary-action connect-button" disabled={!profile} onClick={()=>navigate(profile?.revision?"volan":"profil")}>Connect <span aria-hidden="true">↗</span></button><small className="connect-source">{live?"Sursă Live · servicii locale":"Mod demonstrativ · fără notificări sau apeluri reale"}</small>
    {profileError&&<div className="form-feedback" role="alert">{profileError}<button onClick={reloadProfile}>Reîncearcă</button></div>}
  </div></div>;
}
export function DrivePage(){
  const {data,profile,command,busy,live,fresh,locked}=useDriver(),s=data.state,phase=tripPhase(s.trip);
  const [ending,setEnding]=useState(false);
  const media=s.media;
  const stop=s.trip?.next_poi;
  const stopName=stop?.name??"Nicio oprire raportată";
  const music=media?.playing===true?media.title||"Redare în curs":media?.playing===false?"Muzica e oprită":"Starea redării indisponibilă";
  const reminderCategory=phase==="parked"?s.trip?.at_poi?.category:stop?.category;
  const reminders=s.reminders?.filter(item=>item.state==="active"&&reminderCategory&&item.trigger?.category===reminderCategory);
  return <div className={"journey-view"+(locked?" journey-focus":"")}>
    <header className="journey-header"><small>{phaseLabels[phase]}</small>
      <h1>{locked?"La volan":"Salut, "+(profile?.name??"șofer")}</h1></header>
    <div className="journey-board">
      <div className="journey-map"><small>Următoarea oprire</small><h2>{stopName}</h2>
        {locked?<p>{fmt(stop?.dist_km," km")}</p>:<RouteDiagram route={s.driver_ui?.route} position={s.trip?.pos}/>}
      </div>
      {!locked&&<aside className="journey-inspector" aria-label="Detalii călătorie">
        <dl><div><dt>Până la oprire</dt><dd>{fmt(stop?.dist_km," km")}</dd></div>
          <div><dt>Timp până la destinație</dt><dd>{fmt(s.trip?.eta_min," min")}</dd></div></dl>
        {!!reminders?.length&&<div><strong>{phase==="parked"?"Mementouri la această oprire":"Mementouri la următoarea oprire"}</strong><ul>{reminders.map(item=><li key={item.id}>{item.task}</li>)}</ul></div>}
        <div className="journey-actions"><button className="primary-action" disabled={busy||!fresh||live} onClick={()=>command(phase==="parked"?"resume_trip":"start_trip")}>{phase==="parked"?"Continuă călătoria":"Începe călătoria"}</button>
          {phase==="parked"&&<button disabled={busy||live} onClick={()=>setEnding(true)}>Încheie călătoria</button>}
          {ending&&phase==="parked"&&<div className="inline-confirmation" role="group" aria-label="Confirmă încheierea"><span>Închei călătoria și deschizi fișa?</span><button disabled={busy||live||!fresh} onClick={async()=>{if(await command("end_trip")){setEnding(false);navigate("rezumat")}}}>Da, încheie</button><button onClick={()=>setEnding(false)}>Continuă aici</button></div>}
          <a href="#/drum">Vezi drumul <span aria-hidden="true">↗</span></a></div>
      </aside>}
    </div>
    <div className="journey-track"><div className="record-mark" aria-hidden="true"><span/></div>
      <div><small>Muzică</small><strong>{music}</strong>{media?.playing&&media.artist&&<span>{media.artist}</span>}</div>
      {!locked&&<a href="#/muzica">Deschide Muzică</a>}</div>
    <Copilot/>{!locked&&<AudioControls/>}
  </div>;
}
export function RoadPage(){
  const {data,command,busy,locked,live,fresh}=useDriver(),s=data.state;
  const [task,setTask]=useState(""),[category,setCategory]=useState("fuel");
  const [stopId,setStopId]=useState("");
  const stops=s.driver_ui?.route?.stops??[];
  const stop=stops.find(p=>p.id===stopId)??stops.find(p=>p.id===s.trip?.next_poi?.id)??stops[0];
  const associated=s.reminders?.filter(r=>!!stop?.category&&r.trigger?.category===stop.category&&r.state==="active");
  return <><PageHeading label="DRUM ȘI MEMENTOURI" title="Opririle care contează" description="Traseul, următoarea oprire și lucrurile de rezolvat pe drum."/>
    <div className="road-workspace"><section><small>CĂLĂTORIA TA</small><h2>{s.trip?.next_poi?.name??"În așteptarea traseului"}</h2><Metrics items={[["Parcurs",fmt(s.trip?.distance_km," km")],["Până la destinație",fmt(s.trip?.eta_min," min")],["Pe drum",fmt(s.trip?.elapsed_min," min")]]}/><RouteDiagram route={s.driver_ui?.route} position={s.trip?.pos} selected={stop?.id} onSelect={setStopId}/>
    <ol className="stop-list">{s.driver_ui?.route?.stops.map((poi,i)=><li key={poi.id}><button type="button" aria-pressed={poi.id===stop?.id} onClick={()=>setStopId(poi.id)}><span className="stop-number">{i+1}</span><div><strong>{poi.name}</strong><small>{categoryNames[poi.category??""]??"Destinație"} · {fmt(poi.km," km")}</small></div></button></li>)}</ol></section>
    <section>{stop&&<header className="stop-detail"><small>Oprire selectată</small><h2>{stop.name}</h2><p>{categoryNames[stop.category??""]??"Destinație"} · km {fmt(stop.km)}</p>
      {associated?.length?<ul>{associated.map(item=><li key={item.id}>{item.task}</li>)}</ul>:<p>Niciun memento activ pentru această categorie.</p>}</header>}<h2>Toate mementourile</h2>{s.reminders?.length?<ul className="driver-list">{s.reminders.map(item=><li key={item.id}><strong>{item.task}</strong><p>{categoryNames[item.trigger?.category??""]??"Oprire"} · {item.state==="done"?"Rezolvat":"Activ"}</p>{item.state==="active"&&<div className="action-row"><button disabled={busy||locked||!fresh||live||s.trip?.at_poi?.category!==item.trigger?.category} onClick={()=>command("complete_reminder",{id:item.id})}>Rezolvat</button><button disabled={busy||locked||!fresh||live||s.trip?.at_poi?.category!==item.trigger?.category} onClick={()=>command("defer_reminder",{id:item.id})}>La următoarea oprire</button></div>}</li>)}</ul>:<p className="empty-state">Nu ai mementouri. Adaugă unul înainte de plecare sau cere-i copilotului prin voce.</p>}
      <form onSubmit={async e=>{e.preventDefault();if(await command("create_reminder",{task,category}))setTask("");}}><fieldset disabled={locked||live||!fresh||busy}><legend>Adaugă un memento</legend><label>Ce să îți amintesc?<input required maxLength={100} value={task} onChange={e=>setTask(e.target.value)}/></label><label>La ce fel de oprire?<select value={category} onChange={e=>setCategory(e.target.value)}>{Object.entries(categoryNames).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label><button type="submit" disabled={!task.trim()}>Cere confirmarea</button></fieldset></form></section></div><Copilot/>
  </>;
}
export function MessagesPage(){
  const {data,command,busy,live,locked,fresh}=useDriver();
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const messages=data.state.messages??[];
  const [sender,setSender]=useState<string|null>(null);
  const list=useRef<HTMLDivElement>(null),back=useRef<HTMLButtonElement>(null);
  const threadKey=(m:typeof messages[number])=>JSON.stringify([m.app,m.from]);
  const threads=new Map(messages.map(m=>[threadKey(m),m]));
  const current=sender&&threads.has(sender)?sender:threads.keys().next().value;
  const open=!!sender&&threads.has(sender);
  function choose(key:string){setSender(key);requestAnimationFrame(()=>{if(back.current?.offsetWidth)back.current.focus()});}
  const states:Record<string,string>={pending:"Primit",deferred:"Amânat",read:"Citit",replied:"Răspuns înregistrat",sent:"Trimis",failed:"Trimitere eșuată"};
  return <><PageHeading label="MESAJE" title="Păstrează legătura" description="Citirea și răspunsul cer acordul tău. Mesajele personale se consultă la oprire."/>
    {!messages.length&&<section className="empty-state"><h2>Niciun mesaj deocamdată</h2><p>Mesajele primite vor apărea aici, cu sursa și starea lor.</p></section>}
    <div className={"inbox"+(open?" thread-open":"")}>{!!threads.size&&<div className="thread-index" ref={list} aria-label="Conversații">{Array.from(threads,([key,m])=><button key={key} data-thread={key} aria-pressed={current===key} onClick={()=>choose(key)}><strong>{m.from??"Expeditor necunoscut"}</strong><small>{words(m.app)}</small></button>)}</div>}
    <div className="message-list">{open&&<button className="thread-back" ref={back} onClick={()=>{const trigger=Array.from(list.current?.querySelectorAll("button")??[]).find(b=>b.dataset.thread===sender);setSender(null);requestAnimationFrame(()=>trigger?.focus())}}>← Conversații</button>}{messages.filter(m=>threadKey(m)===current).map(message=><section key={message.id}><div className="message-heading"><h2>{message.from??"Expeditor necunoscut"}</h2><span className="status-pill">{states[message.state??""]??words(message.state)}</span></div><p className="message-source">{words(message.app)} · {message.ts?new Date(message.ts*1000).toLocaleTimeString("ro-RO"):"Ora indisponibilă"}</p><p className="message-body">{message.text??"Conținutul nu este disponibil în această sursă."}</p>{message.deferred_reason&&<p>Motiv amânare: {words(message.deferred_reason)}</p>}{message.reply&&<blockquote>{message.reply}</blockquote>}
      <button disabled={busy||locked||!fresh||live} onClick={()=>command("read_message",{id:message.id})}>Cere citirea cu voce</button>
      {message.replyable&&<form onSubmit={async e=>{e.preventDefault();if(await command("reply_message",{id:message.id,text:drafts[message.id??""]??""}))setDrafts(old=>({...old,[message.id??""]:""}));}}><label>Răspuns pentru {message.from}<textarea maxLength={300} value={drafts[message.id??""]??""} onChange={e=>setDrafts(old=>({...old,[message.id??""]:e.target.value}))} disabled={locked||!fresh||live}/></label><button type="submit" disabled={busy||locked||!fresh||live||!drafts[message.id??""]?.trim()}>Ascultă și confirmă răspunsul</button></form>}
    </section>)}</div></div><Copilot/>
  </>;
}
