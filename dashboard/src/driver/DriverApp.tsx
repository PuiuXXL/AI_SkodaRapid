import {useEffect,useRef,useState} from "react";
import {motion,useReducedMotion} from "motion/react";
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
    if(landing)document.title="DriveMate · four your safety";
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
  const reducedMotion=useReducedMotion();
  const tools=page==="dashboard"||page==="simulator";
  // Kept across pages: the route being planned, and the one core follows (#/simulator).
  const planner=useRoutePlanner(session.fresh?session.data.state.trip:undefined);
  useEffect(()=>{try{localStorage.setItem("drivemate.sidebar.collapsed",String(collapsed))}catch{/* Keep navigation usable without storage. */}},[collapsed]);
  useEffect(()=>{document.title=pageTitles[page]+" · DriveMate";shell.current?.scrollTo({top:0,behavior:"instant"});},[page]);
  const provider={...session,audio};
  function link(destination:Page,icon:string){
    const selected=page===destination;
    return <a key={destination} className="page-link" href={"#/"+destination}
      aria-label={pageTitles[destination]} title={pageTitles[destination]} aria-current={selected?"page":undefined}>
      {selected&&<motion.i className="nav-active-surface" layoutId="driver-navigation-active"
        transition={{duration:reducedMotion?0:.24,ease:[.22,.7,.3,1]}} aria-hidden="true"/>}
      <Icon name={icon}/><span>{pageTitles[destination]}</span>
    </a>;
  }
  const state:typeof session.data.state=session.fresh?session.data.state:{},alert=state.safety?.alert,sos=state.safety?.sos,name=driverName(state.occupants);
  if(page==="salut")return <Greeting ready={session.fresh} name={name} dark={dark}/>;
  return <DriverContext.Provider value={provider}><div data-workspace-theme={dark?"dark":"light"} ref={shell} className={"dashboard driver-app"+(collapsed&&!mobile?" sidebar-collapsed":"")+(tools?" tools-page":"")}>
    <a className="skip-link" href="#driver-main" onClick={e=>{e.preventDefault();document.getElementById("driver-main")?.focus();}}>Skip to content</a>
    <NavigationShell dark={dark} mobile={mobile} navigationKey={page}>
      <div className="sidebar-brand"><a href="#/volan" className="brand" aria-label="DriveMate · At the wheel"><BrandLogo dark compact={collapsed&&!mobile}/></a><button className="nav-collapse" aria-label={collapsed?"Expand navigation":"Collapse navigation"} aria-expanded={!collapsed} onClick={()=>setCollapsed(!collapsed)} title={collapsed?"Expand navigation":"Collapse navigation"}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d={collapsed?"M9 4v16m4-11 3 3-3 3":"M9 4v16m7-11-3 3 3 3"}/></svg></button></div>
      <nav className="page-nav" aria-label="Driver navigation">{links.map(item=>link(item.page,item.icon))}</nav>
      <div className="header-meta">
        <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Dark mode" aria-pressed={dark} title="Dark mode">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            {dark?<path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/>:<><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></>}
          </svg>
          <b>{dark?"Dark appearance":"Light appearance"}</b><i className="theme-switch" aria-hidden="true"/>
        </button>
        {/* Account: who core recognises at the wheel, and the way back to the start (Connect) page. Leaving silences voice and sound. */}
        <div className="account-block"><span className="account-avatar" aria-hidden="true">{name?name.slice(0,1):<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>}</span>
          <span className="account-caption"><strong>{name??"Driver"}</strong><small><i className={"account-status"+(session.fresh?" is-live":"")} aria-hidden="true"/>{session.fresh?"Live session":"Offline"}</small></span>
          <button type="button" className="account-exit" onClick={()=>{audio.silence();navigate("start");}} aria-label="Back to start" title="Back to start"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h10"/></svg><b>Exit</b></button>
        </div>
      </div>
    </NavigationShell>
    <main className="driver-main" id="driver-main" tabIndex={-1}><div className="workspace-topline"><span>{tools?"TOOLS":"PERSONAL COPILOT"}</span><span className={"connection-badge"+(!session.fresh?" stale":"")}>{session.data.connection}</span></div>
      {!session.fresh&&<div className="connection-warning" role="status">Waiting for core. Live readings and controls return when the connection is restored.</div>}
      {(alert||state.safety?.monitoring_ok===false)&&<div className="safety-banner" role="alert"><Icon name="pulse"/><strong>{state.safety?.monitoring_ok===false?"Monitoring interrupted":label(alerts,typeof alert==="object"?alert?.text:alert)}</strong>
        {sos?.state&&sos.state!=="normal"&&<span>{label(sosStates,sos.state)}{typeof sos.countdown_s==="number"&&" · "+Math.max(0,Math.ceil(sos.countdown_s))+" s"}</span>}</div>}
      {session.error&&<div className="form-feedback" role="alert">{session.error}<button onClick={session.clearError}>Dismiss</button></div>}
      {page==="volan"&&<Cockpit/>}
      {page==="dashboard"&&<MonitorPage/>}
      {page==="setari"&&<SettingsPage/>}
      {page==="simulator"&&<div><div className="driver-heading"><small>TOOLS / LOCATION</small><h1>Route simulator</h1><p>Plan a route and explore it with your copilot.</p></div><Simulator planner={planner}/></div>}
      {page==="missing"&&<section className="empty-state"><h1>Page not found</h1><p>Return to the driver menu.</p><button className="primary-action" onClick={()=>navigate("volan")}>At the wheel</button></section>}
      <footer className="driver-footer"><span>DriveMate · Personal copilot</span><span>Live data · core</span></footer>
    </main>
  </div></DriverContext.Provider>;
}
