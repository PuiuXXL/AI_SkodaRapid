import {useCallback,useEffect,useRef,useState} from "react";
import type {DashboardEvent,DashboardState,SessionData,SessionSocket} from "../types";
import {appendEvent,withState} from "../session-state";
import {api,errorText,newId} from "./contracts";

const empty:SessionData={state:{},history:[],log:[],socket:null,cue:0,speech:"",connection:"Se conectează"};
class LocalSocket extends EventTarget implements SessionSocket {
  readyState=1;
  tripId:string|null=null;
  constructor(private fail:(text:string)=>void){super();}
  send(raw:string){
    if(this.readyState!==1)return;
    let message;try{message=JSON.parse(raw)}catch{return;}
    void api("/api/driver/voice","POST",{...message,trip_id:this.tripId}).catch(error=>this.fail(errorText(error)));
  }
}

export function useDriverSession(live:boolean) {
  const [data,setData]=useState<SessionData>({...empty,connection:"Se conectează"});
  const [fresh,setFresh]=useState(false),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const current=useRef({live,data,fresh});current.current={live,data,fresh};
  const pending=useRef(false);
  useEffect(()=>{
    let disposed=false,last=0,retry:ReturnType<typeof setTimeout>|undefined;
    let ws:WebSocket|undefined,events:EventSource|undefined;
    const local=new LocalSocket(setError);
    setData({...empty,connection:live?"Live · conectare":"Simulat · conectare"});setFresh(false);setError("");
    function receive(packet:any) {
      if(disposed)return;
      if(packet.type==="snapshot"||packet.type==="state"){
        if(!packet.state||typeof packet.state!=="object"||Array.isArray(packet.state))return;
        last=Date.now();setFresh(true);local.tripId=packet.state.trip?.id??null;
        setData(old=>packet.type==="snapshot"?{...empty,state:packet.state,history:packet.history??[],log:packet.log??[],speech:packet.speech??"",socket:local,connection:"Simulat · conectat"}:
          {...withState(old,packet.state),socket:live?ws??null:local,connection:live?"Live · conectat":"Simulat · conectat"});
      }else if(["event","alarm","speak","media","speak_control"].includes(packet.type)){
        const raw=typeof packet.event==="object"?packet.event:packet;
        const event:DashboardEvent={...raw.data,...raw,type:typeof packet.event==="string"?packet.event:raw.type,ts:raw.ts??Date.now()/1000};
        setData(old=>({...appendEvent(old,event),speech:packet.type==="speak"?packet.text??old.speech:old.speech}));
      }
      if(!live&&packet.type!=="snapshot")local.dispatchEvent(new MessageEvent("message",{data:JSON.stringify(packet)}));
    }
    function connect(){
      ws=new WebSocket(import.meta.env.VITE_UI_WS||"ws://localhost:8000/ws/ui");
      ws.onopen=()=>{if(!disposed)setData(old=>({...old,socket:ws!,connection:"Live · așteaptă date"}));};
      ws.onmessage=event=>{try{receive(JSON.parse(event.data))}catch{/* Ignore malformed packets, keep the connection. */}};
      ws.onclose=()=>{if(disposed)return;setFresh(false);setData(old=>({...old,socket:null,connection:"Live · reconectare"}));retry=setTimeout(connect,1800);};
    }
    if(live)connect();
    else {
      events=new EventSource("/api/driver/events");
      events.onopen=()=>{local.readyState=1;};
      events.onmessage=event=>{try{receive(JSON.parse(event.data))}catch{/* Ignore malformed packets. */}};
      events.onerror=()=>{local.readyState=0;setFresh(false);setData(old=>({...old,socket:null,connection:"Simulat · reconectare"}));};
    }
    const watchdog=setInterval(()=>{
      if(last&&Date.now()-last>2500){setFresh(false);setData(old=>({...old,connection:live?"Live · date neactualizate":"Simulat · date neactualizate"}));}
    },500);
    return ()=>{disposed=true;clearTimeout(retry);clearInterval(watchdog);events?.close();local.readyState=3;ws?.close();};
  },[live]);
  const command=useCallback(async(name:string,args:Record<string,unknown>={})=>{
    const snapshot=current.current;
    if(pending.current)return false;
    if(snapshot.live){
      // Live: the same buttons speak core's contract on /ws/ui (shared/contracts.py: UiCommand, UiSpeech).
      const socket=snapshot.data.socket,message=liveMessage(name,args,snapshot.data.state);
      if(!socket||socket.readyState!==1){setError("Core nu este conectat. Comanda nu a fost trimisă.");return false;}
      if(!message){setError("În Live, această acțiune se face prin voce, cu copilotul.");return false;}
      setError("");socket.send(JSON.stringify(message));return true;
    }
    if(!snapshot.fresh||!snapshot.data.state.driver_ui?.commands?.includes(name)){
      setError(DEMO_ONLY_IN_LIVE.has(name)?"Disponibil numai în Live, cu percepția conectată.":"Așteaptă reconectarea înainte de a reîncerca.");return false;
    }
    pending.current=true;setBusy(true);setError("");
    try{await api("/api/driver/command","POST",{id:newId(),cmd:name,args,trip_id:snapshot.data.state.trip?.id??null});return true;}
    catch(error){setError(errorText(error));return false;}
    finally{pending.current=false;setBusy(false);}
  },[]);
  /** Whether a button for ``name`` can act right now (Live: core connected and the command exists in the contract). */
  const can=useCallback((name:string)=>{
    const snapshot=current.current;
    if(snapshot.live)return snapshot.data.socket?.readyState===1&&LIVE_COMMANDS.has(name);
    return snapshot.fresh&&!!snapshot.data.state.driver_ui?.commands?.includes(name);
  },[]);
  return {data,fresh,error,busy,command,can,clearError:()=>setError("")};
}

/** Commands that exist only with the real backend (P1 perception behind core). */
const DEMO_ONLY_IN_LIVE=new Set(["debug","calibrate","enroll","pause_trip","declare_occupant"]);
/** Local command names the Live bridge can express with the contract. */
export const LIVE_COMMANDS=new Set(["start_trip","resume_trip","pause_trip","stop_at_poi","end_trip","reset","scene","set_llm","set_child",
  "declare_occupant","set_rate","set_speed","inject_message","debug","calibrate","enroll","request","answer"]);

/**
 * A dashboard action as core expects it on ``/ws/ui`` (``UI_COMMANDS`` in shared/contracts.py), or null when the
 * contract has no such command (reminders, message replies and music are voice-driven in core).
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
    case "set_child":{
      // A rear child is a declared occupant in core (plan G1); removing it needs the id core assigned.
      if(args.enabled===true)return cmd({cmd:"declare_occupant",value:{profile:null,role:"child",seat:"rear"}});
      const child=state.occupants?.find(o=>o.source==="declared"&&o.role==="child");
      return child?cmd({cmd:"declare_occupant",value:{remove:child.id}}):null;
    }
    case "request":return speech(args.text);
    case "answer":return speech(args.value);
    default:return null;
  }
}
