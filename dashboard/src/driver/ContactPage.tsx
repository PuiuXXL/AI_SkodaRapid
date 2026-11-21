import {useEffect,useRef,useState} from "react";
import {api,errorText,newId} from "./contracts";
import type {ContactState} from "./contracts";
import {phaseLabels} from "./DrivingPages";
import {BrandLogo} from "../BrandLogo";
import {fmt} from "../Panels";

export function ContactPage({token}: {token:string}){
  const [state,setState]=useState<ContactState|null>(null),[error,setError]=useState(""),[text,setText]=useState(""),[feedback,setFeedback]=useState(""),[busy,setBusy]=useState(false);
  const receipt=useRef({text:"",id:newId()});
  useEffect(()=>{
    let disposed=false,pending=false;
    async function refresh(){if(pending)return;pending=true;try{const value=await api<ContactState>("/api/contact/"+encodeURIComponent(token));if(!disposed){setState(value);setError("");}}catch(error){if(!disposed)setError(errorText(error));}finally{pending=false;}}
    void refresh();const timer=setInterval(refresh,2000);return ()=>{disposed=true;clearInterval(timer)};
  },[token]);
  async function send(){
    if(busy||!text.trim())return;
    if(receipt.current.text!==text)receipt.current={text,id:newId()};
    setBusy(true);setFeedback("");
    try{await api("/api/contact/"+encodeURIComponent(token)+"/messages","POST",{id:receipt.current.id,text});setFeedback(state?.source==="demo"?"Mesaj înregistrat în sesiunea demonstrativă.":"Mesaj primit de serviciu.");setText("");receipt.current={text:"",id:newId()};}
    catch(error){setFeedback(errorText(error));}finally{setBusy(false);}
  }
  return <main className="contact-page"><a className="contact-brand" style={{display:"inline-flex",alignItems:"center"}} href="/"><BrandLogo/> <span>Contact</span></a><div className="driver-heading"><small>{state?.source==="demo"?"SESIUNE DEMONSTRATIVĂ":"STARE PARTAJATĂ"}</small><h1>{state?"Drumul lui "+state.name:"DriveMate Contact"}</h1></div>
    {error&&<p role="alert" className="form-feedback">{error} Datele afișate anterior nu sunt confirmate ca actuale.</p>}
    {state&&<><section className={"contact-notice "+(state.notice?.type??"normal")}>{state.notice&&<small>{phaseLabels[state.phase]}</small>}<h2>{state.notice?.type==="sos"?"Alertă SOS" :state.notice?.type==="fatigue"?"Șoferul pare obosit":phaseLabels[state.phase]??"Stare necunoscută"}</h2><p>{state.notice?.text??"Îi poți lăsa un mesaj. Va fi anunțat când contextul permite."}</p><dl><div><dt>Până la destinație</dt><dd>{fmt(state.eta_min," min")}</dd></div><div><dt>Ultima actualizare</dt><dd>{new Date(state.updated_at*1000).toLocaleTimeString("ro-RO")}</dd></div></dl>{state.notice?.type==="sos"&&state.pos&&<p>Poziție comunicată: {state.pos.lat.toFixed(5)}, {state.pos.lon.toFixed(5)}</p>}{state.notice?.channels&&<ul>{Object.entries(state.notice.channels).map(([channel,status])=><li key={channel}>{channel}: {status}</li>)}</ul>}{state.source==="demo"&&<p className="contact-demo-note">Exercițiu local. Nu s-au efectuat apeluri sau notificări de urgență reale.</p>}</section>
    <section><h2>Lasă-i un mesaj</h2><form onSubmit={e=>{e.preventDefault();void send();}}><label>Mesaj<textarea value={text} maxLength={500} required onChange={e=>setText(e.target.value)}/></label><button className="primary-action" type="submit" disabled={busy||!!error||!text.trim()}>{busy?"Se trimite…":"Trimite mesajul"}</button></form><p role="status">{feedback}</p></section></>}
  </main>;
}
