import {useCallback,useEffect,useRef,useState} from "react";
import {useDriverSession} from "./session";
import {useDriverAudio} from "./audio";
import {DriverContext} from "./context";
import {api,errorText,tripPhase} from "./contracts";
import type {Profile} from "./contracts";
import {usePage,navigate,pageTitles} from "./routes";
import type {Page} from "./routes";
import {NavigationShell,useMobileNavigation} from "../NavigationShell";
import {BrandLogo} from "../BrandLogo";
import {Icon} from "../App";
import {Cockpit,Greeting} from "./Cockpit";
import {LandingPage} from "./LandingPage";
import {MonitorPage} from "./MonitorPage";
import {ContactPage} from "./ContactPage";
import {Simulator} from "../Simulator";
import {useRouteSimulation} from "../route-simulation";
import type {SimulationSettings} from "../session";
import "./driver.css";
import "./cockpit.css";

const links=[{page:"volan",icon:"grid"},{page:"dashboard",icon:"eye"},{page:"simulator",icon:"route"}] as const;
export function DriverApp(){
  if(location.pathname.startsWith("/c/"))return <ContactPage token={location.pathname.slice(3)}/>;
  return <DriverEntry/>;
}
function DriverEntry(){
  const landing=usePage()==="start";
  const [visited,setVisited]=useState(!landing);
  useEffect(()=>{
    if(landing)document.title="DriveMate · for you safety";
    else setVisited(true);
  },[landing]);
  return <>{landing&&<LandingPage/>}{(visited||!landing)&&<div hidden={landing}><DriverWorkspace/></div>}</>;
}
function DriverWorkspace(){
  const rawPage=usePage(),page=["start","salut","dashboard","simulator","missing"].includes(rawPage)?rawPage:"volan";
  const [live,setLiveState]=useState(false),session=useDriverSession(live),audio=useDriverAudio(session.data.socket);
  const [profile,setProfile]=useState<Profile|null>(null),[draft,setDraft]=useState<Profile|null>(null),[profileError,setProfileError]=useState(""),[saving,setSaving]=useState(false);
  const savePending=useRef(false),shell=useRef<HTMLDivElement>(null);
  const [collapsed,setCollapsed]=useState(()=>{try{return localStorage.getItem("drivemate.sidebar.collapsed")==="true"}catch{return false;}});
  const [dark,setDark]=useState(()=>{try{return localStorage.getItem("drivemate.theme")==="dark"}catch{return false}});
  const toggleTheme=()=>{setDark(!dark);try{localStorage.setItem("drivemate.theme",dark?"light":"dark")}catch{/* Storage is optional. */}};
  const mobile=useMobileNavigation();
  const [simulation,setSimulation]=useState<SimulationSettings>({running:false,speed:72,rate:1,reset:0});
  const pauseRoute=useCallback(()=>setSimulation(old=>({...old,running:false})),[]);
  const route=useRouteSimulation(simulation,pauseRoute);
  const phase=tripPhase(session.data.state.trip),locked=!session.fresh||!["ready","parked","finished"].includes(phase);
  const tools=page==="dashboard"||page==="simulator";
  async function reloadProfile(){try{const value=await api<Profile>("/api/driver/profile");setProfile(value);setDraft(value);setProfileError("");}catch(error){setProfileError(errorText(error));}}
  useEffect(()=>{void reloadProfile();},[]);
  useEffect(()=>{try{localStorage.setItem("drivemate.sidebar.collapsed",String(collapsed))}catch{/* Keep navigation usable without storage. */}},[collapsed]);
  useEffect(()=>{document.title=pageTitles[page]+" · DriveMate";shell.current?.scrollTo({top:0,behavior:"instant"});},[page]);
  async function saveProfile(){
    if(!draft||savePending.current)return false;
    if(live||locked){setProfileError("Profilul se salvează la oprire, în sesiunea locală confirmată.");return false;}
    savePending.current=true;setSaving(true);setProfileError("");
    try{const saved=await api<Profile>("/api/driver/profile","PUT",draft);setProfile(saved);setDraft(saved);return true;}
    catch(error){setProfileError(errorText(error));return false;}finally{savePending.current=false;setSaving(false);}
  }
  function setLive(value:boolean){audio.silence();setLiveState(value);}
  const provider={...session,live,setLive,profile,profileError,draft,setDraft,saveProfile,reloadProfile,saving,audio,locked};
  function link(destination:Page,icon:string){return <a key={destination} className="page-link" href={"#/"+destination} aria-label={pageTitles[destination]} title={pageTitles[destination]} aria-current={page===destination?"page":undefined}><Icon name={icon}/><span>{pageTitles[destination]}</span></a>;}
  const alert=session.data.state.safety?.alert;
  if(page==="salut")return <Greeting ready={!!profile&&session.fresh} error={profileError} retry={reloadProfile} dark={dark}/>;
  return <DriverContext.Provider value={provider}><div data-workspace-theme={dark?"dark":"light"} ref={shell} className={"dashboard driver-app"+(collapsed&&!mobile?" sidebar-collapsed":"")+(tools?" tools-page":"")}>
    <a className="skip-link" href="#driver-main" onClick={e=>{e.preventDefault();document.getElementById("driver-main")?.focus();}}>Sari la conținut</a>
    <NavigationShell dark={dark} mobile={mobile} navigationKey={page}>
      <div className="sidebar-brand"><a href="#/volan" className="brand" aria-label="DriveMate · La volan"><BrandLogo dark={dark} compact={collapsed&&!mobile}/></a><button className="nav-collapse" aria-label={collapsed?"Extinde navigarea":"Restrânge navigarea"} aria-expanded={!collapsed} onClick={()=>setCollapsed(!collapsed)} title={collapsed?"Extinde navigarea":"Restrânge navigarea"}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d={collapsed?"M9 4v16m4-11 3 3-3 3":"M9 4v16m7-11-3 3 3 3"}/></svg></button></div>
      <nav className="page-nav" aria-label="Meniul șoferului">{links.map(item=>link(item.page,item.icon))}</nav>
      <div className="header-meta">{page==="dashboard"&&<label className="source-select"><span>Sursa sesiunii</span><select value={live?"live":"demo"} disabled={saving||session.busy} onChange={e=>setLive(e.target.value==="live")}><option value="demo">Simulat · local</option><option value="live">Live · core</option></select></label>}
        <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Mod întunecat" aria-pressed={dark} title="Mod întunecat"><span aria-hidden="true">{dark?"☾":"☼"}</span><b>{dark?"Mod întunecat":"Mod luminos"}</b></button>
      </div>
    </NavigationShell>
    <main className="driver-main" id="driver-main" tabIndex={-1}><div className="workspace-topline"><span>{tools?"INSTRUMENTE":"COPILOT PERSONAL"}</span><span className={"connection-badge"+(!session.fresh?" stale":"")}>{session.data.connection}</span></div>
      {!session.fresh&&<div className="connection-warning" role="status">Se așteaptă date actualizate. Comenzile sunt indisponibile până la reconectare.</div>}
      {(alert||session.data.state.safety?.monitoring_ok===false)&&<div className="safety-banner" role="alert"><Icon name="pulse"/><strong>{session.data.state.safety?.monitoring_ok===false?"Monitorizare întreruptă":typeof alert==="object"?alert?.text:alert}</strong>{session.data.state.driver_ui?.sos_at&&<span>Numărătoare SOS: {Math.max(0,Math.ceil(session.data.state.driver_ui.sos_at-Date.now()/1000))} s</span>}</div>}
      {session.error&&<div className="form-feedback" role="alert">{session.error}<button onClick={session.clearError}>Închide mesajul</button></div>}
      {page==="volan"&&<Cockpit/>}
      {page==="dashboard"&&<MonitorPage/>}
      {page==="simulator"&&<div><div className="driver-heading"><h1>Simulator de locație</h1></div><Simulator settings={simulation} onChange={setSimulation} routeSimulation={route}/></div>}
      {page==="missing"&&<section className="empty-state"><h1>Pagina nu există</h1><p>Revino la meniul șoferului.</p><button onClick={()=>navigate("volan")}>La volan</button></section>}
      <footer className="driver-footer"><span>DriveMate · Copilot personal</span><span>{live?"Date Live · core local":"Date sintetice · exercițiu local"}</span></footer>
    </main>
  </div></DriverContext.Provider>;
}
