import {useEffect,useRef,useState} from "react";
import type {ReactNode} from "react";
import {motion,useMotionValue,useReducedMotion,useTransform} from "motion/react";
import type {MotionValue} from "motion/react";
import {Icon} from "../App";

export interface Instrument {label:string;icon:string;description:string;body:ReactNode}

const MIN_STAGE=560; // below this viewport height the cards use ordinary document flow
const BAND=104;      // px under the cards: docked camera preview, progress, previous / next
const CHROME=34;     // stage padding + gap between the cards and the band
const STEP=.62;   // scroll distance per card, as a share of the viewport height
const SNAP_MS=260;  // fallback idle time before settling, where scrollend is missing

function StackCard({card,index,count,position,stacked,active}:{card:Instrument;index:number;count:number;position:MotionValue<number>;stacked:boolean;active:number}){
  // The incoming card slides in from the right and covers the previous one, which recedes a little.
  const x=useTransform(position,value=>index===0?"0%":`${104*Math.max(0,Math.min(1,index-value))}%`);
  const scale=useTransform(position,value=>1-.045*Math.max(0,Math.min(1,value-index)));
  const dim=useTransform(position,value=>1-.5*Math.max(0,Math.min(1,value-index)));
  const visibility=useTransform(position,value=>index<=Math.floor(value)+1&&index>=Math.floor(value)-1?"visible":"hidden");
  return <motion.article className="instrument-card" aria-label={card.label} data-instrument={card.icon}
    inert={stacked&&index!==active} aria-hidden={stacked&&index!==active?true:undefined}
    style={stacked?{x,scale,opacity:dim,visibility,zIndex:index+1}:{zIndex:index+1}}>
    <header className="instrument-label"><span className="instrument-icon"><Icon name={card.icon}/></span>
      <div><small>MONITOR DE BORD · {String(index+1).padStart(2,"0")} / {String(count).padStart(2,"0")}</small><h2>{card.label}</h2><p>{card.description}</p></div>
    </header>
    <div className="instrument-body">{card.body}</div>
  </motion.article>;
}

// Sequential right-to-left cover driven by the page scroll. Scroll progress drives only transforms; telemetry is
// never interpolated. The stage is as tall as the viewport, so the travel (count - 1 steps) is always reachable and
// the last card arrives completely; when scrolling stops between two cards the page settles on the nearest one.
export function InstrumentStack({cards,dock=false}:{cards:Instrument[];dock?:boolean}){
  const scene=useRef<HTMLDivElement>(null),rail=useRef<HTMLDivElement>(null);
  const position=useMotionValue(0),reduced=useReducedMotion();
  const [active,setActive]=useState(0),[layout,setLayout]=useState({stacked:false,stage:720,step:440,rail:560});
  const count=cards.length;
  useEffect(()=>{
    const area=scene.current,track=rail.current,page=area?.closest<HTMLElement>(".dashboard");
    if(!area||!track||!page)return;
    let frame=0,settle:ReturnType<typeof setTimeout>|undefined;
    // Settle only when scrolling has really ended (scrollend also waits for a smooth programmatic scroll to finish);
    // an idle timer is the fallback for browsers without the event.
    const hasScrollEnd="onscrollend" in window;
    function measure(){
      if(!track||!page)return;
      const stage=page.clientHeight;
      // Narrow or very short screens and reduced motion use ordinary document flow. All cards share the height of
      // the tallest one (a card must cover the previous one); a card taller than the stage scrolls inside its own
      // body (fluid.css), so the stack never falls apart because of one long card.
      const stacked=!reduced&&page.clientWidth>=900&&stage>=MIN_STAGE;
      const tallest=Math.ceil(Math.max(0,...Array.from(track.children,card=>{
        const head=card.querySelector<HTMLElement>(".instrument-label"),body=card.querySelector<HTMLElement>(".instrument-body");
        return (head?.offsetHeight??0)+(body?.scrollHeight??0)+2;
      })));
      const rail=Math.max(320,Math.min(tallest,stage-BAND-CHROME));
      const step=Math.round(stage*STEP);
      setLayout(old=>old.stage===stage&&old.stacked===stacked&&old.step===step&&old.rail===rail?old:{stacked,stage,step,rail});
    }
    const observer=new ResizeObserver(measure);
    observer.observe(page);
    track.querySelectorAll(".instrument-label,.instrument-body").forEach(el=>observer.observe(el));
    const offset=()=>page.getBoundingClientRect().top-area.getBoundingClientRect().top;
    function sync(){
      frame=0;
      const value=Math.min(count-1,Math.max(0,offset()/layout.step));
      position.set(value);
      setActive(Math.round(value));
    }
    function snap(){
      if(!layout.stacked||!page)return;
      const distance=offset(),travel=(count-1)*layout.step;
      if(distance<=0||distance>=travel)return;  // outside the stack: never hijack the page scroll
      const target=Math.round(distance/layout.step)*layout.step;
      if(Math.abs(target-distance)<2)return;
      page.scrollTo({top:page.scrollTop+target-distance,behavior:"smooth"});
    }
    function scroll(){
      if(!frame)frame=requestAnimationFrame(sync);
      if(!hasScrollEnd){clearTimeout(settle);settle=setTimeout(snap,SNAP_MS);}
    }
    measure();sync();
    page.addEventListener("scroll",scroll,{passive:true});
    if(hasScrollEnd)page.addEventListener("scrollend",snap);
    window.addEventListener("resize",scroll);
    return ()=>{observer.disconnect();page.removeEventListener("scroll",scroll);page.removeEventListener("scrollend",snap);window.removeEventListener("resize",scroll);cancelAnimationFrame(frame);clearTimeout(settle);};
  },[count,reduced,layout.stage,layout.step,layout.stacked,position]);

  function select(index:number){
    const area=scene.current,page=area?.closest<HTMLElement>(".dashboard");
    if(!area||!page)return;
    const start=page.scrollTop+area.getBoundingClientRect().top-page.getBoundingClientRect().top;
    page.scrollTo({top:start+Math.max(0,Math.min(count-1,index))*layout.step,behavior:"smooth"});
  }
  return <div ref={scene} className={"instrument-scene"+(layout.stacked?" is-stacked":" is-flow")+(dock?" has-dock":"")}
    style={layout.stacked?{height:layout.stage+(count-1)*layout.step}:undefined}>
    <div className="instrument-stage" style={layout.stacked?{height:layout.stage,gridTemplateRows:`${layout.rail}px ${BAND}px`}:undefined}>
      <div ref={rail} className="instrument-rail" role="region" aria-label="Instrumente de monitorizare">
        {cards.map((card,index)=><StackCard key={card.label} {...{card,index,count,position,stacked:layout.stacked,active}}/>)}
      </div>
      {layout.stacked&&<div className="instrument-band">
        <div className="camera-slot" data-camera-slot="stack" aria-hidden="true"/>
        <div className="instrument-controls">
          <span aria-live="polite"><b>{String(active+1).padStart(2,"0")}</b> / {String(count).padStart(2,"0")}<strong>{cards[active].label}</strong></span>
          <div className="instrument-progress" role="tablist" aria-label="Instrumentele monitorului">{cards.map((card,i)=>
            <button key={card.label} role="tab" aria-selected={i===active} aria-label={card.label} title={card.label} data-active={i<=active} onClick={()=>select(i)}/>)}</div>
          <button className="instrument-step" aria-label="Cardul anterior" disabled={active===0} onClick={()=>select(active-1)}>←</button>
          <button className="instrument-step" aria-label="Cardul următor" disabled={active===count-1} onClick={()=>select(active+1)}>→</button>
        </div>
      </div>}
    </div>
  </div>;
}
