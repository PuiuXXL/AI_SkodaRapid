import {useCallback,useEffect,useRef,useState} from "react";
import type {DashboardEvent,SessionData,SessionSocket} from "../types";
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
    if(snapshot.live||!snapshot.fresh||!snapshot.data.state.driver_ui?.commands?.includes(name)){
      setError(snapshot.live?"Această comandă nu este disponibilă în Live.":"Așteaptă reconectarea înainte de a reîncerca.");return false;
    }
    pending.current=true;setBusy(true);setError("");
    try{await api("/api/driver/command","POST",{id:newId(),cmd:name,args,trip_id:snapshot.data.state.trip?.id??null});return true;}
    catch(error){setError(errorText(error));return false;}
    finally{pending.current=false;setBusy(false);}
  },[]);
  return {data,fresh,error,busy,command,clearError:()=>setError("")};
}
