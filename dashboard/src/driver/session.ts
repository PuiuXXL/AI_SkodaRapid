// The dashboard's only data source: core's /ws/ui (shared/contracts.py). State at 10 Hz, events, speech and alarms
// in; commands and speech out. There is no simulated source: without core the pages show "no data" and say why.
import {useCallback,useEffect,useRef,useState} from "react";
import type {DashboardEvent,DashboardState,SessionData} from "../types";
import {appendEvent,withState} from "../session-state";

export const uiSocketUrl=import.meta.env.VITE_UI_WS||"ws://localhost:8000/ws/ui";
/** P1's MJPEG server (perception/stream.py): /video/driver, /video/passenger. */
export const videoOrigin=import.meta.env.VITE_VIDEO_ORIGIN||"http://localhost:8001";

const empty:SessionData={state:{},history:[],log:[],socket:null,cue:0,speech:"",connection:"Se conectează la core"};
const STALE_MS=2500,RETRY_MS=1800;

export function useDriverSession() {
  const [data,setData]=useState<SessionData>(empty);
  const [fresh,setFresh]=useState(false),[error,setError]=useState("");
  const current=useRef({data,fresh});current.current={data,fresh};
  useEffect(()=>{
    let disposed=false,last=0,retry:ReturnType<typeof setTimeout>|undefined;
    let ws:WebSocket|undefined;
    function receive(packet:any) {
      if(disposed)return;
      if(packet.type==="state"){
        if(!packet.state||typeof packet.state!=="object"||Array.isArray(packet.state))return;
        last=Date.now();setFresh(true);
        setData(old=>({...withState(old,packet.state),socket:ws??null,connection:"Conectat la core"}));
      }else if(["event","alarm","speak","media","speak_control"].includes(packet.type)){
        const raw=typeof packet.event==="object"?packet.event:packet;
        const event:DashboardEvent={...raw.data,...raw,type:typeof packet.event==="string"?packet.event:raw.type,ts:raw.ts??Date.now()/1000};
        setData(old=>({...appendEvent(old,event),speech:packet.type==="speak"?packet.text??old.speech:old.speech}));
      }
    }
    function connect(){
      ws=new WebSocket(uiSocketUrl);
      ws.onopen=()=>{if(!disposed)setData(old=>({...old,socket:ws!,connection:"Conectat · așteaptă date"}));};
      ws.onmessage=event=>{try{receive(JSON.parse(event.data))}catch{/* Ignore malformed packets, keep the connection. */}};
      ws.onclose=()=>{if(disposed)return;setFresh(false);setData(old=>({...old,socket:null,connection:"Core indisponibil · reconectare"}));retry=setTimeout(connect,RETRY_MS);};
    }
    connect();
    const watchdog=setInterval(()=>{
      if(last&&Date.now()-last>STALE_MS){setFresh(false);setData(old=>old.socket?{...old,connection:"Date neactualizate"}:old);}
    },500);
    return ()=>{disposed=true;clearTimeout(retry);clearInterval(watchdog);ws?.close();};
  },[]);
  /** Send a dashboard action to core; false (with a visible reason) when it could not be sent. */
  const command=useCallback(async(name:string,args:Record<string,unknown>={})=>{
    const {data}=current.current,socket=data.socket,message=liveMessage(name,args,data.state);
    if(!socket||socket.readyState!==1){setError("Core nu este conectat. Comanda nu a fost trimisă.");return false;}
    if(!message){setError("Această acțiune se face prin voce, cu copilotul.");return false;}
    setError("");socket.send(JSON.stringify(message));return true;
  },[]);
  /** Whether a button for ``name`` can act right now: core connected and the action exists in the contract. */
  const can=useCallback((name:string)=>current.current.data.socket?.readyState===1&&LIVE_COMMANDS.has(name),[]);
  return {data,fresh,error,command,can,clearError:()=>setError("")};
}

/** Dashboard actions that the contract can express (see :func:`liveMessage`). */
export const LIVE_COMMANDS=new Set(["start_trip","resume_trip","pause_trip","stop_at_poi","end_trip","reset","scene","set_llm","set_child",
  "declare_occupant","set_rate","set_speed","inject_message","debug","calibrate","enroll","request","answer","stop_media",
  "set_assistant_preference"]);

/**
 * A dashboard action as core expects it on ``/ws/ui`` (``UI_COMMANDS`` in shared/contracts.py), or null when the
 * contract has no such command (reminders and message replies are voice-driven in core).
 */
export function liveMessage(name:string,args:Record<string,unknown>,state:DashboardState):Record<string,unknown>|null{
  const cmd=(value:Record<string,unknown>)=>({type:"command",...value});
  const speech=(text:unknown)=>typeof text==="string"&&text.trim()?{type:"speech",text:text.trim(),final:true,addressed:true,ts:Date.now()/1000}:null;
  switch(name){
    case "start_trip":case "resume_trip":return cmd({cmd:"start"});
    case "pause_trip":return cmd({cmd:"pause"});
    case "stop_at_poi":return cmd({cmd:"stop_at_next_poi"});
    case "end_trip":return cmd({cmd:"end_trip"});
    case "reset":return cmd({cmd:"reset"});
    case "scene":return Number.isInteger(args.scene)?cmd({cmd:"scene",value:args.scene}):null;
    case "set_llm":return cmd({cmd:"llm",on:args.enabled===true});
    case "set_rate":return typeof args.rate==="number"&&args.rate>0?cmd({cmd:"time_scale",value:args.rate}):null;
    case "set_speed":return typeof args.speed==="number"?cmd({cmd:"speed",value:args.speed}):null;
    case "inject_message":return cmd({cmd:"fake_message",value:{from:args.from??"Mihai",app:args.app??"whatsapp",text:String(args.text??"")}});
    case "debug":return cmd({cmd:"debug",on:args.on===true});
    case "calibrate":return typeof args.profile==="string"&&args.profile.trim()?cmd({cmd:"calibrate",value:{profile:args.profile.trim(),quick:args.quick===true}}):null;
    case "enroll":return typeof args.name==="string"&&args.name.trim()?cmd({cmd:"enroll",value:{name:args.name.trim(),camera:args.camera==="passenger"?"passenger":"driver"}}):null;
    case "declare_occupant":return cmd({cmd:"declare_occupant",value:args});
    // P3's interaction preferences (talkativeness / follow_up / answer_length); core keeps them for this trip.
    case "set_assistant_preference":return typeof args.key==="string"&&typeof args.value==="string"?cmd({cmd:"assistant_preference",value:{key:args.key,value:args.value}}):null;
    case "set_child":{
      // A rear child is a declared occupant in core (plan G1); removing it needs the id core assigned.
      if(args.enabled===true)return cmd({cmd:"declare_occupant",value:{profile:null,role:"child",seat:"rear"}});
      const child=state.occupants?.find(o=>o.source==="declared"&&o.role==="child");
      return child?cmd({cmd:"declare_occupant",value:{remove:child.id}}):null;
    }
    case "request":return speech(args.text);
    case "answer":return speech(args.value);
    // The assistant stops playback from the words themselves (assistant/fallback.py stop_media_request).
    case "stop_media":return speech("Oprește muzica");
    default:return null;
  }
}
