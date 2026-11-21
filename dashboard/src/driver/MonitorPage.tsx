import {useState} from "react";
import {Cameras,Eyes,General,Reaction} from "../App";
import {Cabin,InlineDetails,Performance,Rows,Scorecard,VisionDiagnostics,fmt,time,words} from "../Panels";
import {ScoreHistory} from "../ScoreHistory";
import {EventJournal} from "./EventJournal";
import {InstrumentStack} from "./InstrumentStack";
import {useDriver} from "./context";
import {PageHeading} from "./DrivingPages";
import "./monitor-layout.css";

export function MonitorPage(){
  const {data,live,setLive,fresh}=useDriver();
  const s=live&&!fresh?{}:data.state,p=s.perf??{};
  const [docked,setDocked]=useState(false),[eventTime,setEventTime]=useState<number>();
  const history=live&&!fresh?[]:data.history;
  const cards=[
    {label:"Scoruri",icon:"chart",description:"Atenție, oboseală și dezinteres · aceeași scală, în timp.",body:<>
      <ScoreHistory points={history} sectionId="score-history" eventTime={eventTime}/>
      <div className="score-context"><h3>Contextul evaluării</h3><Rows items={[["Nivel de siguranță",s.safety?.level],["Risc raportat",fmt(s.assessment?.risk," / 3")],["Cauză",words(s.cause?.label)],["Încredere cauză",fmt(s.cause?.conf,"%",100)],["Ultima stare",time(s.ts)],["Mostre disponibile",fmt(history.filter(Boolean).length)]]}/></div>
    </>},
    {label:"Privire",icon:"eye",description:"Direcția privirii, pleoape și calitatea semnalului ocular.",body:<Eyes s={s} live={live}/>},
    {label:"Reacție",icon:"pulse",description:"Răspunsurile șoferului comparate cu referința personală.",body:<Reaction s={s}/>},
    {label:"Cabină",icon:"cabin",description:"Ocupanți, telefon, conversație și conținutul de la bord.",body:<Cabin s={s}/>},
    {label:"Fișă",icon:"report",description:"Concentrare, intervenții și rezultatele călătoriei.",body:<Scorecard s={s}/>},
    {label:"Sistem",icon:"chip",description:"Resurse, procesarea camerelor și latențe pe fiecare etapă.",body:<Performance s={s}/>},
    {label:"Jurnal",icon:"journal",description:"Evenimentele sesiunii și explicația fiecărei intervenții.",body:<EventJournal id="recent-events" events={data.log} pageSize={4} onSelect={setEventTime}/>},
  ];
  return <InlineDetails.Provider value={true}><div className={"monitor-page"+(docked?" has-camera-dock":"")}>
    <PageHeading label="INSTRUMENTE / MONITORIZARE" title="Dashboard" description="Camere și telemetrie de bord"/>
    <Cameras live={live} socket={data.socket} cue={data.cue} trip={s.trip} onLive={()=>setLive(true)} onDock={setDocked}/>
    <section className="perf"><span>Performanță</span>{[["FPS șofer",fmt(p.cameras?.driver?.process_fps)],["FPS pasager",fmt(p.cameras?.passenger?.process_fps)],["p95 captură → publicare",fmt(p.e2e_ms_p95," ms")],["Ultima alarmă",fmt(s.safety?.alarm_ms_last??p.alarm_ms_last," ms")]].map(([title,count])=><div className="vision-stat" key={title}><small>{title}</small><strong>{count}</strong></div>)}</section>
    <div className="content monitor-overview"><General s={s} points={history}/>{live&&<VisionDiagnostics s={s} connection={data.connection}/>}</div>
    <InstrumentStack cards={cards}/>
  </div></InlineDetails.Provider>;
}
