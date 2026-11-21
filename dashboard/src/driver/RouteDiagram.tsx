import {useId} from "react";
import type {Point,Road} from "./contracts";

export function RouteDiagram({route,position,blind=[],selected,onSelect}: {route?:Road;position?:Point;selected?:string;onSelect?:(id:string)=>void;blind?:{from:Point;to:Point}[]}) {
  const id=useId();
  if(!route?.geometry?.length)return <p className="empty-state">Traseul nu este disponibil în această sesiune.</p>;
  const coordinates=route.geometry;
  const latitudes=coordinates.map(p=>p.lat),longitudes=coordinates.map(p=>p.lon);
  const minLat=Math.min(...latitudes),minLon=Math.min(...longitudes);
  const spanLat=Math.max(.005,Math.max(...latitudes)-minLat),spanLon=Math.max(.005,Math.max(...longitudes)-minLon);
  const scale=Math.min(500/spanLon,220/spanLat);
  const x=(p:Point)=>50+(500-spanLon*scale)/2+(p.lon-minLon)*scale;
  const y=(p:Point)=>40+(220-spanLat*scale)/2+(minLat+spanLat-p.lat)*scale;
  return <figure className="driver-route"><svg viewBox="0 0 600 300" role={onSelect?"group":"img"} aria-labelledby={id}>
    <title id={id}>Schemă a traseului, opriri și poziția raportată{blind.length?"; segmentele roșii indică metrii orbi măsurați":""}.</title>
    <defs><pattern id={id+"-grid"} width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="var(--ui-stroke)" strokeWidth=".6"/></pattern></defs>
    <rect width="600" height="300" rx="12" fill="var(--ui-inset)"/><rect width="600" height="300" fill={`url(#${id}-grid)`}/>
    <polyline points={coordinates.map(p=>`${x(p)},${y(p)}`).join(" ")} fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinejoin="round"/>
    {blind.map((segment,i)=><line key={i} x1={x(segment.from)} y1={y(segment.from)} x2={x(segment.to)} y2={y(segment.to)} stroke="var(--ui-danger)" strokeWidth="7"/>)}
    {route.stops.map((p,i)=><g key={p.id} className={onSelect?"route-point":undefined} role={onSelect?"button":undefined} tabIndex={onSelect?0:undefined} aria-label={onSelect?p.name:undefined} aria-pressed={onSelect?selected===p.id:undefined} onClick={()=>onSelect?.(p.id)} onKeyDown={e=>{if(onSelect&&(e.key==="Enter"||e.key===" ")){e.preventDefault();onSelect(p.id);}}}><circle cx={x(p)} cy={y(p)} r="18" fill="transparent"/><circle cx={x(p)} cy={y(p)} r={selected===p.id?10:7} fill={selected===p.id?"var(--accent)":"var(--ui-surface-1)"} stroke="var(--accent)" strokeWidth="2"/><text x={x(p)+12} y={y(p)-12} fill="var(--muted)" fontSize="12">{i+1}</text></g>)}
    {position&&<g pointerEvents="none"><circle cx={x(position)} cy={y(position)} r="12" fill="var(--ui-accent-dim)" stroke="var(--accent)"/><circle cx={x(position)} cy={y(position)} r="5" fill="var(--accent)"/></g>}
  </svg><figcaption>Schemă orientativă · {route.stops.length} opriri · {route.total.toLocaleString("ro-RO",{maximumFractionDigits:1})} km</figcaption></figure>;
}
