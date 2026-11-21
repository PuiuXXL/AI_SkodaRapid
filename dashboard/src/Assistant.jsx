import React,{useEffect,useRef,useState} from "react";
import {initVoice,onTranscript,stopVoice} from "./voice/index.js";
import {Detail,Panel,Rows,time,words,fmt,yes} from "./Panels.jsx";

function Voice({socket}){
 const [status,setStatus]=useState("Oprită"),[subtitle,setSubtitle]=useState("");
 const active=useRef(false),off=useRef(null);
 function stop(){
   active.current=false;off.current?.();off.current=null;stopVoice();setStatus("Oprită");setSubtitle("");
 }
 useEffect(()=>()=>{active.current=false;off.current?.();stopVoice()},[socket]);
 async function start(){
   if(active.current || socket?.readyState!==WebSocket.OPEN)return;
   active.current=true;setStatus("Se activează");
   try{
     const controller=await initVoice(socket);
     if(!active.current || socket.readyState!==WebSocket.OPEN){controller.stop();return;}
     off.current=onTranscript(r=>setSubtitle(r.text));setStatus("Activă");
   }catch{stop();setStatus("Microfon indisponibil");}
 }
 return <div className="voice"><button disabled={!socket || status==="Se activează"} onClick={active.current?stop:start}>{active.current?"Oprește vocea":"Activează vocea"}</button> {status}{subtitle&&<p>{subtitle}</p>}</div>
}
export function Assistant({s,data,live}){
 return <Panel id="assistant" label="INTERACȚIUNE" title="Asistent și jurnal">
 <p className="utterance">{data.speech||"În așteptarea unei sugestii"}</p>
 {s.assistant?.muted_until> Date.now()/1000&&<p>Asistentul tace până la {time(s.assistant.muted_until)}</p>}
 {live&&<Voice key={data.socket?"connected":"offline"} socket={data.socket}/>}
 <Detail title="Stare și dialog"><Rows items={[["Stare",words(s.interaction?.state)],["Destinatar",words(s.interaction?.addressed_to)],["Fereastră de răspuns",yes(s.interaction?.dialog_window_open)],["LLM activat",yes(s.safety?.llm_enabled)],["Intervenție LLM permisă",yes(s.safety?.llm_allowed)],["Motiv liniște",words(s.assistant?.mute_reason)]]}/></Detail>
 <Detail title={'Jurnal de evenimente · '+data.log.length}>{data.log.length?<ol>{data.log.map((e,i)=><li key={data.log.length-i+"-"+e.ts}><small>{time(e.ts)} · {words(e.source)}</small><p>{words(e.explanation??e.text??e.type)}</p><span>{words(e.channel)} · {fmt(e.latency_ms," ms")}</span></li>)}</ol>:<p>În așteptarea primului eveniment.</p>}</Detail>
 </Panel>
}
