import React,{useRef,useState} from "react";

import type {SimulationSettings} from "./session";
import type {RouteSimulation} from "./route-simulation";
import {EXAMPLE_POINTS} from "./route-simulation";
import {fmt,Metrics} from "./Panels";

import {RouteMap} from "./RouteMap";

export function Simulator({settings,onChange,routeSimulation:sim}: {


  settings:SimulationSettings;
  onChange:(settings:SimulationSettings)=>void;

  routeSimulation:RouteSimulation;
}) {
  const [latitude,setLatitude]=useState("46.77"),[longitude,setLongitude]=useState("23.59");
  const [copied,setCopied]=useState("");
  const [pointsOpen,setPointsOpen]=useState(true);
  const [dragged,setDragged]=useState<number|null>(null);
  const [dropTarget,setDropTarget]=useState<number|null>(null);
  const pointerSource=useRef<number|null>(null);
  const pointerTarget=useRef<number|null>(null);
  const total=sim.route?.distance??0;
  const fraction=total>0?sim.progress.distance/total:0;
  const payload=sim.position?{
    source:"frontend_simulator",timestamp:Date.now()/1000,
    latitude:sim.position.lat,longitude:sim.position.lon,heading_deg:sim.position.heading,
    speed_kmh:settings.running&&!sim.completed&&sim.route?settings.speed:0,
    distance_km:sim.progress.distance,elapsed_s:sim.progress.elapsed,
    status:sim.completed?"arrived":settings.running&&sim.route?"moving":"paused"
  }:null;
  function reorder(from:number,to:number){
    if(sim.editingLocked||from===to||from<0||to<0||from>=sim.points.length||to>=sim.points.length)return;
    const points=[...sim.points], [point]=points.splice(from,1);
    points.splice(to,0,point);sim.edit(points);
  }
  async function copy(){
    try{await navigator.clipboard.writeText(JSON.stringify(payload,null,2));setCopied("Copiat")}
    catch{setCopied("Copiere indisponibilă. Selectează textul JSON.")}
  }
  return <div className="simulator-page content route-simulator">
    <section className="route-editor">
      <div className="route-heading"><div><small>PLANIFICARE TRASEU</small><h2>Construiește traseul</h2></div><span className="status-pill">Navigare liberă</span></div>
      <p role="status">{sim.editingLocked?"Simularea rulează. Apasă Pauză pentru a adăuga sau modifica punctele traseului.":"Apasă pe hartă pentru a adăuga puncte. Mută marcajele sau schimbă ordinea opririlor din listă."}</p>

      <div className="route-workspace">
        <RouteMap simulation={sim} disabled={sim.adding||sim.editingLocked} pointsOpen={pointsOpen} onOpenLayers={()=>setPointsOpen(false)}/>
        <div className="route-points" data-collapsed={!pointsOpen}>
          <div className="route-list-heading"><h3>Puncte de traseu</h3><span>{sim.points.length}</span><button className="points-toggle" aria-label={pointsOpen?"Restrânge lista de puncte":"Extinde lista de puncte"} aria-expanded={pointsOpen} aria-controls="route-points-content" onClick={()=>setPointsOpen(!pointsOpen)}>{pointsOpen?"−":"+"}</button></div>
          <fieldset id="route-points-content" className="route-point-editing" hidden={!pointsOpen} disabled={sim.editingLocked}>
          {sim.editingLocked&&<p className="route-lock-note">Pune simularea pe pauză pentru a edita traseul.</p>}
          <div className="route-list-actions"><button disabled={sim.adding} onClick={()=>sim.edit(EXAMPLE_POINTS.map(p=>({...p})))}>Exemplu Cluj–Gilău–Turda</button><button disabled={!sim.points.length} onClick={()=>sim.edit([])}>Golește</button></div>
          {!sim.points.length&&<p className="route-empty">Adaugă cel puțin două puncte pentru a calcula un traseu auto.</p>}
          <ol className="route-point-list">{sim.points.map((point,index)=><li key={point.id} data-point-index={index} data-dragging={dragged===index} data-drop-target={dropTarget===index&&dragged!==index} draggable={!sim.adding&&!sim.editingLocked}
            onDragStart={event=>{event.dataTransfer.setData("text/plain",String(index));event.dataTransfer.effectAllowed="move";setDragged(index)}}
            onDragOver={event=>{event.preventDefault();setDropTarget(index)}}
            onDragEnd={()=>{setDragged(null);setDropTarget(null)}}
            onDrop={event=>{event.preventDefault();const value=event.dataTransfer.getData("text/plain");if(/^\d+$/.test(value))reorder(Number(value),index);setDragged(null);setDropTarget(null)}}>
            <button className="point-drag-handle" disabled={sim.adding} aria-label={`Trage pentru a reordona punctul ${index+1}`} title="Trage pentru reordonare · săgeți sus/jos din tastatură"
              onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();event.stopPropagation();event.currentTarget.setPointerCapture(event.pointerId);pointerSource.current=index;pointerTarget.current=index;setDragged(index);setDropTarget(index)}}
              onPointerMove={event=>{
                if(pointerSource.current===null)return;
                const panel=event.currentTarget.closest<HTMLElement>(".route-points");
                if(panel){const bounds=panel.getBoundingClientRect();if(event.clientY<bounds.top+40)panel.scrollTop-=10;else if(event.clientY>bounds.bottom-40)panel.scrollTop+=10;}
                const row=document.elementFromPoint(event.clientX,event.clientY)?.closest<HTMLElement>(".route-point-list li");
                const target=row?Number(row.dataset.pointIndex):null;
                pointerTarget.current=target;setDropTarget(target);
              }}
              onPointerUp={event=>{if(pointerSource.current!==null&&pointerTarget.current!==null)reorder(pointerSource.current,pointerTarget.current);pointerSource.current=null;pointerTarget.current=null;setDragged(null);setDropTarget(null);if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId)}}
              onPointerCancel={()=>{pointerSource.current=null;pointerTarget.current=null;setDragged(null);setDropTarget(null)}}
              onKeyDown={event=>{if(event.key==="ArrowUp"||event.key==="ArrowDown"){event.preventDefault();reorder(index,index+(event.key==="ArrowUp"?-1:1))}}}>
              <svg width="12" height="18" viewBox="0 0 12 18" fill="currentColor" aria-hidden="true">{[4,9,14].map(y=><g key={y}><circle cx="3" cy={y} r="1.3"/><circle cx="8" cy={y} r="1.3"/></g>)}</svg>
            </button>
            <span className="point-number" title="Trage pentru reordonare">{index+1}</span>
            <div className="point-description"><input aria-label={`Numele punctului ${index+1}`} value={point.name} onChange={event=>sim.rename(point.id,event.target.value)}/><span>{point.lat.toFixed(5)}, {point.lon.toFixed(5)}</span></div>
            <div className="point-actions"><button disabled={index===0} aria-label={`Mută punctul ${index+1} mai sus`} onClick={()=>reorder(index,index-1)}>↑</button><button disabled={index===sim.points.length-1} aria-label={`Mută punctul ${index+1} mai jos`} onClick={()=>reorder(index,index+1)}>↓</button><button aria-label={`Șterge punctul ${index+1}`} onClick={()=>sim.edit(sim.points.filter(p=>p.id!==point.id))}>×</button></div>
          </li>)}</ol>
          <details className="point-coordinate-details"><summary>Adaugă prin coordonate</summary><form className="coordinate-form" onSubmit={event=>{event.preventDefault();void sim.add({lat:Number(latitude),lon:Number(longitude)})}}>
            <label>Latitudine<input name="latitude" type="number" step="any" required min="-90" max="90" value={latitude} onChange={e=>setLatitude(e.target.value)} disabled={sim.adding}/></label>
            <label>Longitudine<input name="longitude" type="number" step="any" required min="-180" max="180" value={longitude} onChange={e=>setLongitude(e.target.value)} disabled={sim.adding}/></label>
            <button disabled={sim.adding} type="submit">{sim.adding?"Se validează…":"Adaugă punct"}</button>
          </form></details>
          </fieldset>
        </div>
      </div>
      <div className="route-status" role="status">{sim.adding?"Se verifică drumul…":sim.status==="loading"?"Se calculează traseul auto…":sim.status==="ready"?`Traseu calculat · ${fmt(total," km",1,2)}`:"Alege punctele traseului."}</div>
      {sim.error&&<div className="route-error" role="alert">{sim.error}{sim.status==="error"&&<button onClick={sim.retry}>Reîncearcă rutarea</button>}</div>}
      <p className="route-hint">Harta și calculul traseului folosesc servicii online OpenStreetMap / OSRM.</p>
      <p className="route-hint">Punctele sunt aliniate la drumuri aflate la maximum 500 m. Trage de mânerul cu puncte pentru reordonare. Traseul recalculat revine la start, în pauză.</p>
    </section>
    <section className="route-playback" aria-label="Comenzi deplasare"><small>REDARE</small><h2>Deplasarea mașinii</h2>
      <fieldset className="simulator-controls">
        <div className="simulator-actions">
          <button className="primary-action" disabled={!sim.route||sim.completed||sim.adding} aria-pressed={Boolean(settings.running&&sim.route)} onClick={()=>onChange({...settings,running:!settings.running})}>{settings.running&&sim.route?"Pauză":"Pornește"}</button>
          <button onClick={()=>onChange({...settings,running:false,reset:settings.reset+1})}>Revino la start</button>
          <span role="status">{sim.completed?"Destinație atinsă":settings.running&&sim.route?"În deplasare":"În pauză"}</span>
        </div>
        <label>Viteza mașinii<output>{settings.speed} km/h</output><input type="range" min="0" max="160" value={settings.speed} onChange={e=>onChange({...settings,speed:Number(e.target.value)})}/></label>
        <label>Viteza de rulare a simulării<select value={settings.rate} onChange={e=>onChange({...settings,rate:Number(e.target.value)})}><option value={1}>×1 · Timp real</option><option value={5}>×5</option><option value={20}>×20</option><option value={100}>×100</option></select></label>
        <label>Poziție pe traseu<output>{fmt(fraction,"%",100,1)}</output><input aria-label="Poziție pe traseu" type="range" min="0" max="1" step=".001" value={fraction} disabled={!sim.route} onChange={e=>sim.seek(Number(e.target.value))}/></label>
      </fieldset>
      <Metrics items={[["Parcurs",fmt(sim.progress.distance," km",1,2)],["Rămas",fmt(total-sim.progress.distance," km",1,2)],["Timp simulat",fmt(sim.progress.elapsed/60," min",1,2)]]}/>
    </section>
    <section className="location-preview"><small>LOCAȚIE SIMULATĂ</small><h2>Preview input</h2>
      <p>Coordonate generate local, pregătite pentru conectarea ulterioară la backend.</p>
      <Metrics items={[["Latitudine",fmt(sim.position?.lat,"",1,6)],["Longitudine",fmt(sim.position?.lon,"",1,6)],["Direcție",fmt(sim.position?.heading,"°",1,1)]]}/>
      <pre aria-label="Input locație JSON">{payload?JSON.stringify(payload,null,2):"Adaugă un punct pentru a vedea coordonatele."}</pre>
      <div className="simulator-actions"><button disabled={!payload} onClick={copy}>Copiază JSON</button><span role="status">{copied}</span></div>
    </section>

  </div>;
}
