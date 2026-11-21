import {useEffect,useRef,useState} from "react";
import {Cameras,Eyes,General,Icon,Reaction} from "../App";
import {Cabin,Performance,Scorecard,VisionDiagnostics,fmt,time,yes} from "../Panels";
import {ScoreHistory} from "../ScoreHistory";
import {EventJournal} from "./EventJournal";
import {useDriver} from "./context";
import "./monitor-layout.css";
import {PageHeading} from "./DrivingPages";

// MiniStatisticsCard adapted from Vision UI Free React, Simmmple & Creative Tim (MIT).
function MiniStatisticsCard({title,count}:{title:string;count:string}){
  return <div className="vision-stat"><small>{title}</small><strong>{count}</strong></div>;
}
export function MonitorPage(){
  const {data,live,setLive,fresh}=useDriver();
  const s=live && !fresh?{}:data.state,p=s.perf??{};
  const [docked,setDocked]=useState(false);
  const [eventTime,setEventTime]=useState<number>();
  const rail=useRef<HTMLDivElement>(null);
  const eyes=s.driver?.monitoring_ok!==false && p.cameras?.driver?.available!==false && s.driver?.eyes?.reliable?s.driver.eyes:undefined;
  const scores=s.assessment,reaction=s.driver?.reaction,report=s.scorecard;
  const latest=data.log[0];
  const cards=[
    {label:"Scoruri",icon:"chart",metrics:[["Atenție",fmt(scores?.attention," / 100",100,0)],["Oboseală",fmt(scores?.fatigue," / 100",100,0)],["Dezinteres",fmt(scores?.disengagement," / 100",100,0)]],body:<ScoreHistory points={data.history} sectionId="score-history" eventTime={eventTime}/>},
    {label:"Privire",icon:"eye",metrics:[["PERCLOS · 60 s",fmt(eyes?.perclos_60s,"%",100)],["Ultima clipire",fmt(eyes?.blink_ms," ms")],["Închidere curentă",fmt(eyes?.closed_ms," ms")]],body:<Eyes s={s} live={live}/>},
    {label:"Reacție",icon:"pulse",metrics:[["Răspuns vizual",fmt(reaction?.visual_ms," ms")],["Răspuns verbal",fmt(reaction?.verbal_ms," ms")],["Răspuns prin gest",fmt(reaction?.gesture_ms," ms")]],body:<Reaction s={s}/>},
    {label:"Cabină",icon:"cabin",metrics:[["Ocupanți",fmt(s.occupants?.length)],["Telefon conectat",yes(s.phone?.connected)],["Baterie telefon",fmt(s.phone?.battery,"%")]],body:<Cabin s={s}/>},
    {label:"Fișă",icon:"report",metrics:[["Concentrare maximă",fmt(report?.longest_focus_min," min")],["Mesaje fără mâini",fmt(report?.hands_free_messages)],["Atingeri telefon",fmt(report?.phone_touches)]],body:<Scorecard s={s}/>},
    {label:"Sistem",icon:"chip",metrics:[["Captură → publicare · p95",fmt(p.e2e_ms_p95," ms")],["Procesare șofer",fmt(p.cameras?.driver?.process_fps," fps")],["Procesare pasager",fmt(p.cameras?.passenger?.process_fps," fps")]],body:<Performance s={s}/>},
    {label:"Jurnal",icon:"journal",metrics:[["Evenimente în jurnal",fmt(data.log.length)],["Ultimul eveniment",latest?.type??"—"],["Ora",time(latest?.ts)]],body:<EventJournal id="recent-events" events={data.log} onSelect={setEventTime}/>},
  ];
  const dialog=useRef<HTMLDialogElement>(null);
  const [detail,setDetail]=useState(0);
  const scene=useRef<HTMLDivElement>(null);
  const pinned=useRef<HTMLDivElement>(null);
  const [active,setActive]=useState(0);
  const count=cards.length;

  useEffect(()=>{
    const area=scene.current, track=rail.current, stage=pinned.current;
    const page=area?.closest<HTMLElement>(".dashboard");
    if(!area || !track || !stage || !page)return;
    const reduced=matchMedia("(prefers-reduced-motion: reduce)");
    function sync(){
      if(!area || !track || !stage || !page)return;
      const distance=page.getBoundingClientRect().top-area.getBoundingClientRect().top;
      const travel=Math.max(1,area.offsetHeight-stage.offsetHeight);
      const position=Math.min(1,Math.max(0,distance/travel))*(count-1);
      const current=Math.round(position);
      track.scrollLeft=(reduced.matches?current:position)*track.clientWidth;
      setActive(current);
    }
    const resize=new ResizeObserver(sync);
    resize.observe(area);resize.observe(stage);resize.observe(page);
    page.addEventListener("scroll",sync,{passive:true});
    reduced.addEventListener("change",sync);
    sync();
    return ()=>{
      resize.disconnect();page.removeEventListener("scroll",sync);
      reduced.removeEventListener("change",sync);
    };
  },[count]);

  function selectCard(index:number){
    const area=scene.current, stage=pinned.current;
    const page=area?.closest<HTMLElement>(".dashboard");
    if(!area || !stage || !page)return;
    const start=page.scrollTop+area.getBoundingClientRect().top-page.getBoundingClientRect().top;
    page.scrollTo({top:start+index*(area.offsetHeight-stage.offsetHeight)/(count-1),behavior:"instant"});
  }
  return <div className={"monitor-page"+(docked?" has-camera-dock":"")}>
    <PageHeading label="INSTRUMENTE / MONITORIZARE" title="Dashboard" description="Camere și telemetrie de bord"/>
    <Cameras live={live} socket={data.socket} cue={data.cue} trip={s.trip} onLive={()=>setLive(true)} onDock={setDocked}/>
    <section className="perf"><span>Performanță</span>{[["FPS șofer",fmt(p.cameras?.driver?.process_fps)],["FPS pasager",fmt(p.cameras?.passenger?.process_fps)],["p95 captură → publicare",fmt(p.e2e_ms_p95," ms")],["Ultima alarmă",fmt(s.safety?.alarm_ms_last??p.alarm_ms_last," ms")]].map(([name,value])=><MiniStatisticsCard key={name} title={name} count={value}/>)}</section>
    <div className="content monitor-overview"><General s={s} points={data.history}/>
      {live&&<VisionDiagnostics s={s} connection={data.connection}/>}
    </div>
    <div ref={scene} className="instrument-scene" style={{height:`calc(var(--stage-height) + ${count-1} * 85svh)`}}>
    <div ref={pinned} className="instrument-stage">
    <nav className="instrument-nav" aria-label="Alege instrumentul">{cards.map(({label,icon},i)=>
      <button key={label} aria-current={active===i?"step":undefined} onClick={()=>selectCard(i)}><Icon name={icon}/>{label}</button>)}</nav>
    <div ref={rail} className="instrument-rail" role="region" aria-label="Instrumente de monitorizare">
      {cards.map(({label,icon,metrics},i)=><article className="instrument-card" aria-label={label} key={label} inert={i!==active} tabIndex={i===active?0:-1}
        onKeyDown={e=>{
          if(e.target!==e.currentTarget)return;
          if(e.key==="ArrowRight"||e.key==="ArrowLeft"){
            e.preventDefault();
            const next=Math.max(0,Math.min(count-1,i+(e.key==="ArrowRight"?1:-1)));
            selectCard(next);
            requestAnimationFrame(()=>(rail.current?.children[next] as HTMLElement)?.focus({preventScroll:true}));
          }
        }}>
        <div className="instrument-label"><Icon name={icon}/>{label}
          <button className="instrument-open" aria-label={"Detalii · "+label} aria-haspopup="dialog" onClick={()=>{setDetail(i);dialog.current?.showModal();}}>Detalii ↗</button>
        </div>
        <dl className="instrument-summary">{metrics.map(([name,value])=><div key={name}><dt>{name}</dt><dd title={value}>{value}</dd></div>)}</dl>
      </article>)}
    </div>
    </div></div>
    <dialog className="instrument-dialog" ref={dialog} aria-label={"Detalii · "+cards[detail].label}>
      <header><strong>{cards[detail].label}</strong><button onClick={()=>dialog.current?.close()}>Închide</button></header>
      {cards[detail].body}
    </dialog>
  </div>;
}
