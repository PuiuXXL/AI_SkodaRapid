// Every action the backend accepts from the dashboard, in one place (shared/contracts.py: UI_COMMANDS).
// Each button sends a UiCommand on core's /ws/ui (liveMessage in session.ts); all are disabled while core is not
// connected. Speed, time scale, scenes and the test message drive core's own trip simulator, not the dashboard.
import {CardArt, type ArtSubject} from "../CardArt";
import {useState} from "react";
import type {ReactNode} from "react";
import {useDriver} from "./context";
import {time,words} from "../Panels";

const scenes=["Prepare and depart","Monitoring interrupted","Deferred message","Passenger context","Monotonous drive and music","Fatigue and refusal","Stop at a point of interest","Microsleep, LLM disabled","SOS demo","Finish and report"];
const perceptionEvents=["calibration_prompt","calibrate_done","calibrate_error","enroll_done","enroll_error"];

function Group({art,title,hint,children}: {art: ArtSubject; title: string; hint?: string; children: ReactNode}){
  return <div className="fx-control-group"><header><CardArt subject={art}/><div><h3>{title}</h3>{hint&&<small>{hint}</small>}</div></header>{children}</div>;
}

export function ControlPanel(){
  const driver=useDriver(),{data}=driver;
  const s=driver.fresh?data.state:{},trip=s.trip;
  // Tests and stories may mount the page with a partial session: missing callbacks disable the controls.
  const can=(name: string)=>driver.can?.(name)??false;
  const run=(name: string,args?: Record<string,unknown>)=>{void driver.command?.(name,args);};
  const [message,setMessage]=useState("Hi! How much longer?");
  const [speed,setSpeed]=useState<number | null>(null);
  const [profile,setProfile]=useState("andrei"),[quick,setQuick]=useState(false);
  const [person,setPerson]=useState(""),[camera,setCamera]=useState("driver");
  const [debug,setDebug]=useState(false),[confirmReset,setConfirmReset]=useState(false);
  const shownSpeed=speed??(typeof trip?.speed_kmh==="number"?Math.round(trip.speed_kmh):0);
  const child=!!s.occupants?.some(o=>o.source==="declared"&&o.role==="child");
  const rates=[1,20];
  const feedback=data.log.find(event=>perceptionEvents.includes(event.type));
  return <section id="control" className="fx-control">
    <Group art="car" title="Trip" hint="Core controls">
      <div className="fx-actions">
        <button className="fx-primary" disabled={!can("start_trip")} onClick={()=>run("start_trip")}>Start</button>
        <button disabled={!can("pause_trip")} onClick={()=>run("pause_trip")}>Pause</button>
        <button disabled={!can("stop_at_poi")} onClick={()=>run("stop_at_poi")}>Stop at the next point of interest</button>
        <button disabled={!can("end_trip")} onClick={()=>run("end_trip")}>End trip and view report</button>
        {confirmReset?<span className="fx-confirm" role="group" aria-label="Confirm reset">Reset this trip?
          <button onClick={()=>{setConfirmReset(false);run("reset");}}>Yes, reset</button><button onClick={()=>setConfirmReset(false)}>No</button></span>
          :<button disabled={!can("reset")} onClick={()=>setConfirmReset(true)}>Reset</button>}
      </div>
      <label className="fx-slider">Vehicle speed · core simulator<input type="range" min="0" max="160" step="1" value={shownSpeed} disabled={!can("set_speed")}
        onChange={e=>setSpeed(Number(e.target.value))} onPointerUp={()=>{if(speed!==null){run("set_speed",{speed});setSpeed(null);}}}
        onKeyUp={()=>{if(speed!==null){run("set_speed",{speed});setSpeed(null);}}}/><output>{shownSpeed} km/h</output></label>
      <div className="fx-segment" role="group" aria-label="Time scale">{rates.map(rate=>
        <button key={rate} disabled={!can("set_rate")} onClick={()=>run("set_rate",{rate})}>×{rate}</button>)}
        <small>Simulation speed</small></div>
    </Group>
    <Group art="sliders" title="Demo scenarios" hint={trip?.scene?"Scenario "+trip.scene+" active":"No active scenario"}>
      <div className="fx-scenes">{scenes.map((name,i)=><button key={name} disabled={!can("scene")} aria-pressed={trip?.scene===i+1} onClick={()=>run("scene",{scene:i+1})}><b>{i+1}</b>{name}</button>)}</div>
    </Group>
    <Group art="conversation" title="Safety & assistant" hint={"LLM "+(s.safety?.llm_enabled?"on":"off")+(s.safety?.llm_allowed===false?" · blocked by safety":"")}>
      <div className="fx-toggles">
        <label className="fx-switch"><input type="checkbox" checked={s.safety?.llm_enabled??false} disabled={!can("set_llm")} onChange={e=>run("set_llm",{enabled:e.target.checked})}/><span>LLM enabled<small>Safety rules run independently</small></span></label>
        <label className="fx-switch"><input type="checkbox" checked={child} disabled={!can("set_child")} onChange={e=>run("set_child",{enabled:e.target.checked})}/><span>Child in rear seat<small>Age-appropriate music and content</small></span></label>
      </div>
      <form className="fx-inline-form" onSubmit={e=>{e.preventDefault();if(message.trim())run("inject_message",{text:message.trim()});}}>
        <label>Test message · sent to core as a phone message<input value={message} maxLength={300} onChange={e=>setMessage(e.target.value)} disabled={!can("inject_message")}/></label>
        <button type="submit" disabled={!can("inject_message")||!message.trim()}>Send</button>
      </form>
    </Group>
    <Group art="camera" title="Perception · cameras" hint="Commands sent to perception through core">
      <div className="fx-actions">
        <button disabled={!can("debug")} aria-pressed={debug} onClick={()=>{setDebug(!debug);run("debug",{on:!debug});}}>Debug overlay · D key</button>
      </div>
      <form className="fx-inline-form" onSubmit={e=>{e.preventDefault();run("calibrate",{profile,quick});}}>
        <label>Gaze calibration · profile<input value={profile} maxLength={40} onChange={e=>setProfile(e.target.value)} disabled={!can("calibrate")}/></label>
        <label className="fx-check"><input type="checkbox" checked={quick} onChange={e=>setQuick(e.target.checked)} disabled={!can("calibrate")}/>Quick · road and mirrors</label>
        <button type="submit" disabled={!can("calibrate")||!profile.trim()}>Calibrate</button>
      </form>
      <form className="fx-inline-form" onSubmit={e=>{e.preventDefault();run("enroll",{name:person,camera});}}>
        <label>Face enrolment · name<input value={person} maxLength={40} placeholder="e.g. Maria" onChange={e=>setPerson(e.target.value)} disabled={!can("enroll")}/></label>
        <label>Camera<select value={camera} onChange={e=>setCamera(e.target.value)} disabled={!can("enroll")}><option value="driver">Driver</option><option value="passenger">Passenger</option></select></label>
        <button type="submit" disabled={!can("enroll")||!person.trim()}>Enrol</button>
      </form>
      {feedback&&<p className="fx-feedback" role="status"><b>{time(feedback.ts)}</b> {words(feedback.text??feedback.explanation??feedback.type)}</p>}
    </Group>
  </section>;
}
