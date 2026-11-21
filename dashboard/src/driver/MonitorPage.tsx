import {useState} from "react";
import {Cameras,Eyes,General,Reaction} from "../App";
import {Cabin,Performance,Scorecard,fmt} from "../Panels";
import {ScoreHistory} from "../ScoreHistory";
import {EventJournal} from "./EventJournal";
import {useDriver} from "./context";
import {PageHeading} from "./DrivingPages";

// MiniStatisticsCard adapted from Vision UI Free React, Simmmple & Creative Tim (MIT).
function MiniStatisticsCard({title,count}:{title:string;count:string}){
  return <div className="vision-stat"><small>{title}</small><strong>{count}</strong></div>;
}
const destinations=[["camera-overview","General"],["score-history","Scoruri"],["eyes","Privire"],["reaction","Reacție"],["cabin","Cabină"],["scorecard","Fișă"],["performance","Sistem"],["recent-events","Jurnal"]];
export function MonitorPage(){
  const {data,live,setLive}=useDriver(),s=data.state,p=s.perf??{};
  const [docked,setDocked]=useState(false);
  const [eventTime,setEventTime]=useState<number>();
  return <div className={"monitor-page"+(docked?" has-camera-dock":"")}><PageHeading label="INSTRUMENTE / MONITORIZARE" title="Dashboard" description="Semnale, context și performanță în aceeași sesiune cu ecranul șoferului."/>
    <nav className="monitor-section-nav" aria-label="Secțiuni monitorizare">{destinations.map(([id,label])=><a key={id} href={"#"+id} onClick={e=>{e.preventDefault();e.currentTarget.closest(".monitor-page")?.querySelector("#"+id)?.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth",block:"start"});}}>{label}</a>)}</nav>
    <section className="perf"><span>Performanță</span>{[["FPS șofer",fmt(p.cameras?.driver?.process_fps)],["FPS pasager",fmt(p.cameras?.passenger?.process_fps)],["p95 captură → publicare",fmt(p.e2e_ms_p95," ms")],["Ultima alarmă",fmt(s.safety?.alarm_ms_last??p.alarm_ms_last," ms")]].map(([name,value])=><MiniStatisticsCard key={name} title={name} count={value}/>)}</section>
    <div className="columns" id="camera-overview"><Cameras live={live} socket={data.socket} cue={data.cue} trip={s.trip} onLive={()=>setLive(true)} onDock={setDocked}/><div className="content"><General s={s} points={data.history}/></div></div>
    <div className="monitor-analysis"><ScoreHistory points={data.history} sectionId="score-history" eventTime={eventTime}/><EventJournal id="recent-events" events={data.log} onSelect={setEventTime}/></div>
    <div className="expanded-sections content"><div className="signal-sections"><Eyes s={s} live={live}/><Reaction s={s}/></div><Cabin s={s}/><Scorecard s={s}/><Performance s={s}/></div>
  </div>;
}
