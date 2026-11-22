// #/simulator: the live location demo. The user builds a road route on the map, sends the route file to core and
// drives it from here; core's trip source moves the car (simulator/sim.py) and the engine and the LLM read the same
// State.trip (position, speed, ETA, next stop, stop reached). Nothing is simulated in the browser.
import {useRef,useState} from "react";
import {EXAMPLE_POINTS,attractionKinds,stopCategories} from "./route-simulation";
import type {RoutePlanner} from "./route-simulation";
import {fmt,Metrics} from "./Panels";
import {CardArt} from "./CardArt";
import {RouteMap} from "./RouteMap";
import {useDriver} from "./driver/context";
import {categoryNames} from "./driver/contracts";

const RATES=[1,20];
const kindOf=(category:string|null|undefined)=>category==="destination"?"destination":category==="attraction"?"place of interest":category?categoryNames[category]??stopCategories.find(c=>c.id===category)?.label??category:"—";
const MAX_DETOUR_KM=5;  // simulator.yaml attraction_offset_max_m

export function Simulator({planner:sim}: {planner: RoutePlanner}) {
  const {data,fresh,command,can}=useDriver();
  const trip=fresh?data.state.trip:undefined;
  const [latitude,setLatitude]=useState("46.77"),[longitude,setLongitude]=useState("23.59");
  const [copied,setCopied]=useState("");
  const [pointsOpen,setPointsOpen]=useState(true);
  const [dragged,setDragged]=useState<number|null>(null);
  const [dropTarget,setDropTarget]=useState<number|null>(null);
  const [speed,setSpeed]=useState<number|null>(null),[seeking,setSeeking]=useState<number|null>(null),[rate,setRate]=useState<number|null>(null);
  const pointerSource=useRef<number|null>(null);
  const pointerTarget=useRef<number|null>(null);
  const total=sim.route?.distance??0;
  const coreTotal=sim.coreRoute?.distance??0;
  const fraction=seeking??(coreTotal>0&&sim.travelled!==null?sim.travelled/coreTotal:0);
  const shownSpeed=speed??sim.core?.speed_kmh??50;
  const shownRate=rate??sim.core?.time_scale??1;
  const active=Boolean(sim.core?.active);
  const file=sim.synced&&sim.core?.route?sim.core.route:sim.draft;
  function reorder(from:number,to:number){
    if(from===to||from<0||to<0||from>=sim.points.length||to>=sim.points.length)return;
    const points=[...sim.points], [point]=points.splice(from,1);
    points.splice(to,0,point);sim.edit(points);
  }
  async function copy(){
    try{await navigator.clipboard.writeText(JSON.stringify(file,null,2));setCopied("Copied")}
    catch{setCopied("Copy unavailable. Select the JSON text.")}
  }
  function download(){
    if(!file)return;
    const link=document.createElement("a");
    link.href=URL.createObjectURL(new Blob([JSON.stringify(file,null,2)],{type:"application/json"}));
    link.download="drivemate-route.json";link.click();
    setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  }
  function sendSpeed(){if(speed!==null){void command("speed",{speed});setSpeed(null);}}
  function sendSeek(){if(seeking!==null){void sim.seek(seeking);setSeeking(null);}}
  const coreStatus=sim.coreError?sim.coreError:sim.sending?"Sending route to core…":sim.synced?`Core is following this route · revision ${sim.core?.revision}`
    :active?"Core is following another route. Send this one to replace it.":sim.core?"Core is running the demo drive.":"Checking core…";
  const place=trip?.place,ahead=trip?.attractions_ahead??[];
  const chosen=sim.sights.filter(a=>a.selected).length;
  const kind=(index:number)=>index===0?"Start":index===sim.points.length-1&&sim.points.length>1?"Destination":null;
  return <div className="simulator-page content route-simulator">
    <section className="route-editor">
      <div className="route-heading"><CardArt subject="route"/><div><small>ROUTE PLANNER</small><h2>Build your route</h2></div><span className="status-pill">{sim.synced?"Sent to core":"Local draft"}</span></div>
      <p role="status">Click the map to set your start and destination. Add stops or waypoints between them, then send your route to core.</p>

      <div className="route-workspace">
        <RouteMap planner={sim} disabled={sim.adding}/>
        <div className="route-points" data-collapsed={!pointsOpen}>
          <div className="route-list-heading"><h3>Route points</h3><span>{sim.points.length}</span><button className="points-toggle" aria-label={pointsOpen?"Collapse route points":"Expand route points"} aria-expanded={pointsOpen} aria-controls="route-points-content" onClick={()=>setPointsOpen(!pointsOpen)}>{pointsOpen?"−":"+"}</button></div>
          <fieldset id="route-points-content" className="route-point-editing" hidden={!pointsOpen}>
          <div className="route-list-actions"><button disabled={sim.adding} onClick={()=>sim.edit(EXAMPLE_POINTS.map(p=>({...p})))}>Cluj–Gilău–Turda example</button><button disabled={!sim.points.length} onClick={()=>sim.edit([])}>Clear</button></div>
          {!sim.points.length&&<p className="route-empty">Add at least two points to calculate a driving route.</p>}
          <ol className="route-point-list">{sim.points.map((point,index)=><li key={point.id} data-point-index={index} data-dragging={dragged===index} data-drop-target={dropTarget===index&&dragged!==index} draggable={!sim.adding}
            onDragStart={event=>{event.dataTransfer.setData("text/plain",String(index));event.dataTransfer.effectAllowed="move";setDragged(index)}}
            onDragOver={event=>{event.preventDefault();setDropTarget(index)}}
            onDragEnd={()=>{setDragged(null);setDropTarget(null)}}
            onDrop={event=>{event.preventDefault();const value=event.dataTransfer.getData("text/plain");if(/^\d+$/.test(value))reorder(Number(value),index);setDragged(null);setDropTarget(null)}}>
            <button className="point-drag-handle" disabled={sim.adding} aria-label={`Drag to reorder point ${index+1}`} title="Drag to reorder · use the up/down arrow keys"
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
            <span className="point-number" title="Drag to reorder">{index+1}</span>
            <div className="point-description"><input aria-label={`Point name ${index+1}`} value={point.name} maxLength={80} onChange={event=>sim.rename(point.id,event.target.value)}/>
              {kind(index)?<span>{kind(index)} · {point.lat.toFixed(5)}, {point.lon.toFixed(5)}</span>:
                <select className="point-category" aria-label={`Point type ${index+1}`} value={stopCategories.some(c=>c.id===point.category)?point.category:"waypoint"} onChange={event=>sim.setCategory(point.id,event.target.value)}>
                  {stopCategories.map(c=><option key={c.id} value={c.id}>{c.label}</option>)}</select>}</div>
            <div className="point-actions"><button disabled={index===0} aria-label={`Move point ${index+1} up`} onClick={()=>reorder(index,index-1)}>↑</button><button disabled={index===sim.points.length-1} aria-label={`Move point ${index+1} down`} onClick={()=>reorder(index,index+1)}>↓</button><button aria-label={`Remove point ${index+1}`} onClick={()=>sim.edit(sim.points.filter(p=>p.id!==point.id))}>×</button></div>
          </li>)}</ol>
          <details className="point-coordinate-details"><summary>Add coordinates</summary><form className="coordinate-form" onSubmit={event=>{event.preventDefault();void sim.add({lat:Number(latitude),lon:Number(longitude)})}}>
            <label>Latitude<input name="latitude" type="number" step="any" required min="-90" max="90" value={latitude} onChange={e=>setLatitude(e.target.value)} disabled={sim.adding}/></label>
            <label>Longitude<input name="longitude" type="number" step="any" required min="-180" max="180" value={longitude} onChange={e=>setLongitude(e.target.value)} disabled={sim.adding}/></label>
            <button disabled={sim.adding} type="submit">{sim.adding?"Validating…":"Add point"}</button>
          </form></details>
          </fieldset>
        </div>
      </div>
      <div className="route-status" role="status">{sim.adding?"Checking road…":sim.status==="loading"?"Calculating route…":sim.status==="ready"?`Route calculated · ${fmt(total," km",1,2)}`:"Choose your route points."}</div>
      {sim.error&&<div className="route-error" role="alert">{sim.error}{sim.status==="error"&&<button onClick={sim.retry}>Retry routing</button>}</div>}
      <p className="route-hint">Maps and routing use OpenStreetMap and OSRM. Points snap to roads within 500 m.</p>
    </section>

    <section className="route-sights" aria-label="Places of interest pe traseu"><div className="route-heading"><CardArt subject="route"/><div><small>PLACES TO VISIT · WIKIPEDIA</small><h2>Discover along the way</h2></div></div>
      <p>Choose places worth stopping for. Your copilot uses their descriptions to suggest breaks along the route.</p>
      <div className="simulator-actions">
        <button disabled={!sim.route||sim.search.status==="loading"} onClick={sim.findAttractions}>{sim.search.status==="loading"?"Searching…":"Search again"}</button>
        <button aria-pressed={sim.placing} onClick={()=>sim.setPlacing(!sim.placing)}>{sim.placing?"Cancel placement":"Add a place on the map"}</button>
        <span role="status">{sim.search.status==="ready"?`${sim.sights.length} found · ${chosen} selected`:sim.search.status==="idle"?"Places appear after your route is calculated.":""}</span>
      </div>
      {sim.search.error&&<div className="route-error" role="alert">{sim.search.error}<button onClick={sim.findAttractions}>Retry</button></div>}
      {sim.sights.length>0&&<ul className="sight-list">{sim.sights.map(sight=>{const far=sight.detour!==null&&sight.detour>MAX_DETOUR_KM;
        return <li key={sight.id} data-selected={sight.selected}>
          <label className="sight-pick"><input type="checkbox" checked={sight.selected} onChange={()=>sim.toggleAttraction(sight.id)} aria-label={`Select ${sight.name}`}/></label>
          <div className="sight-body">
            {sight.source==="manual"?<input aria-label="Place name" value={sight.name} maxLength={80} onChange={e=>sim.editAttraction(sight.id,{name:e.target.value})}/>:<strong>{sight.name}</strong>}
            <span>{attractionKinds[sight.kind]??"Attraction"}{sight.km!==null&&` · km ${fmt(sight.km,"",1,1)}`}{sight.detour!==null&&` · ${fmt(sight.detour," km",1,1)} from route`}{sight.wikipedia&&" · Wikipedia"}</span>
            {far&&<span className="sight-warn">Too far from the route. Core accepts places within {MAX_DETOUR_KM} km.</span>}
            {sight.selected&&<textarea aria-label={`Description for ${sight.name}`} rows={2} maxLength={300} placeholder="Optional short description for your copilot"
              value={sight.description??""} onChange={e=>sim.editAttraction(sight.id,{description:e.target.value})}/>}
          </div>
          {sight.source==="manual"&&<button aria-label={`Remove ${sight.name}`} onClick={()=>sim.removeAttraction(sight.id)}>×</button>}
        </li>;})}</ul>}
      {sim.search.status==="ready"&&!sim.sights.length&&<p className="route-empty">No places found within 2 km of the route. Add one on the map.</p>}
    </section>

    <section className="location-preview"><div className="route-heading"><CardArt subject="report"/><div><small>ROUTE FILE</small><h2>Send route to core</h2></div></div>
      <p>Send this route to start the simulation. Your copilot follows the vehicle position, speed, arrival time and stops.</p>
      <div className="simulator-actions">
        <button className="primary-action" disabled={!sim.draft||sim.sending||sim.synced} onClick={()=>void sim.send(shownSpeed)}>{sim.synced?"Sent":active?"Replace core route":"Send to core"}</button>
        <button disabled={!file} onClick={download}>Download JSON</button>
        <button disabled={!file} onClick={copy}>Copy</button>
        <button disabled={!active} onClick={()=>void sim.clear()}>Remove from core</button>
        <span role="status">{copied}</span>
      </div>
      <p className={"route-sync"+(sim.coreError?" is-error":"")} role="status">{coreStatus}{sim.coreError&&<button onClick={()=>void sim.refresh()}>Retry</button>}</p>
      <details className="route-file"><summary>drivemate-route.json · {file?`${file.stops.length} stops · ${file.attractions?.length??0} places · ${file.geometry.length} road points`:"—"}</summary>
        <pre aria-label="Route JSON file">{file?JSON.stringify({...file,geometry:`[${file.geometry.length} points]`},null,2):"Build a route to generate the file."}</pre></details>
    </section>

    <section className="route-playback" aria-label="Vehicle simulation"><div className="route-heading"><CardArt subject="car"/><div><small>TRIP SIMULATION</small><h2>Trip playback</h2></div></div>
      <div className="playback-layout"><div className="playback-console"><h3>Drive controls</h3>
      <fieldset className="simulator-controls" disabled={!active||!sim.synced}>
        <div className="simulator-actions">
          <button className="primary-action" disabled={!can("start_trip")||sim.core?.arrived} onClick={()=>void command("start_trip")}>{trip?.at_poi&&!sim.core?.arrived?"Leave stop":"Start"}</button>
          <button disabled={!can("pause_trip")} onClick={()=>void command("pause_trip")}>Pause</button>
          <button disabled={!can("stop_at_poi")||!trip?.next_poi} onClick={()=>void command("stop_at_poi")}>Stop at the next stop</button>
          <button onClick={()=>void sim.seek(0)}>Back to start</button>
          <span role="status">{sim.core?.arrived?"Destination reached":trip?.at_poi?"Stopped at "+(trip.at_poi.name??trip.at_poi.id):trip&&(trip.speed_kmh??0)>0?"On the move":"Stopped"}</span>
        </div>
        <label>Vehicle speed<output>{shownSpeed} km/h</output><input type="range" min="0" max="160" value={shownSpeed} disabled={!can("set_speed")}
          onChange={e=>setSpeed(Number(e.target.value))} onPointerUp={sendSpeed} onKeyUp={sendSpeed}/></label>
        <div className="fx-segment" role="group" aria-label="Simulation speed">{RATES.map(value=><button key={value} type="button" disabled={!can("set_rate")} aria-pressed={shownRate===value}
          onClick={()=>{setRate(value);void command("set_rate",{rate:value});}}>×{value}</button>)}<small>Simulation speed</small></div>
        <label>Route progress<output>{fmt(fraction,"%",100,1)}</output><input aria-label="Route progress" type="range" min="0" max="1" step=".001" value={fraction} disabled={!coreTotal}
          onChange={e=>setSeeking(Number(e.target.value))} onPointerUp={sendSeek} onKeyUp={sendSeek}/></label>
      </fieldset>
      {!active&&<p className="route-lock-note">Send your route to core to start driving.</p>}
      </div><div className="playback-readings"><h3>Trip overview</h3>
      <Metrics items={[["Speed",fmt(trip?.speed_kmh," km/h",1,0)],["Travelled",sim.travelled===null?"—":fmt(sim.travelled," km",1,2)],["Remaining",sim.travelled===null?"—":fmt(coreTotal-sim.travelled," km",1,2)],["Arrival in",fmt(trip?.eta_min," min",1,0)]]}/>
      <h3>Route context</h3>
      <dl className="route-trip">
        <div><dt>Next stop</dt><dd>{trip?.next_poi?`${trip.next_poi.name??trip.next_poi.id} · ${kindOf(trip.next_poi.category)} · ${fmt(trip.next_poi.dist_km," km",1,1)}`:"—"}</dd></div>
        <div><dt>Stopped at</dt><dd>{trip?.at_poi?`${trip.at_poi.name??trip.at_poi.id} · ${kindOf(trip.at_poi.category)}`:"—"}</dd></div>
        <div><dt>Coordinates</dt><dd>{trip?.pos?`${fmt(trip.pos.lat,"",1,5)}, ${fmt(trip.pos.lon,"",1,5)}`:"—"}</dd></div>
        <div><dt>Road</dt><dd>{trip?.road==="highway"?"highway":trip?.road==="city"?"city":trip?.road??"—"}</dd></div>
        <div className="route-trip-wide"><dt>Current location</dt><dd>{place?.after?<>After {place.after} ({fmt(place.after_km," km",1,1)}){place.before&&<> · before {place.before} ({fmt(place.before_km," km",1,1)})</>} · destination {place.destination} in {fmt(place.destination_km," km",1,1)}</>:"—"}</dd></div>
        <div className="route-trip-wide"><dt>Places ahead</dt><dd>{ahead.length?ahead.map(a=>`${a.name} · ${fmt(a.dist_km," km",1,1)}`).join(" · "):"—"}</dd></div>
      </dl></div></div>
    </section>
  </div>;
}
