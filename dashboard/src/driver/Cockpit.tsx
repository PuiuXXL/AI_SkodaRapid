import {useEffect,useState} from "react";
import {Icon} from "../App";
import {fmt} from "../Panels";
import {useDriver} from "./context";
import {tripPhase} from "./contracts";
import {phaseLabels} from "./DrivingPages";

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
  const {data,audio,busy,fresh,command,live}=useDriver();
  const trip=data.state.trip,phase=tripPhase(trip),stop=trip?.next_poi,media=data.state.media;
  const [showStop,setShowStop]=useState(false);

  const canStart=fresh&&!live&&!busy&&["ready","finished","parked"].includes(phase);
  const listening=audio.microphone==="Activ";
  const voiceEnabled=listening||audio.microphone==="Se activează"||audio.microphone==="În pauză";
  const voiceStatus=listening?"Te ascult":audio.microphone==="În pauză"?"Ascultare în pauză":audio.microphone==="Se activează"?"Se activează microfonul":audio.microphone==="Indisponibil"?"Microfon indisponibil":"Microfon oprit";
  const controls=data.state.driver_ui?.commands??[];
  const musicCommand=media?.playing?"stop_media":"request";
  async function music(){
    if(media?.playing){await command("stop_media");return;}
    if(await audio.activateAudio())await command("request",{text:"Propune muzică"});
  }
  return <article className="cockpit">
    <div className="cockpit-title"><div><small>{phaseLabels[phase]}</small><h1 lang="en">I am Copilot.<span>Say my name and I will help you.</span></h1></div>
    {canStart&&<button className="primary-action" onClick={()=>command(phase==="parked"?"resume_trip":"start_trip")}>{phase==="parked"?"Continuă călătoria":"Începe călătoria"}</button>}</div>
    <div className="cockpit-actions">
      <button className="cockpit-tile voice-tile" onClick={voiceEnabled?audio.stopMicrophone:audio.activateMicrophone} aria-pressed={voiceEnabled} aria-label={voiceEnabled?"Oprește microfonul":"Activează vocea"}>
        <span className="voice-wave" data-listening={listening} aria-hidden="true">
          {[12,22,36,44,35,49,42,28,19,32,46,39,24,13,28,43,36,23,16,27,40,34,23,15,32,46,34,20,12].map((height,i)=>
            <i key={i} style={{height,animationDelay:`${-i*87}ms`}}/>)}
        </span><strong>Copilot vocal</strong><span role="status">{voiceStatus}</span></button>
      <button className="cockpit-tile" onClick={audio.audio?audio.silence:audio.activateAudio} aria-pressed={audio.audio}><Icon name="sound"/><strong>Sunet</strong><span>{audio.audio?"Dezactivează sunetul":"Activează sunetul"}</span></button>
      <button className="cockpit-tile" onClick={()=>setShowStop(!showStop)} aria-expanded={showStop}><Icon name="route"/><strong>Oprirea următoare</strong><span>{stop?.name??"Nicio oprire raportată"}</span></button>
      <button className="cockpit-tile" disabled={!fresh||live||busy||!controls.includes(musicCommand)} onClick={music}><Icon name="music"/><strong>{media?.playing?"Oprește muzica":"Muzică"}</strong><span>{media?.playing?media.title||"Redare în curs":media?.playing===false?"Cere o recomandare":"Stare indisponibilă"}</span></button>
    </div>
    {showStop&&<div className="cockpit-summary"><strong>{stop?.name??"Traseu indisponibil"}</strong><span>Până la oprire · {fmt(stop?.dist_km," km")}</span><span>Până la destinație · {fmt(trip?.eta_min," min")}</span></div>}
    <p role="status">{audio.error||data.speech}</p>
  </article>;
}
