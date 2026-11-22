import {useEffect,useState} from "react";
import {CardArt} from "../CardArt";
import {fmt} from "../Panels";
import {useDriver} from "./context";
import {driverName,phaseLabels,tripPhase} from "./contracts";
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

/** Shown after Connect until core's first state arrives; the name is the driver profile P1 recognised, if any. */
export function Greeting({ready,name,dark}:{ready:boolean;name?:string;dark:boolean}){
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
    <div><LoadingWave/><h1>{name?"Hello, "+name+"!":"Hello!"}</h1><p role="status">{!ready&&delayed?"Waiting for core. Start core and perception to connect.":"Getting your trip ready…"}</p>
    {delayed&&<a href="#/volan">Continue to the wheel</a>}</div>
  </main>;
}

export function Cockpit(){
  const {data,audio,command,can,fresh}=useDriver();
  const s:typeof data.state=fresh?data.state:{},trip=s.trip,phase=tripPhase(trip),stop=trip?.next_poi,media=s.media,a=s.assessment??{},safety=s.safety??{};
  // Core accepts "start" whenever the car is not moving, including before its first state has arrived here.
  const canStart=can("start_trip")&&phase!=="moving";
  const listening=audio.microphone==="Active";
  const voiceEnabled=listening||audio.microphone==="Starting"||audio.microphone==="Paused";
  const voiceStatus=listening?"Listening":audio.microphone==="Paused"?"Listening paused":audio.microphone==="Starting"?"Starting microphone":audio.microphone==="Unavailable"?"Microphone unavailable":"Microphone off";
  const asking=s.interaction?.dialog_window_open===true;
  const alert=typeof safety.alert==="object"?safety.alert?.text:safety.alert;
  const waiting=s.messages?.filter(m=>["pending","deferred"].includes(m.state??"")).length;
  const reminders=s.reminders?.filter(r=>r.state==="active").length;
  async function music(){
    if(media?.playing){await command("stop_media");return;}
    if(await audio.activateAudio())await command("request",{text:"Propune muzică"});
  }
  const name=driverName(s.occupants);
  return <article className="cockpit">
    <div className="cockpit-title"><div><small>{phaseLabels[phase]}</small><h1>{name?"Hello, "+name+".":"Your copilot."}</h1><p>Say “Copilot” for help with your route, music and messages.</p></div>
    {canStart&&<button className="primary-action" onClick={()=>command(phase==="parked"?"resume_trip":"start_trip")}>{phase==="parked"?"Resume trip":"Start trip"}</button>}</div>
    <div className="cockpit-grid">
      <section className="cockpit-voice" data-listening={listening}>
        <button className="cockpit-mic" onClick={voiceEnabled?audio.stopMicrophone:audio.activateMicrophone} aria-pressed={voiceEnabled} aria-label={voiceEnabled?"Turn off microphone":"Enable voice"}>
          <span className="voice-wave" data-listening={listening} aria-hidden="true">
            {[12,22,36,44,35,49,42,28,19,32,46,39,24,13,28,43,36,23,16,27,40,34,23,15,32,46,34,20,12].map((height,i)=>
              <i key={i} style={{height,animationDelay:`${-i*87}ms`}}/>)}
          </span><strong>Voice copilot</strong><span role="status">{voiceStatus}</span><span className="mic-action">{voiceEnabled?"Turn off microphone":"Enable voice"}</span></button>
        <p className="cockpit-speech">{audio.error||data.speech||"Ready to help with your route, music and reminders."}</p>
        {asking&&<div className="cockpit-answer"><span>Your copilot is waiting for your answer.</span>
          <div><button disabled={!can("answer")} onClick={()=>command("answer",{value:"da"})}>Yes</button><button disabled={!can("answer")} onClick={()=>command("answer",{value:"nu"})}>No</button></div></div>}
        {audio.transcript&&<small className="cockpit-heard">You said: {audio.transcript}</small>}
      </section>
      <section className={"cockpit-card cockpit-safety"+(alert?" is-alert":"")}>
        <header><CardArt subject="camera"/><span>Safety</span><b>{s.safety?safety.level??"P4":"—"}</b></header>
        <strong>{safety.monitoring_ok===false?"Monitoring lost":alert?label(alerts,alert):s.safety?"All clear":"No data from core"}</strong>
        <div className="cockpit-meters"><Meter label="Attention" value={a.attention}/><Meter label="Fatigue" value={a.fatigue} warn/><Meter label="Disengagement" value={a.disengagement} warn/></div>
      </section>
      <section className="cockpit-card">
        <header><CardArt subject="route"/><span>Road</span><b>{fmt(trip?.speed_kmh," km/h",1,0)}</b></header>
        <strong>{stop?.name??"No upcoming stop"}</strong>
        <dl><div><dt>Distance to stop</dt><dd>{fmt(stop?.dist_km," km")}</dd></div><div><dt>Arrival in</dt><dd>{fmt(trip?.eta_min," min",1,0)}</dd></div><div><dt>Time on the road</dt><dd>{fmt(trip?.elapsed_min," min",1,0)}</dd></div></dl>
        <button disabled={!can("stop_at_poi")||phase!=="moving"} onClick={()=>command("stop_at_poi")}>Stop at the next stop</button>
      </section>
      <section className="cockpit-card">
        <header><CardArt subject="music"/><span>Sound & music</span><b>{audio.audio?"on":"off"}</b></header>
        <strong>{media?.playing?media.title||"Now playing":"Nothing playing"}</strong>
        <div className="cockpit-row"><button onClick={audio.audio?audio.silence:audio.activateAudio} aria-pressed={audio.audio}>{audio.audio?"Mute audio":"Enable audio"}</button>
          <button disabled={!can(media?.playing?"stop_media":"request")} onClick={music}>{media?.playing?"Stop music":"Request music"}</button></div>
      </section>
      <section className="cockpit-card">
        <header><CardArt subject="message"/><span>Messages & reminders</span><b>{s.phone?.connected?"phone connected":s.phone?.connected===false?"phone offline":"—"}</b></header>
        <div className="cockpit-counts"><div><b>{fmt(waiting,"",1,0)}</b><span>pending messages</span></div><div><b>{fmt(reminders,"",1,0)}</b><span>active reminders</span></div></div>
        <small>Ask to hear your messages. Personal messages wait until you stop.</small>
      </section>
    </div>
  </article>;
}
function Meter({label,value,warn}:{label:string;value:number|null|undefined;warn?:boolean}){
  const measured=typeof value==="number"&&Number.isFinite(value),share=measured?Math.max(0,Math.min(1,value)):0;
  return <div className={"cockpit-meter"+(warn&&share>.6?" is-warn":"")}><span>{label}<b>{fmt(value,"",100,0)}{measured&&<small> /100</small>}</b></span><i aria-hidden="true">{measured&&<em style={{width:share*100+"%"}}/>}</i></div>;
}
