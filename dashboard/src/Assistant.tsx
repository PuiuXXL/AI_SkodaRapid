import type { StateProps, SessionData } from "./types";
import React,{useEffect,useRef,useState} from "react";
import {initVoice,onTranscript,stopVoice} from "./voice/index.js";
import {Detail,Panel,Rows,time,words,fmt,yes} from "./Panels";

function Voice({socket}: {socket: SessionData["socket"]}){
 const [status,setStatus]=useState("Off"),[subtitle,setSubtitle]=useState("");
 const active=useRef(false),off=useRef<(() => void) | null>(null);
 function stop(){
   active.current=false;off.current?.();off.current=null;stopVoice();setStatus("Off");setSubtitle("");
 }
 useEffect(()=>()=>{active.current=false;off.current?.();stopVoice()},[socket]);
 async function start(){
   if(active.current || socket?.readyState!==WebSocket.OPEN)return;
   active.current=true;setStatus("Starting");
   try{
     const controller=await initVoice(socket);
     if(!active.current || socket.readyState!==WebSocket.OPEN){controller.stop();return;}
     off.current=onTranscript(r=>setSubtitle(r.text));setStatus("Active");
   }catch{stop();setStatus("Microphone unavailable");}
 }
 return <div className="voice"><button disabled={!socket || status==="Starting"} onClick={active.current?stop:start}>{active.current?"Turn off voice":"Enable voice"}</button> {status}{subtitle&&<p>{subtitle}</p>}</div>
}
export function Assistant({s,data}: StateProps & {data: SessionData}){
 return <Panel id="assistant" label="INTERACTION" title="Assistant & journal">
 <p className="utterance">{data.speech||"Waiting for a suggestion"}</p>
 <div className="assistant-flow" aria-label="Assistant status">
   <span data-active={Boolean(data.socket)}>Connection<strong>{data.socket?"Connected":"Waiting"}</strong></span>
   <span data-active={s.safety?.llm_allowed===true}>Assistant<strong>{yes(s.safety?.llm_allowed)}</strong></span>
   <span data-active={s.interaction?.dialog_window_open===true}>Dialogue<strong>{s.interaction?.dialog_window_open===undefined?"—":s.interaction.dialog_window_open?"Open":"Closed"}</strong></span>
 </div>
 {(s.assistant?.muted_until??0)> Date.now()/1000&&<p>Assistant muted until {time(s.assistant?.muted_until)}</p>}
 <Voice key={data.socket?"connected":"offline"} socket={data.socket}/>
 <Detail title="State & dialogue"><Rows items={[["State",words(s.interaction?.state)],["Recipient",words(s.interaction?.addressed_to)],["Response window",yes(s.interaction?.dialog_window_open)],["LLM enabled",yes(s.safety?.llm_enabled)],["LLM intervention allowed",yes(s.safety?.llm_allowed)],["Mute reason",words(s.assistant?.mute_reason)]]}/></Detail>
 <Detail title={'Event journal · '+data.log.length}>{data.log.length?<ol>{data.log.map((e,i)=><li key={data.log.length-i+"-"+e.ts}><small>{time(e.ts)} · {words(e.source)}</small><p>{words(e.explanation??e.text??e.type)}</p><span>{words(e.channel)} · {fmt(e.latency_ms," ms")}</span></li>)}</ol>:<p>Waiting for the first event.</p>}</Detail>
 </Panel>
}
