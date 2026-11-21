// Top of the monitoring page: status strip, KPI tiles with mini charts, and the driver overview.
// Every reading comes from core's State (P1 perception, P2 scores and safety, P3 assistant health); a missing value
// renders as "—" or an empty chart.
import type {ReactNode} from "react";
import type {DashboardState,SessionData} from "../types";
import type {Sample} from "../telemetry";
import {zoneShares} from "../telemetry";
import {Flag,Gauge,HeatStrip,MiniBars,PoseDial,RankBars,Ring,Spark,StackBar} from "../charts";
import type {Tone} from "../charts";
import {alerts,causes,drivingZones,integrationNames,integrationStates,label,monitoringReasons,phoneUsage,postures,roads,safetyLevels,sosStates,zones} from "../labels";
import {fmt,words} from "../Panels";

const known=(v: unknown): v is number=>typeof v==="number"&&Number.isFinite(v);
const levelTone=(level: string | null | undefined): Tone=>level==="P0"||level==="P1"?"danger":level==="P2"?"warn":"ok";

function Chip({title,value,tone,detail}: {title: string; value: ReactNode; tone?: Tone; detail?: string}){
  return <div className={"fx-chip"+(tone?" tone-"+tone:"")} title={detail}><i aria-hidden="true"/><span>{title}</span><b>{value}</b></div>;
}

/** One line of health: safety level, SOS, both cameras, degradation and the external integrations. */
export function StatusStrip({s,connection}: {s: DashboardState; connection: string}){
  const safety=s.safety??{},sos=safety.sos,perf=s.perf??{};
  const camera=(side: "driver" | "passenger")=>{
    const person=s[side],cam=perf.cameras?.[side];
    if(!person&&!cam)return {value:"—",tone:undefined as Tone | undefined};
    if(cam?.available===false)return {value:"Indisponibilă",tone:"danger" as Tone};
    if(person?.monitoring_ok===false)return {value:label(monitoringReasons,person.monitoring_reason??"face_lost"),tone:"warn" as Tone};
    const warning=person?.monitoring_warnings?.[0];
    return warning?{value:label(monitoringReasons,warning),tone:"warn" as Tone}:{value:"Activă",tone:"ok" as Tone};
  };
  const driver=camera("driver"),passenger=camera("passenger");
  const alert=typeof safety.alert==="object"?safety.alert?.text:safety.alert;
  return <div className="fx-status" role="status" aria-label="Starea sistemului">
    <Chip title="Siguranță" value={(safety.level??"P4")+" · "+label(safetyLevels,safety.level??"P4")+(alert?" · "+label(alerts,alert):"")} tone={levelTone(safety.level)}/>
    {sos?.state&&sos.state!=="normal"&&<Chip title="SOS" value={label(sosStates,sos.state)+(known(sos.countdown_s)?" · "+Math.max(0,Math.ceil(sos.countdown_s))+" s":"")} tone="danger"/>}
    <Chip title="Cameră șofer" value={driver.value} tone={driver.tone}/>
    <Chip title="Cameră pasager" value={passenger.value} tone={passenger.tone}/>
    {known(perf.degrade_level)&&perf.degrade_level>0&&<Chip title="Degradare" value={"Treapta "+perf.degrade_level} tone="warn" detail="Percepția a redus rata pasagerului / YOLO ca să țină latența"/>}
    <Chip title="LLM" value={safety.llm_enabled===false?"Oprit":safety.llm_allowed===false?"Blocat de siguranță":safety.llm_enabled?"Activ":"—"} tone={safety.llm_enabled===false||safety.llm_allowed===false?"warn":safety.llm_enabled?"ok":undefined}/>
    {Object.entries(s.integrations??{}).filter(([name])=>name!=="llm").map(([name,state])=>
      <Chip key={name} title={label(integrationNames,name)} value={label(integrationStates,state)} tone={state==="ok"?"ok":state==="down"?"danger":undefined}/>)}
    <Chip title="Sursă" value={connection}/>
  </div>;
}

function Tile({title,value,unit,note,tone,children}: {title: string; value: string; unit?: string; note?: ReactNode; tone?: Tone; children: ReactNode}){
  return <article className={"fx-kpi"+(tone?" tone-"+tone:"")}>
    <header><span>{title}</span>{note&&<small>{note}</small>}</header>
    <div className="fx-kpi-body"><strong>{value}{unit&&value!=="—"&&<em>{unit}</em>}</strong><div className="fx-kpi-chart">{children}</div></div>
  </article>;
}

/** Five tiles, five chart types: gauge, area, columns, ring + heat strip, area. */
export function KpiStrip({s,history,samples}: {s: DashboardState; history: SessionData["history"]; samples: Sample[]}){
  const a=s.assessment??{},eyes=s.driver?.eyes,reliable=s.driver?.monitoring_ok!==false&&eyes?.reliable!==false;
  const series=(key: "attention" | "fatigue" | "disengagement" | "risk")=>history.map(point=>point?.[key]);
  const delta=(key: "attention" | "fatigue" | "disengagement")=>{
    const values=series(key).filter(known);
    if(values.length<20)return null;
    const change=(values.at(-1)!-values.at(-20)!)*100;
    return Math.abs(change)<1?"stabil":(change>0?"+":"")+change.toFixed(0)+" pct";
  };
  const risk=a.risk;
  return <section className="fx-kpis" aria-label="Indicatori principali">
    <Tile title="Atenție" value={fmt(a.attention,"",100,0)} unit="/100" note={delta("attention")} tone={known(a.attention)&&a.attention<.4?"danger":known(a.attention)&&a.attention<.65?"warn":undefined}>
      <Gauge value={a.attention} label="Atenție, de la 0 la 100"/>
    </Tile>
    <Tile title="Oboseală" value={fmt(a.fatigue,"",100,0)} unit="/100" note={delta("fatigue")} tone={known(a.fatigue)&&a.fatigue>.7?"danger":known(a.fatigue)&&a.fatigue>.5?"warn":undefined}>
      <Spark values={series("fatigue")} max={1} label="Oboseala în ultimele mostre"/>
    </Tile>
    <Tile title="Dezinteres" value={fmt(a.disengagement,"",100,0)} unit="/100" note={delta("disengagement")} tone={known(a.disengagement)&&a.disengagement>.7?"warn":undefined}>
      <MiniBars values={series("disengagement")} max={1} label="Dezinteresul în ultimele mostre"/>
    </Tile>
    <Tile title="Risc" value={fmt(risk,"",1,0)} unit="/3" note={label(safetyLevels,s.safety?.level??"P4")} tone={known(risk)&&risk>=3?"danger":known(risk)&&risk>=2?"warn":undefined}>
      <div className="fx-kpi-pair"><Ring value={risk} max={3} size={58} label="Risc din 3"/><HeatStrip values={series("risk").slice(-40)} max={3} label="Riscul în ultimele mostre"/></div>
    </Tile>
    <Tile title="PERCLOS · 60 s" value={reliable?fmt(eyes?.perclos_60s,"",100,0):"—"} unit="%" note={reliable?"clipiri "+fmt(eyes?.blink_rate,"/min",1,0):"semnal nesigur"} tone={reliable&&known(eyes?.perclos_60s)&&eyes.perclos_60s>.15?"warn":undefined}>
      <Spark values={samples.map(sample=>sample.perclos)} max={.4} tone="soft" label="PERCLOS în ultimul minut"/>
    </Tile>
  </section>;
}

/** Driver overview: what is happening now, where the driver looked in the last minute, head pose and trip context. */
export function Overview({s,samples,slot}: {s: DashboardState; samples: Sample[]; slot?: ReactNode}){
  const safety=s.safety??{},d=s.driver??{},g=d.gaze??{},h=d.head??{},c=s.cause??{},trip=s.trip??{},eyes=d.eyes??{};
  const alert=typeof safety.alert==="object"?safety.alert?.text:safety.alert;
  const headline=safety.monitoring_ok===false?"Monitorizare întreruptă":alert?label(alerts,alert):g.zone==="road"?"Privirea pe drum":zones[g.zone??""]??"Direcție nedeterminată";
  const shares=zoneShares(samples);
  const driving=shares.filter(z=>drivingZones.has(z.zone)).reduce((sum,z)=>sum+z.share,0);
  const unknownShare=shares.filter(z=>z.zone==="unknown").reduce((sum,z)=>sum+z.share,0);
  const road=shares.find(z=>z.zone==="road")?.share??0;
  const posture=Object.entries(d.posture??{}).filter(([,on])=>on===true).map(([name])=>label(postures,name));
  return <section id="general" className="fx-overview">
    <div className="fx-overview-main">
      <header><small>STARE GENERALĂ</small><h2>{headline}</h2>
        <p>{c.label?<>Cauză · <b>{label(causes,c.label)}</b>{known(c.conf)&&" · încredere "+fmt(c.conf,"%",100,0)}{known(c.glances_30s)&&c.glances_30s>0&&" · "+c.glances_30s+" priviri în 30 s"}</>:"Nicio cauză de distragere raportată"}</p></header>
      <div className="fx-flags">
        <Flag label="Telefon" on={d.phone?.in_use} tone="danger"/>
        <Flag label="Microsomn" on={eyes.microsleep} tone="danger"/>
        <Flag label="Cădere de cap" on={h.nodding} tone="warn"/>
        <Flag label="Căscat" on={d.yawn} tone="warn"/>
        <Flag label="Ochi mijiți" on={eyes.squint}/>
        <Flag label="Vorbește" on={d.speaking}/>
        <Flag label="Tipar poală" on={g.lap_pattern} tone="warn"/>
        {posture.map(name=><Flag key={name} label={name} on tone="warn"/>)}
      </div>
      <div className="fx-overview-grid">
        <div className="fx-block"><h3>Unde privește · ultimul minut<small>{samples.length?Math.round(samples.length/2)+" s măsurate":"în așteptarea datelor"}</small></h3>
          <StackBar label="Împărțirea privirii" parts={[{label:"Drum",value:road},{label:"Oglinzi",value:Math.max(0,driving-road)},{label:"În afara drumului",value:Math.max(0,1-driving-unknownShare),tone:"warn"},{label:"Nedeterminat",value:unknownShare,tone:"soft"}]}/>
          <RankBars max={1} empty="Zonele apar după primele secunde de date" items={shares.slice(0,5).map(z=>({label:zones[z.zone]??words(z.zone),value:z.share,display:fmt(z.seconds," s",1,0),tone:z.zone==="unknown"?"soft":drivingZones.has(z.zone)?"ink":"warn"}))}/>
        </div>
        <div className="fx-block fx-pose-block"><h3>Poziția capului<small>{g.calibrated===false?"privire necalibrată":"yaw · pitch · roll"}</small></h3>
          <div className="fx-pose-row"><PoseDial yaw={h.yaw} pitch={h.pitch} roll={h.roll} label="Poziția capului față de drum"/>
            <dl className="fx-readings"><div><dt>Yaw</dt><dd>{fmt(h.yaw,"°",1,0)}</dd></div><div><dt>Pitch</dt><dd>{fmt(h.pitch,"°",1,0)}</dd></div><div><dt>Roll</dt><dd>{fmt(h.roll,"°",1,0)}</dd></div>
              <div><dt>În afara drumului</dt><dd>{fmt(g.off_road_ms," s",.001,1)}</dd></div></dl></div>
        </div>
      </div>
    </div>
    <aside className="fx-overview-rail"><div className="fx-rail-sticky">
      {slot}
      <div className="fx-block fx-context"><h3>Context<small>{label(roads,trip.road)}</small></h3>
        <dl className="fx-readings">
          <div><dt>Următoarea oprire</dt><dd>{trip.next_poi?.name??"—"}</dd></div>
          <div><dt>Până la oprire</dt><dd>{fmt(trip.next_poi?.dist_km," km")}</dd></div>
          <div><dt>Până la destinație</dt><dd>{fmt(trip.eta_min," min",1,0)}</dd></div>
          <div><dt>Telefon</dt><dd>{d.phone?.in_use?label(phoneUsage,d.phone.usage??"visible")+(d.phone.side?" · "+(d.phone.side==="left"?"stânga":"dreapta"):""):d.phone?.foreign_seen?"Al pasagerului":"Nu"}</dd></div>
          <div><dt>Ultimul răspuns</dt><dd>{words(s.interaction?.last_input?.value)}</dd></div>
          <div><dt>Gest · cap</dt><dd>{words(d.gesture)} · {h.answer==="yes"?"da":h.answer==="no"?"nu":"—"}</dd></div>
        </dl>
      </div>
    </div></aside>
  </section>;
}
