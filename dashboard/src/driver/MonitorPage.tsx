import {useState} from "react";
import {Cameras,Eyes,Reaction} from "../App";
import {Cabin,InlineDetails,Performance,Rows,Scorecard,VisionDiagnostics,fmt,time,words} from "../Panels";
import {ScoreHistory} from "../ScoreHistory";
import {EventJournal} from "./EventJournal";
import {InstrumentStack} from "./InstrumentStack";
import {ControlPanel} from "./ControlPanel";
import {KpiStrip,Overview,StatusStrip} from "./MonitorParts";
import {useDriver} from "./context";
import {PageHeading} from "./DrivingPages";
import {useTelemetry} from "../telemetry";
import {causes,label,safetyLevels} from "../labels";
import "./monitor-layout.css";

export function MonitorPage(){
  const {data,live,setLive,fresh}=useDriver();
  const s=live&&!fresh?{}:data.state;
  const [docked,setDocked]=useState(false),[eventTime,setEventTime]=useState<number>();
  const history=live&&!fresh?[]:data.history;
  const samples=useTelemetry(s);
  const cards=[
    {label:"Scoruri",icon:"chart",description:"Atenție, oboseală și dezinteres · aceeași scală, în timp.",body:<>
      <ScoreHistory points={history} sectionId="score-history" eventTime={eventTime}/>
      <div className="score-context"><h3>Contextul evaluării</h3><Rows items={[["Nivel de siguranță",(s.safety?.level??"—")+" · "+label(safetyLevels,s.safety?.level)],["Risc raportat",fmt(s.assessment?.risk," / 3")],["Cauză",label(causes,s.cause?.label)],["Încredere cauză",fmt(s.cause?.conf,"%",100)],["Ultima intervenție",words(s.intervention?.last)],["Efect măsurat",fmt(s.intervention?.effect_pct,"%")],["Ultima stare",time(s.ts)],["Mostre disponibile",fmt(history.filter(Boolean).length)]]}/></div>
    </>},
    {label:"Privire",icon:"eye",description:"Direcția privirii, pleoape și calitatea semnalului ocular.",body:<Eyes s={s} live={live} samples={samples}/>},
    {label:"Reacție",icon:"pulse",description:"Răspunsurile șoferului comparate cu referința personală.",body:<Reaction s={s}/>},
    {label:"Cabină",icon:"cabin",description:"Ocupanți, telefon, conversație și conținutul de la bord.",body:<Cabin s={s}/>},
    {label:"Fișă",icon:"report",description:"Concentrare, intervenții și rezultatele călătoriei.",body:<Scorecard s={s}/>},
    {label:"Sistem",icon:"chip",description:"Resurse, procesarea camerelor și latențe pe fiecare etapă.",body:<Performance s={s} samples={samples}/>},
    {label:"Jurnal",icon:"journal",description:"Evenimentele sesiunii și explicația fiecărei intervenții.",body:<EventJournal id="recent-events" events={data.log} pageSize={5} onSelect={setEventTime}/>},
    {label:"Control",icon:"sliders",description:"Comenzile pe care backendul le primește de la dashboard: călătorie, scene, asistent, camere.",body:<ControlPanel/>},
  ];
  return <InlineDetails.Provider value={true}><div className={"monitor-page"+(docked?" has-camera-dock":"")}>
    <PageHeading label="INSTRUMENTE / MONITORIZARE" title="Dashboard" description="Camere, starea șoferului și telemetria de bord"/>
    <StatusStrip s={s} connection={data.connection}/>
    <KpiStrip s={s} history={history} samples={samples}/>
    <Cameras live={live} socket={data.socket} cue={data.cue} trip={s.trip} onLive={()=>setLive(true)} onDock={setDocked}/>
    <div className="content monitor-overview">
      <Overview s={s} samples={samples} slot={<div className="camera-slot" data-camera-slot="overview" aria-hidden="true"/>}/>
      {live&&<VisionDiagnostics s={s} connection={data.connection}/>}
    </div>
    <InstrumentStack cards={cards} dock={docked}/>
  </div></InlineDetails.Provider>;
}
