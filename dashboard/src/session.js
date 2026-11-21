import {useEffect, useState} from "react";
import example from "../../tests/assistant/fixtures/state_example.json";

export const videoOrigin = import.meta.env.VITE_VIDEO_ORIGIN || "http://localhost:8001";
const wsUrl = import.meta.env.VITE_UI_WS || "ws://localhost:8000/ws/ui";

function sample(t) {
  const mirror = t%120 >= 95, wave = Math.sin(t/15);
  return {...example,ts:Date.now()/1000,seq:t,
    driver:{...example.driver,eyes:{...example.driver.eyes,ear:.27+.02*wave},
      gaze:{...example.driver.gaze,zone:mirror?"mirror_left":"road",off_road_ms:mirror?(t%120-95)*100:0},
      reaction:{...example.driver.reaction,visual_ms:Math.floor(t/50)%2?560:650}},
    assessment:{attention:mirror ? .68 : .84+.04*wave,fatigue:.29+.03*Math.sin(t/30),disengagement:.36+.05*wave,risk:1},
    perf:{cameras:{driver:{capture_fps:30,process_fps:24,dropped_frames:3},passenger:{capture_fps:25,process_fps:10,dropped_frames:1}},
      face_driver_ms_p50:9,face_passenger_ms_p50:8,e2e_ms_p95:95,cpu:61,ram_mb:2100,gpu:35}};
}
const empty = {state:{},history:[],log:[],socket:null,cue:0,speech:"",connection:"Se conectează"};
function withState(old,state){
  const gap=Number.isFinite(old.state.seq)&&Number.isFinite(state.seq)&&state.seq!==old.state.seq+1;
  return {...old,state,history:[...old.history,...(gap?[null]:[]),state.assessment].slice(-120)};
}
function appendEvent(old,event) {
  return {...old,log:[event,...old.log].slice(0,60),cue:old.cue+(event.type==="visual_cue"?1:0)};
}
export function useSession(live) {
  const [data,set]=useState(empty);
  useEffect(()=>{
    if(!live){
      let tick=120;
      set({...empty,state:sample(119),connection:"Sesiune simulată",
        history:Array.from({length:120},(_,t)=>sample(t).assessment),
        speech:"Îți citesc mesajul când e momentul potrivit."});
      const timer=setInterval(()=>{
        const t=tick++, state=sample(t);
        set(old=>{
          const next=withState(old,state);
          if(t%120!==95)return next;
          return appendEvent(next,{type:"visual_cue",source:"REGULĂ",text:"Semnal discret de probă",ts:state.ts});
        });
      },100);
      return ()=>clearInterval(timer);
    }
    let disposed=false, ws, retry, last=0;
    function connect(){
      ws=new WebSocket(wsUrl);
      ws.onopen=()=>{if(!disposed)set({...empty,socket:ws,connection:"Live · așteaptă date"});};
      ws.onmessage=({data:raw})=>{
        if(disposed)return;
        let m;try{m=JSON.parse(raw);}catch{return;}
        if(m?.type==="state" && m.state && typeof m.state==="object" && !Array.isArray(m.state)){
          last=Date.now();set(old=>({...withState(old,m.state),connection:"Live · conectat"}));return;
        }
        if(!["event","alarm","speak","media","speak_control"].includes(m?.type))return;
        const ev=typeof m.event==="object" && m.event ? m.event : m;
        const event={...ev.data,...ev,type:typeof m.event==="string"?m.event:ev.type,ts:ev.ts??Date.now()/1000};
        set(old=>({...appendEvent(old,event),speech:m.type==="speak" && typeof m.text==="string"?m.text:old.speech}));
      };
      ws.onclose=()=>{if(disposed)return;last=0;set({...empty,connection:"Live · reconectare"});retry=setTimeout(connect,1800);};
    }
    set(empty);connect();
    const watchdog=setInterval(()=>{if(last && Date.now()-last>2000){
      last=0;set(old=>({...old,state:{},history:[],connection:"Live · date neactualizate"}));
    }},500);
    return ()=>{disposed=true;clearTimeout(retry);clearInterval(watchdog);ws.close();};
  },[live]);
  return data;
}
