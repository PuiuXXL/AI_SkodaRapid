import {useEffect,useState} from "react";
import {Icon} from "../App";
import {fmt} from "../Panels";
import {useDriver} from "./context";
import {tripPhase} from "./contracts";
import {phaseLabels} from "./DrivingPages";
import {alerts,label} from "../labels";

// The mirrored halves share one profile, from the wide outer disc to the thin centre.
const discs=[
  {cx:41,rx:40},{cx:77,rx:25},{cx:104,rx:17},
  {cx:123,rx:10},{cx:136,rx:6},{cx:145,rx:2}
];
function LoadingWave(){
  return <svg className="loading-wave" viewBox="0 0 300 92" aria-hidden="true" focusable="false">
    {[false,true].map(mirror=><g key={String(mirror)} transform={mirror?"translate(300 0) scale(-1 1)":undefined}>
      {discs.map(({cx,rx},i)=><ellipse key={cx} cx={cx} cy="46" rx={rx} ry="40"
        fill={`color-mix(in srgb, var(--ui-text) ${95-i*10}%, var(--ui-bg))`}
        style={{animationDelay:`${(i-5)*85}ms`}}/>)}
    </g>)}
  </svg>;
}

export function Greeting({ready,error,retry,dark}:{ready:boolean;error:string;retry:()=>void;dark:boolean}){
  const [introduced,setIntroduced]=useState(false);
  const [delayed,setDelayed]=useState(false);
  const leaving=ready&&introduced;
  useEffect(()=>{
    const intro=setTimeout(()=>setIntroduced(true),850);
    const wait=setTimeout(()=>setDelayed(true),6000);
    return ()=>{clearTimeout(intro);clearTimeout(wait)};
  },[]);
  useEffect(()=>{
    if(!leaving)return;
    const timer=setTimeout(()=>location.replace("#/volan"),matchMedia("(prefers-reduced-motion: reduce)").matches?0:220);
    return ()=>clearTimeout(timer);
  },[leaving]);
  return <main data-workspace-theme={dark?"dark":"light"} className={"drive-welcome"+(leaving?" departing":"")}>
    <div><LoadingWave/><h1>Salut, Andrei!</h1><p role="status">{error||(!ready&&delayed?"Așteptăm conexiunea cu sesiunea locală.":"Se pregătește călătoria…")}</p>
    {error&&<button onClick={retry}>Reîncearcă</button>}{(error||delayed)&&<a href="#/volan">Continuă la volan</a>}</div>
  </main>;
}

export function Cockpit(){
  const {data,audio,busy,fresh,command,can,live,profile}=useDriver();
  const s=data.state,trip=s.trip,phase=tripPhase(trip),stop=trip?.next_poi,media=s.media,a=s.assessment??{},safety=s.safety??{};
  // Live: core's simulator has no "ready" phase, so a stopped or unknown trip can be started too.
  const canStart=!busy&&can("start_trip")&&(["ready","finished","parked"].includes(phase)||(live&&phase==="unknown"));
  const listening=audio.microphone==="Activ";
  const voiceEnabled=listening||audio.microphone==="Se activează"||audio.microphone==="În pauză";
  const voiceStatus=listening?"Te ascult":audio.microphone==="În pauză"?"Ascultare în pauză":audio.microphone==="Se activează"?"Se activează microfonul":audio.microphone==="Indisponibil"?"Microfon indisponibil":"Microfon oprit";
  const pending=s.driver_ui?.pending,asking=!!pending||s.interaction?.dialog_window_open===true;
  const alert=typeof safety.alert==="object"?safety.alert?.text:safety.alert;
  const waiting=s.messages?.filter(m=>["pending","deferred"].includes(m.state??"")).length;
  const reminders=s.reminders?.filter(r=>r.state==="active").length;
  async function music(){
    if(media?.playing){await command("stop_media");return;}
    if(await audio.activateAudio())await command("request",{text:"Propune muzică"});
  }
  const name=profile?.name??s.occupants?.find(o=>o.seat==="driver")?.profile;
  return <article className="cockpit">
    <div className="cockpit-title"><div><small>{phaseLabels[phase]}</small><h1>{name?"Salut, "+name+".":"Copilotul tău."}<span>Spune „Copilot” și te ajut cu drumul, muzica și mesajele.</span></h1></div>
    {canStart&&<button className="primary-action" onClick={()=>command(phase==="parked"?"resume_trip":"start_trip")}>{phase==="parked"?"Continuă călătoria":"Începe călătoria"}</button>}</div>
    <div className="cockpit-grid">
      <section className="cockpit-voice" data-listening={listening}>
        <button className="cockpit-mic" onClick={voiceEnabled?audio.stopMicrophone:audio.activateMicrophone} aria-pressed={voiceEnabled} aria-label={voiceEnabled?"Oprește microfonul":"Activează vocea"}>
          <span className="voice-wave" data-listening={listening} aria-hidden="true">
            {[12,22,36,44,35,49,42,28,19,32,46,39,24,13,28,43,36,23,16,27,40,34,23,15,32,46,34,20,12].map((height,i)=>
              <i key={i} style={{height,animationDelay:`${-i*87}ms`}}/>)}
          </span><strong>Copilot vocal</strong><span role="status">{voiceStatus}</span></button>
        <p className="cockpit-speech">{audio.error||data.speech||"Sunt aici pentru drum, muzică și mementouri."}</p>
        {asking&&<div className="cockpit-answer"><span>{pending?.question??"Copilotul așteaptă răspunsul tău."}</span>
          {(!pending||!["kss","quiz"].includes(pending.kind))&&<div><button disabled={busy||!can("answer")} onClick={()=>command("answer",{id:pending?.id,value:"da"})}>Da</button><button disabled={busy||!can("answer")} onClick={()=>command("answer",{id:pending?.id,value:"nu"})}>Nu</button></div>}</div>}
        {audio.transcript&&<small className="cockpit-heard">Ai spus: {audio.transcript}</small>}
      </section>
      <section className={"cockpit-card cockpit-safety"+(alert?" is-alert":"")}>
        <header><Icon name="pulse"/><span>Siguranță</span><b>{safety.level??"P4"}</b></header>
        <strong>{safety.monitoring_ok===false?"Nu te mai văd":alert?label(alerts,alert):"Totul în regulă"}</strong>
        <div className="cockpit-meters"><Meter label="Atenție" value={a.attention}/><Meter label="Oboseală" value={a.fatigue} warn/><Meter label="Dezinteres" value={a.disengagement} warn/></div>
      </section>
      <section className="cockpit-card">
        <header><Icon name="route"/><span>Drum</span><b>{fmt(trip?.speed_kmh," km/h",1,0)}</b></header>
        <strong>{stop?.name??"Nicio oprire raportată"}</strong>
        <dl><div><dt>Până la oprire</dt><dd>{fmt(stop?.dist_km," km")}</dd></div><div><dt>Până la destinație</dt><dd>{fmt(trip?.eta_min," min",1,0)}</dd></div><div><dt>Pe drum</dt><dd>{fmt(trip?.elapsed_min," min",1,0)}</dd></div></dl>
        <button disabled={busy||!can("stop_at_poi")||phase!=="moving"} onClick={()=>command("stop_at_poi")}>Oprește la următoarea oprire</button>
      </section>
      <section className="cockpit-card">
        <header><Icon name="music"/><span>Sunet și muzică</span><b>{audio.audio?"pornit":"oprit"}</b></header>
        <strong>{media?.playing?media.title||"Redare în curs":"Nicio piesă"}</strong>
        <div className="cockpit-row"><button onClick={audio.audio?audio.silence:audio.activateAudio} aria-pressed={audio.audio}>{audio.audio?"Oprește sunetul":"Activează sunetul"}</button>
          <button disabled={busy||!can(media?.playing?"stop_media":"request")} onClick={music}>{media?.playing?"Oprește muzica":"Cere muzică"}</button></div>
      </section>
      <section className="cockpit-card">
        <header><Icon name="message"/><span>Mesaje și mementouri</span><b>{s.phone?.connected?"telefon conectat":s.phone?.connected===false?"fără telefon":"—"}</b></header>
        <div className="cockpit-counts"><div><b>{fmt(waiting,"",1,0)}</b><span>mesaje în așteptare</span></div><div><b>{fmt(reminders,"",1,0)}</b><span>mementouri active</span></div></div>
        <small>Mesajele se citesc cu voce, la cererea ta; cele personale așteaptă oprirea.</small>
      </section>
    </div>
  </article>;
}
function Meter({label,value,warn}:{label:string;value:number|null|undefined;warn?:boolean}){
  const measured=typeof value==="number"&&Number.isFinite(value),share=measured?Math.max(0,Math.min(1,value)):0;
  return <div className={"cockpit-meter"+(warn&&share>.6?" is-warn":"")}><span>{label}<b>{fmt(value,"",100,0)}</b></span><i aria-hidden="true">{measured&&<em style={{width:share*100+"%"}}/>}</i></div>;
}
