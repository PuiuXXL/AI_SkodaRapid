import {useEffect,useRef,useState} from "react";
import {useDriverSession} from "./session";
import {useDriverAudio} from "./audio";
import {DriverContext} from "./context";
import {driverName} from "./contracts";
import {usePage,navigate,pageTitles} from "./routes";
import type {Page} from "./routes";
import {NavigationShell,useMobileNavigation} from "../NavigationShell";
import {BrandLogo} from "../BrandLogo";
import {alerts,label,sosStates} from "../labels";
import {Icon} from "../App";
import {Cockpit,Greeting} from "./Cockpit";
import {LandingPage} from "./LandingPage";
import {MonitorPage} from "./MonitorPage";
import {SettingsPage} from "./SettingsPage";
import {Simulator} from "../Simulator";
import {useRoutePlanner} from "../route-simulation";
import "./driver.css";
import "./cockpit.css";

const links=[{page:"volan",icon:"grid"},{page:"dashboard",icon:"eye"},{page:"setari",icon:"sliders"},{page:"simulator",icon:"route"}] as const;
export function DriverApp(){
  const landing=usePage()==="start";
  const [visited,setVisited]=useState(!landing);
  useEffect(()=>{
    if(landing)document.title="DriveMate · for you safety";
    else setVisited(true);
  },[landing]);
  return <>{landing&&<LandingPage/>}{(visited||!landing)&&<div hidden={landing}><DriverWorkspace/></div>}</>;
}
// Everything shown here comes from core over /ws/ui (session.ts). Without core the pages say so and show no values.
function DriverWorkspace(){
  const rawPage=usePage(),page=["start","salut","dashboard","setari","simulator","missing"].includes(rawPage)?rawPage:"volan";
  const session=useDriverSession(),audio=useDriverAudio(session.data.socket);
  const shell=useRef<HTMLDivElement>(null);
  const [collapsed,setCollapsed]=useState(()=>{try{return localStorage.getItem("drivemate.sidebar.collapsed")==="true"}catch{return false;}});
  const [dark,setDark]=useState(()=>{try{return localStorage.getItem("drivemate.theme")==="dark"}catch{return false}});
  const toggleTheme=()=>{setDark(!dark);try{localStorage.setItem("drivemate.theme",dark?"light":"dark")}catch{/* Storage is optional. */}};
  const mobile=useMobileNavigation();
  const tools=page==="dashboard"||page==="simulator";
  // Kept across pages: the route being planned, and the one core follows (#/simulator).
  const planner=useRoutePlanner(session.fresh?session.data.state.trip:undefined);
  useEffect(()=>{try{localStorage.setItem("drivemate.sidebar.collapsed",String(collapsed))}catch{/* Keep navigation usable without storage. */}},[collapsed]);
  useEffect(()=>{document.title=pageTitles[page]+" · DriveMate";shell.current?.scrollTo({top:0,behavior:"instant"});},[page]);
  const provider={...session,audio};
  function link(destination:Page,icon:string){return <a key={destination} className="page-link" href={"#/"+destination} aria-label={pageTitles[destination]} title={pageTitles[destination]} aria-current={page===destination?"page":undefined}><Icon name={icon}/><span>{pageTitles[destination]}</span></a>;}
  const state:typeof session.data.state=session.fresh?session.data.state:{},alert=state.safety?.alert,sos=state.safety?.sos,name=driverName(state.occupants);
  if(page==="salut")return <Greeting ready={session.fresh} name={name} dark={dark}/>;
  return <DriverContext.Provider value={provider}><div data-workspace-theme={dark?"dark":"light"} ref={shell} className={"dashboard driver-app"+(collapsed&&!mobile?" sidebar-collapsed":"")+(tools?" tools-page":"")}>
    <a className="skip-link" href="#driver-main" onClick={e=>{e.preventDefault();document.getElementById("driver-main")?.focus();}}>Sari la conținut</a>
    <NavigationShell dark={dark} mobile={mobile} navigationKey={page}>
      <div className="sidebar-brand"><a href="#/volan" className="brand" aria-label="DriveMate · La volan"><BrandLogo dark={dark} compact={collapsed&&!mobile}/></a><button className="nav-collapse" aria-label={collapsed?"Extinde navigarea":"Restrânge navigarea"} aria-expanded={!collapsed} onClick={()=>setCollapsed(!collapsed)} title={collapsed?"Extinde navigarea":"Restrânge navigarea"}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d={collapsed?"M9 4v16m4-11 3 3-3 3":"M9 4v16m7-11-3 3 3 3"}/></svg></button></div>
      <nav className="page-nav" aria-label="Meniul șoferului">{links.map(item=>link(item.page,item.icon))}</nav>
      <div className="header-meta">
        <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Mod întunecat" aria-pressed={dark} title="Mod întunecat"><span aria-hidden="true">{dark?"☾":"☼"}</span><b>{dark?"Mod întunecat":"Mod luminos"}</b></button>
        {/* Account: who core recognises at the wheel, and the way back to the start (Connect) page. Leaving silences voice and sound. */}
        <div className="account-block"><span className="account-avatar" aria-hidden="true">{(name??"?").slice(0,1)}</span>
          <span className="account-caption"><strong>{name??"Șofer"}</strong><small>{session.fresh?"Sesiune Live":"Fără date Live"}</small></span>
          <button type="button" className="account-exit" onClick={()=>{audio.silence();navigate("start");}} aria-label="Ieși la pagina de start" title="Ieși la pagina de start"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h10"/></svg><b>Ieșire</b></button>
        </div>
      </div>
    </NavigationShell>
    <main className="driver-main" id="driver-main" tabIndex={-1}><div className="workspace-topline"><span>{tools?"INSTRUMENTE":"COPILOT PERSONAL"}</span><span className={"connection-badge"+(!session.fresh?" stale":"")}>{session.data.connection}</span></div>
      {!session.fresh&&<div className="connection-warning" role="status">Nu sosesc date de la core. Valorile și comenzile revin la reconectare.</div>}
      {(alert||state.safety?.monitoring_ok===false)&&<div className="safety-banner" role="alert"><Icon name="pulse"/><strong>{state.safety?.monitoring_ok===false?"Monitorizare întreruptă":label(alerts,typeof alert==="object"?alert?.text:alert)}</strong>
        {sos?.state&&sos.state!=="normal"&&<span>{label(sosStates,sos.state)}{typeof sos.countdown_s==="number"&&" · "+Math.max(0,Math.ceil(sos.countdown_s))+" s"}</span>}</div>}
      {session.error&&<div className="form-feedback" role="alert">{session.error}<button onClick={session.clearError}>Închide mesajul</button></div>}
      {page==="volan"&&<Cockpit/>}
      {page==="dashboard"&&<MonitorPage/>}
      {page==="setari"&&<SettingsPage/>}
      {page==="simulator"&&<div><div className="driver-heading"><small>INSTRUMENTE / LOCAȚIE</small><h1>Simulator de locație</h1><p>Traseul de pe hartă devine drumul pe care core îl parcurge</p></div><Simulator planner={planner}/></div>}
      {page==="missing"&&<section className="empty-state"><h1>Pagina nu există</h1><p>Revino la meniul șoferului.</p><button onClick={()=>navigate("volan")}>La volan</button></section>}
      <footer className="driver-footer"><span>DriveMate · Copilot personal</span><span>Date Live · core</span></footer>
    </main>
  </div></DriverContext.Provider>;
}
