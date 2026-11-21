import {useEffect,useRef,useState} from "react";
import type {ReactNode} from "react";
import {motion,useMotionValue,useReducedMotion,useTransform} from "motion/react";
import type {MotionValue} from "motion/react";
import {Icon} from "../App";

export interface Instrument {label:string;icon:string;description:string;body:ReactNode}

function StackCard({card,index,position,stacked,active}:{card:Instrument;index:number;position:MotionValue<number>;stacked:boolean;active:number}){
  const x=useTransform(position,value=>index===0?"0%":`${110*Math.max(0,Math.min(1,index-value))}%`);
  const visibility=useTransform(position,value=>index<=Math.floor(value)+1?"visible":"hidden");
  return <motion.article className="instrument-card" aria-label={card.label} data-instrument={card.icon}
    inert={stacked&&index!==active} aria-hidden={stacked&&index!==active?true:undefined}
    style={{x:stacked?x:0,visibility:stacked?visibility:"visible",zIndex:index+1}}>
    <header className="instrument-label"><span className="instrument-icon"><Icon name={card.icon}/></span>
      <div><small>MONITOR DE BORD · {String(index+1).padStart(2,"0")}</small><h2>{card.label}</h2><p>{card.description}</p></div>
    </header>
    <div className="instrument-body">{card.body}</div>
  </motion.article>;
}

// Sequential right-to-left cover, adapted from the user's stacked-cards demo.
// Scroll progress drives only transforms; telemetry is never interpolated.
export function InstrumentStack({cards}:{cards:Instrument[]}){
  const scene=useRef<HTMLDivElement>(null),rail=useRef<HTMLDivElement>(null);
  const position=useMotionValue(0),reduced=useReducedMotion();
  const [active,setActive]=useState(0),[layout,setLayout]=useState({stacked:false,height:600});
  const count=cards.length;
  useEffect(()=>{
    const area=scene.current,track=rail.current,page=area?.closest<HTMLElement>(".dashboard");
    if(!area||!track||!page)return;
    let frame=0;
    function measure(){
      if(!track||!page)return;
      const height=Math.ceil(Math.max(...Array.from(track.children,card=>{
        const head=card.querySelector<HTMLElement>(".instrument-label"),body=card.querySelector<HTMLElement>(".instrument-body");
        return (head?.offsetHeight??0)+(body?.offsetHeight??0)+2;
      })))+76;
      // Tall content, zoom, mobile and reduced motion use ordinary document flow.
      const stacked=!reduced&&page.clientWidth>=900&&height<=page.clientHeight-8;
      setLayout(old=>old.height===height&&old.stacked===stacked?old:{height,stacked});
    }
    const observer=new ResizeObserver(measure);
    observer.observe(page);
    track.querySelectorAll(".instrument-label,.instrument-body").forEach(el=>observer.observe(el));
    function sync(){
      frame=0;
      if(!area||!page)return;
      const travel=Math.max(1,area.offsetHeight-layout.height);
      const distance=page.getBoundingClientRect().top-area.getBoundingClientRect().top;
      const value=Math.min(count-1,Math.max(0,distance/travel*(count-1)));
      position.set(value);
      setActive(Math.min(count-1,Math.floor(value+0.0001)));
    }
    function scroll(){if(!frame)frame=requestAnimationFrame(sync);}
    measure();sync();
    page.addEventListener("scroll",scroll,{passive:true});
    window.addEventListener("resize",scroll);
    return ()=>{observer.disconnect();page.removeEventListener("scroll",scroll);window.removeEventListener("resize",scroll);cancelAnimationFrame(frame);};
  },[count,reduced,layout.height,layout.stacked,position]);

  function select(index:number){
    const area=scene.current,page=area?.closest<HTMLElement>(".dashboard");
    if(!area||!page)return;
    const start=page.scrollTop+area.getBoundingClientRect().top-page.getBoundingClientRect().top;
    page.scrollTo({top:start+index*(area.offsetHeight-layout.height)/Math.max(1,count-1),behavior:"instant"});
  }
  return <div ref={scene} className={"instrument-scene"+(layout.stacked?" is-stacked":" is-flow")}
    style={layout.stacked?{height:`calc(${layout.height}px + ${count-1} * 85svh)`}:undefined}>
    <div className="instrument-stage" style={layout.stacked?{height:layout.height}:undefined}>
      <div ref={rail} className="instrument-rail" role="region" aria-label="Instrumente de monitorizare">
        {cards.map((card,index)=><StackCard key={card.label} {...{card,index,position,stacked:layout.stacked,active}}/>)}
      </div>
      {layout.stacked&&<div className="instrument-controls">
        <span aria-live="polite">{String(active+1).padStart(2,"0")} / {String(count).padStart(2,"0")} <strong>{cards[active].label}</strong></span>
        <div className="instrument-progress" aria-hidden="true">{cards.map((card,i)=><i key={card.label} data-active={i<=active}/>)}</div>
        <button aria-label="Cardul anterior" disabled={active===0} onClick={()=>select(active-1)}>←</button>
        <button aria-label="Cardul următor" disabled={active===count-1} onClick={()=>select(active+1)}>→</button>
      </div>}
    </div>
  </div>;
}
