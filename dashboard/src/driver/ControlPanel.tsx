// Every action the backend accepts from the dashboard, in one place (shared/contracts.py: UI_COMMANDS).
// Each button sends a UiCommand on core's /ws/ui (liveMessage in session.ts); all are disabled while core is not
// connected. Speed, time scale, scenes and the test message drive core's own trip simulator, not the dashboard.
import {useState} from "react";
import type {ReactNode} from "react";
import {useDriver} from "./context";
import {time,words} from "../Panels";

const scenes=["Pregătire și plecare","Monitorizare întreruptă","Mesaj amânat","Context pasager","Drum monoton și muzică","Oboseală și refuz","Oprire la POI","Microsomn, LLM oprit","SOS demonstrativ","Încheiere și fișă"];
const perceptionEvents=["calibration_prompt","calibrate_done","calibrate_error","enroll_done","enroll_error"];

function Group({title,hint,children}: {title: string; hint?: string; children: ReactNode}){
  return <div className="fx-control-group"><header><h3>{title}</h3>{hint&&<small>{hint}</small>}</header>{children}</div>;
}

export function ControlPanel(){
  const driver=useDriver(),{data}=driver;
  const s=driver.fresh?data.state:{},trip=s.trip;
  // Tests and stories may mount the page with a partial session: missing callbacks disable the controls.
  const can=(name: string)=>driver.can?.(name)??false;
  const run=(name: string,args?: Record<string,unknown>)=>{void driver.command?.(name,args);};
  const [message,setMessage]=useState("Salut! Mai durează mult?");
  const [speed,setSpeed]=useState<number | null>(null);
  const [profile,setProfile]=useState("andrei"),[quick,setQuick]=useState(false);
  const [person,setPerson]=useState(""),[camera,setCamera]=useState("driver");
  const [debug,setDebug]=useState(false),[confirmReset,setConfirmReset]=useState(false);
  const shownSpeed=speed??(typeof trip?.speed_kmh==="number"?Math.round(trip.speed_kmh):0);
  const child=!!s.occupants?.some(o=>o.source==="declared"&&o.role==="child");
  const rates=[1,20];
  const feedback=data.log.find(event=>perceptionEvents.includes(event.type));
  return <section id="control" className="fx-control">
    <Group title="Călătorie" hint="Comenzi către core">
      <div className="fx-actions">
        <button className="fx-primary" disabled={!can("start_trip")} onClick={()=>run("start_trip")}>Pornește</button>
        <button disabled={!can("pause_trip")} onClick={()=>run("pause_trip")}>Pauză</button>
        <button disabled={!can("stop_at_poi")} onClick={()=>run("stop_at_poi")}>Oprește la următorul POI</button>
        <button disabled={!can("end_trip")} onClick={()=>run("end_trip")}>Încheie · fișa călătoriei</button>
        {confirmReset?<span className="fx-confirm" role="group" aria-label="Confirmă resetarea">Resetezi călătoria?
          <button onClick={()=>{setConfirmReset(false);run("reset");}}>Da, resetează</button><button onClick={()=>setConfirmReset(false)}>Nu</button></span>
          :<button disabled={!can("reset")} onClick={()=>setConfirmReset(true)}>Resetează</button>}
      </div>
      <label className="fx-slider">Viteza vehiculului · simulatorul din core<input type="range" min="0" max="160" step="1" value={shownSpeed} disabled={!can("set_speed")}
        onChange={e=>setSpeed(Number(e.target.value))} onPointerUp={()=>{if(speed!==null){run("set_speed",{speed});setSpeed(null);}}}
        onKeyUp={()=>{if(speed!==null){run("set_speed",{speed});setSpeed(null);}}}/><output>{shownSpeed} km/h</output></label>
      <div className="fx-segment" role="group" aria-label="Ritmul timpului">{rates.map(rate=>
        <button key={rate} disabled={!can("set_rate")} onClick={()=>run("set_rate",{rate})}>×{rate}</button>)}
        <small>Ritmul timpului în core</small></div>
    </Group>
    <Group title="Scene demonstrative" hint={trip?.scene?"Scena "+trip.scene+" activă":"Nicio scenă activă"}>
      <div className="fx-scenes">{scenes.map((name,i)=><button key={name} disabled={!can("scene")} aria-pressed={trip?.scene===i+1} onClick={()=>run("scene",{scene:i+1})}><b>{i+1}</b>{name}</button>)}</div>
    </Group>
    <Group title="Siguranță și asistent" hint={"LLM "+(s.safety?.llm_enabled?"pornit":"oprit")+(s.safety?.llm_allowed===false?" · blocat de siguranță":"")}>
      <div className="fx-toggles">
        <label className="fx-switch"><input type="checkbox" checked={s.safety?.llm_enabled??false} disabled={!can("set_llm")} onChange={e=>run("set_llm",{enabled:e.target.checked})}/><span>LLM activ<small>Regulile de siguranță merg la fel fără el</small></span></label>
        <label className="fx-switch"><input type="checkbox" checked={child} disabled={!can("set_child")} onChange={e=>run("set_child",{enabled:e.target.checked})}/><span>Copil declarat în spate<small>Muzică și conținut potrivite</small></span></label>
      </div>
      <form className="fx-inline-form" onSubmit={e=>{e.preventDefault();if(message.trim())run("inject_message",{text:message.trim()});}}>
        <label>Mesaj de test · intră în core ca mesaj de pe telefon<input value={message} maxLength={300} onChange={e=>setMessage(e.target.value)} disabled={!can("inject_message")}/></label>
        <button type="submit" disabled={!can("inject_message")||!message.trim()}>Trimite</button>
      </form>
    </Group>
    <Group title="Percepție · camere" hint="Comenzi transmise la P1 prin core">
      <div className="fx-actions">
        <button disabled={!can("debug")} aria-pressed={debug} onClick={()=>{setDebug(!debug);run("debug",{on:!debug});}}>Overlay debug · tasta D</button>
      </div>
      <form className="fx-inline-form" onSubmit={e=>{e.preventDefault();run("calibrate",{profile,quick});}}>
        <label>Calibrare privire · profil<input value={profile} maxLength={40} onChange={e=>setProfile(e.target.value)} disabled={!can("calibrate")}/></label>
        <label className="fx-check"><input type="checkbox" checked={quick} onChange={e=>setQuick(e.target.checked)} disabled={!can("calibrate")}/>Rapidă · drum și oglinzi</label>
        <button type="submit" disabled={!can("calibrate")||!profile.trim()}>Calibrează</button>
      </form>
      <form className="fx-inline-form" onSubmit={e=>{e.preventDefault();run("enroll",{name:person,camera});}}>
        <label>Înrolare față · nume<input value={person} maxLength={40} placeholder="de exemplu maria" onChange={e=>setPerson(e.target.value)} disabled={!can("enroll")}/></label>
        <label>Cameră<select value={camera} onChange={e=>setCamera(e.target.value)} disabled={!can("enroll")}><option value="driver">Șofer</option><option value="passenger">Pasager</option></select></label>
        <button type="submit" disabled={!can("enroll")||!person.trim()}>Înrolează</button>
      </form>
      {feedback&&<p className="fx-feedback" role="status"><b>{time(feedback.ts)}</b> {words(feedback.text??feedback.explanation??feedback.type)}</p>}
    </Group>
  </section>;
}
