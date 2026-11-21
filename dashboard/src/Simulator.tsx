// #/simulator: the live location demo. The user builds a road route on the map, sends the route file to core and
// drives it from here; core's trip source moves the car (simulator/sim.py) and the engine and the LLM read the same
// State.trip (position, speed, ETA, next stop, stop reached). Nothing is simulated in the browser.
import {useRef,useState} from "react";
import {EXAMPLE_POINTS,attractionKinds,stopCategories} from "./route-simulation";
import type {RoutePlanner} from "./route-simulation";
import {fmt,Metrics} from "./Panels";
import {RouteMap} from "./RouteMap";
import {useDriver} from "./driver/context";
import {categoryNames} from "./driver/contracts";

const RATES=[1,20];
const kindOf=(category:string|null|undefined)=>category==="destination"?"destinație":category==="attraction"?"obiectiv turistic":category?categoryNames[category]??stopCategories.find(c=>c.id===category)?.label??category:"—";
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
    try{await navigator.clipboard.writeText(JSON.stringify(file,null,2));setCopied("Copiat")}
    catch{setCopied("Copiere indisponibilă. Selectează textul JSON.")}
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
  const coreStatus=sim.coreError?sim.coreError:sim.sending?"Se trimite traseul la core…":sim.synced?`Core urmează acest traseu · revizia ${sim.core?.revision}`
    :active?"Core urmează alt traseu. Trimite-l pe acesta ca să îl înlocuiești.":sim.core?"Core nu are traseu de hartă · rulează drumul demonstrativ.":"Se verifică core…";
  const place=trip?.place,ahead=trip?.attractions_ahead??[];
  const chosen=sim.sights.filter(a=>a.selected).length;
  const kind=(index:number)=>index===0?"Plecare":index===sim.points.length-1&&sim.points.length>1?"Destinație":null;
  return <div className="simulator-page content route-simulator">
    <section className="route-editor">
      <div className="route-heading"><div><small>PLANIFICARE TRASEU</small><h2>Construiește traseul</h2></div><span className="status-pill">{sim.synced?"Trimis la core":"Ciornă locală"}</span></div>
      <p role="status">Apasă pe hartă pentru a adăuga puncte: primul este plecarea, ultimul destinația, iar cele dintre ele opriri (benzinărie, cafenea…) sau puncte de trecere. Trimite apoi traseul la core.</p>

      <div className="route-workspace">
        <RouteMap planner={sim} disabled={sim.adding} pointsOpen={pointsOpen} onOpenLayers={()=>setPointsOpen(false)}/>
        <div className="route-points" data-collapsed={!pointsOpen}>
          <div className="route-list-heading"><h3>Puncte de traseu</h3><span>{sim.points.length}</span><button className="points-toggle" aria-label={pointsOpen?"Restrânge lista de puncte":"Extinde lista de puncte"} aria-expanded={pointsOpen} aria-controls="route-points-content" onClick={()=>setPointsOpen(!pointsOpen)}>{pointsOpen?"−":"+"}</button></div>
          <fieldset id="route-points-content" className="route-point-editing" hidden={!pointsOpen}>
          <div className="route-list-actions"><button disabled={sim.adding} onClick={()=>sim.edit(EXAMPLE_POINTS.map(p=>({...p})))}>Exemplu Cluj–Gilău–Turda</button><button disabled={!sim.points.length} onClick={()=>sim.edit([])}>Golește</button></div>
          {!sim.points.length&&<p className="route-empty">Adaugă cel puțin două puncte pentru a calcula un traseu auto.</p>}
          <ol className="route-point-list">{sim.points.map((point,index)=><li key={point.id} data-point-index={index} data-dragging={dragged===index} data-drop-target={dropTarget===index&&dragged!==index} draggable={!sim.adding}
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
            <div className="point-description"><input aria-label={`Numele punctului ${index+1}`} value={point.name} maxLength={80} onChange={event=>sim.rename(point.id,event.target.value)}/>
              {kind(index)?<span>{kind(index)} · {point.lat.toFixed(5)}, {point.lon.toFixed(5)}</span>:
                <select className="point-category" aria-label={`Tipul punctului ${index+1}`} value={stopCategories.some(c=>c.id===point.category)?point.category:"waypoint"} onChange={event=>sim.setCategory(point.id,event.target.value)}>
                  {stopCategories.map(c=><option key={c.id} value={c.id}>{c.label}</option>)}</select>}</div>
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
      <p className="route-hint">Harta și calculul traseului folosesc servicii online OpenStreetMap / OSRM. Punctele sunt aliniate la drumuri aflate la maximum 500 m.</p>
    </section>

    <section className="route-sights" aria-label="Obiective turistice pe traseu"><small>OBIECTIVE TURISTICE · WIKIPEDIA</small><h2>Ce e de văzut pe drum</h2>
      <p>Obiectivele alese merg în fișierul de traseu. Core le propune ca pauză pe drum, iar asistentul le pomenește doar cu datele de aici.</p>
      <div className="simulator-actions">
        <button disabled={!sim.route||sim.search.status==="loading"} onClick={sim.findAttractions}>{sim.search.status==="loading"?"Se caută…":"Caută din nou"}</button>
        <button aria-pressed={sim.placing} onClick={()=>sim.setPlacing(!sim.placing)}>{sim.placing?"Anulează adăugarea":"Adaugă obiectiv pe hartă"}</button>
        <span role="status">{sim.search.status==="ready"?`${sim.sights.length} găsite · ${chosen} alese`:sim.search.status==="idle"?"Se caută după ce traseul e calculat.":""}</span>
      </div>
      {sim.search.error&&<div className="route-error" role="alert">{sim.search.error}<button onClick={sim.findAttractions}>Reîncearcă</button></div>}
      {sim.sights.length>0&&<ul className="sight-list">{sim.sights.map(sight=>{const far=sight.detour!==null&&sight.detour>MAX_DETOUR_KM;
        return <li key={sight.id} data-selected={sight.selected}>
          <label className="sight-pick"><input type="checkbox" checked={sight.selected} onChange={()=>sim.toggleAttraction(sight.id)} aria-label={`Alege ${sight.name}`}/></label>
          <div className="sight-body">
            {sight.source==="manual"?<input aria-label="Numele obiectivului" value={sight.name} maxLength={80} onChange={e=>sim.editAttraction(sight.id,{name:e.target.value})}/>:<strong>{sight.name}</strong>}
            <span>{attractionKinds[sight.kind]??"Atracție"}{sight.km!==null&&` · km ${fmt(sight.km,"",1,1)}`}{sight.detour!==null&&` · ${fmt(sight.detour," km",1,1)} de drum`}{sight.wikipedia&&" · Wikipedia"}</span>
            {far&&<span className="sight-warn">Prea departe de drum: core primește obiective la cel mult {MAX_DETOUR_KM} km.</span>}
            {sight.selected&&<textarea aria-label={`Descrierea pentru ${sight.name}`} rows={2} maxLength={300} placeholder="Descriere scurtă (opțional), din care asistentul poate spune un lucru"
              value={sight.description??""} onChange={e=>sim.editAttraction(sight.id,{description:e.target.value})}/>}
          </div>
          {sight.source==="manual"&&<button aria-label={`Șterge ${sight.name}`} onClick={()=>sim.removeAttraction(sight.id)}>×</button>}
        </li>;})}</ul>}
      {sim.search.status==="ready"&&!sim.sights.length&&<p className="route-empty">Niciun obiectiv la mai puțin de 2 km de drum. Poți adăuga unul pe hartă.</p>}
    </section>

    <section className="location-preview"><small>FIȘIERUL DE TRASEU · INPUT PENTRU CORE</small><h2>Trimite traseul la core</h2>
      <p>Core mută mașina pe acest traseu. Engine-ul și LLM-ul primesc poziția, viteza, ETA, următoarea oprire și oprirea atinsă.</p>
      <div className="simulator-actions">
        <button className="primary-action" disabled={!sim.draft||sim.sending||sim.synced} onClick={()=>void sim.send(shownSpeed)}>{sim.synced?"Trimis":active?"Înlocuiește traseul din core":"Trimite la core"}</button>
        <button disabled={!file} onClick={download}>Descarcă JSON</button>
        <button disabled={!file} onClick={copy}>Copiază</button>
        <button disabled={!active} onClick={()=>void sim.clear()}>Scoate din core</button>
        <span role="status">{copied}</span>
      </div>
      <p className={"route-sync"+(sim.coreError?" is-error":"")} role="status">{coreStatus}{sim.coreError&&<button onClick={()=>void sim.refresh()}>Reîncearcă</button>}</p>
      <details className="route-file"><summary>drivemate-route.json · {file?`${file.stops.length} opriri · ${file.attractions?.length??0} obiective · ${file.geometry.length} puncte de drum`:"—"}</summary>
        <pre aria-label="Fișierul de traseu JSON">{file?JSON.stringify({...file,geometry:`[${file.geometry.length} puncte]`},null,2):"Construiește un traseu pentru a genera fișierul."}</pre></details>
    </section>

    <section className="route-playback" aria-label="Deplasarea mașinii în core"><small>REDARE · CORE</small><h2>Deplasarea mașinii</h2>
      <fieldset className="simulator-controls" disabled={!active||!sim.synced}>
        <div className="simulator-actions">
          <button className="primary-action" disabled={!can("start_trip")||sim.core?.arrived} onClick={()=>void command("start_trip")}>{trip?.at_poi&&!sim.core?.arrived?"Pleacă de la oprire":"Pornește"}</button>
          <button disabled={!can("pause_trip")} onClick={()=>void command("pause_trip")}>Pauză</button>
          <button disabled={!can("stop_at_poi")||!trip?.next_poi} onClick={()=>void command("stop_at_poi")}>Oprește la următoarea oprire</button>
          <button onClick={()=>void sim.seek(0)}>Revino la start</button>
          <span role="status">{sim.core?.arrived?"Destinație atinsă":trip?.at_poi?"Oprit la "+(trip.at_poi.name??trip.at_poi.id):trip&&(trip.speed_kmh??0)>0?"În deplasare":"Oprit"}</span>
        </div>
        <label>Viteza mașinii<output>{shownSpeed} km/h</output><input type="range" min="0" max="160" value={shownSpeed} disabled={!can("set_speed")}
          onChange={e=>setSpeed(Number(e.target.value))} onPointerUp={sendSpeed} onKeyUp={sendSpeed}/></label>
        <div className="fx-segment" role="group" aria-label="Ritmul timpului în core">{RATES.map(value=><button key={value} type="button" disabled={!can("set_rate")} aria-pressed={shownRate===value}
          onClick={()=>{setRate(value);void command("set_rate",{rate:value});}}>×{value}</button>)}<small>Ritmul timpului în core</small></div>
        <label>Poziție pe traseu<output>{fmt(fraction,"%",100,1)}</output><input aria-label="Poziție pe traseu" type="range" min="0" max="1" step=".001" value={fraction} disabled={!coreTotal}
          onChange={e=>setSeeking(Number(e.target.value))} onPointerUp={sendSeek} onKeyUp={sendSeek}/></label>
      </fieldset>
      {!active&&<p className="route-lock-note">Trimite traseul la core pentru a-l parcurge.</p>}
      <Metrics items={[["Viteză",fmt(trip?.speed_kmh," km/h",1,0)],["Parcurs",sim.travelled===null?"—":fmt(sim.travelled," km",1,2)],["Rămas",sim.travelled===null?"—":fmt(coreTotal-sim.travelled," km",1,2)],["Până la destinație",fmt(trip?.eta_min," min",1,0)]]}/>
      <dl className="route-trip">
        <div><dt>Următoarea oprire</dt><dd>{trip?.next_poi?`${trip.next_poi.name??trip.next_poi.id} · ${kindOf(trip.next_poi.category)} · ${fmt(trip.next_poi.dist_km," km",1,1)}`:"—"}</dd></div>
        <div><dt>Oprit la</dt><dd>{trip?.at_poi?`${trip.at_poi.name??trip.at_poi.id} · ${kindOf(trip.at_poi.category)}`:"—"}</dd></div>
        <div><dt>Poziție (State.trip.pos)</dt><dd>{trip?.pos?`${fmt(trip.pos.lat,"",1,5)}, ${fmt(trip.pos.lon,"",1,5)}`:"—"}</dd></div>
        <div><dt>Drum</dt><dd>{trip?.road==="highway"?"autostradă":trip?.road==="city"?"oraș":trip?.road??"—"}</dd></div>
        <div className="route-trip-wide"><dt>Unde e mașina (trip.place · ce vede LLM-ul)</dt><dd>{place?.after?<>După {place.after} ({fmt(place.after_km," km",1,1)}){place.before&&<> · înainte de {place.before} ({fmt(place.before_km," km",1,1)})</>} · destinația {place.destination} în {fmt(place.destination_km," km",1,1)}</>:"—"}</dd></div>
        <div className="route-trip-wide"><dt>Obiective în față (trip.attractions_ahead)</dt><dd>{ahead.length?ahead.map(a=>`${a.name} · ${fmt(a.dist_km," km",1,1)}`).join(" · "):"—"}</dd></div>
      </dl>
    </section>
  </div>;
}
