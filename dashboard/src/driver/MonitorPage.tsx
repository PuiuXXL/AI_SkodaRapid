import {useState} from "react";
import {Cameras,Eyes,Reaction} from "../App";
import {Cabin,InlineDetails,Performance,Rows,Scorecard,VisionDiagnostics,fmt,time,words} from "../Panels";
import {ScoreHistory} from "../ScoreHistory";
import {EventJournal} from "./EventJournal";
import {InstrumentStack, type Instrument} from "./InstrumentStack";
import {ControlPanel} from "./ControlPanel";
import {KpiStrip,Overview,StatusStrip} from "./MonitorParts";
import {useDriver} from "./context";
import {PageHeading} from "./PageHeading";
import {useTelemetry} from "../telemetry";
import {causes,label,safetyLevels} from "../labels";
import "./monitor-layout.css";

export function MonitorPage(){
  const {data,fresh}=useDriver();
  // Stale or missing data is shown as no data, never as the last values received.
  const s=fresh?data.state:{};
  const [docked,setDocked]=useState(false),[eventTime,setEventTime]=useState<number>();
  const history=fresh?data.history:[];
  const samples=useTelemetry(s);
  const cards: Instrument[]=[
    {label:"Scores",icon:"chart",description:"Attention, fatigue and disengagement on a shared timeline.",body:<>
      <ScoreHistory points={history} sectionId="score-history" eventTime={eventTime}/>
      <div className="score-context"><h3>Assessment context</h3><Rows items={[["Safety level",(s.safety?.level??"—")+" · "+label(safetyLevels,s.safety?.level)],["Reported risk",fmt(s.assessment?.risk," / 3")],["Cause",label(causes,s.cause?.label)],["Cause confidence",fmt(s.cause?.conf,"%",100)],["Last intervention",words(s.intervention?.last)],["Measured effect",fmt(s.intervention?.effect_pct,"%")],["Last update",time(s.ts)],["Available samples",fmt(history.filter(Boolean).length)]]}/></div>
    </>},
    {label:"Gaze",icon:"eye",description:"Gaze direction, eyelids and eye-tracking quality.",body:<Eyes s={s} samples={samples}/>},
    {label:"Response",icon:"pulse",description:"Driver responses compared with a personal baseline.",body:<Reaction s={s}/>},
    {label:"Cabin",icon:"cabin",description:"Occupants, phone, conversation and in-car content.",body:<Cabin s={s}/>},
    {label:"Trip report",icon:"report",description:"Focus, interventions and trip outcomes.",body:<Scorecard s={s}/>},
    {label:"System",icon:"chip",description:"Resources, camera processing and latency at each stage.",body:<Performance s={s} samples={samples}/>},
    {label:"Journal",icon:"journal",description:"Session events and the reason behind each intervention.",body:<EventJournal id="recent-events" events={data.log} pageSize={5} onSelect={setEventTime}/>},
    {label:"Control",icon:"sliders",description:"Trip, demo scenarios, assistant and camera controls.",body:<ControlPanel/>},
  ];
  return <InlineDetails.Provider value={true}><div className={"monitor-page"+(docked?" has-camera-dock":"")}>
    <PageHeading label="TOOLS / MONITORING" title="Dashboard" description="Driver awareness, cameras and vehicle telemetry."/>
    <StatusStrip s={s} connection={data.connection}/>
    <KpiStrip s={s} history={history} samples={samples}/>
    <Cameras socket={data.socket} cue={data.cue} trip={s.trip} onDock={setDocked}/>
    <div className="content monitor-overview">
      <Overview s={s} samples={samples} slot={<div className="camera-slot" data-camera-slot="overview" aria-hidden="true"/>}/>
      <VisionDiagnostics s={s} connection={data.connection}/>
    </div>
    <InstrumentStack cards={cards} dock={docked}/>
  </div></InlineDetails.Provider>;
}
