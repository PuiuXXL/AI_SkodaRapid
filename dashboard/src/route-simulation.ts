import {useEffect, useMemo, useRef, useState} from "react";
import type {SimulationSettings} from "./session";

export interface RoutePoint { id: string; name: string; lat: number; lon: number }
export interface Coordinate { lat: number; lon: number }
export function validCoordinate(point: Coordinate) {
  return Number.isFinite(point.lat) && Number.isFinite(point.lon) &&
    point.lat >= -90 && point.lat <= 90 && point.lon >= -180 && point.lon <= 180;
}
export function distanceKm(a: Coordinate, b: Coordinate) {
  const radians = Math.PI / 180;
  const latitude = Math.sin((b.lat-a.lat)*radians/2);
  const longitude = Math.sin((b.lon-a.lon)*radians/2);
  return 12742*Math.asin(Math.sqrt(Math.min(1,latitude*latitude+
    Math.cos(a.lat*radians)*Math.cos(b.lat*radians)*longitude*longitude)));
}
export function locateOnRoute(geometry: Coordinate[], cumulative: number[], distance: number) {
  const total=cumulative.at(-1)??0;
  const travelled=Math.max(0,Math.min(total,distance));
  let low=1, high=geometry.length-1;
  while(low<high){const middle=Math.floor((low+high)/2);if(cumulative[middle]<travelled)low=middle+1;else high=middle;}
  const end=geometry[low]??geometry[0], start=geometry[low-1]??end;
  if(!start || !end)return null;
  const length=(cumulative[low]??0)-(cumulative[low-1]??0);
  const fraction=length>0?(travelled-cumulative[low-1])/length:0;
  const lat=start.lat+(end.lat-start.lat)*fraction,lon=start.lon+(end.lon-start.lon)*fraction;
  const r=Math.PI/180, delta=(end.lon-start.lon)*r;
  const heading=(Math.atan2(Math.sin(delta)*Math.cos(end.lat*r),
    Math.cos(start.lat*r)*Math.sin(end.lat*r)-Math.sin(start.lat*r)*Math.cos(end.lat*r)*Math.cos(delta))/r+360)%360;
  return {lat,lon,heading};
}

interface RoadRoute { geometry: Coordinate[]; cumulative: number[]; distance: number }
interface RoutingResponse {
  code: string;
  routes?: {geometry:{coordinates:number[][]}}[];
}
export const EXAMPLE_POINTS: RoutePoint[] = [
  {id:"cluj",name:"Cluj-Napoca",lat:46.769,lon:23.589},
  {id:"gilau",name:"Gilău · acces A3",lat:46.7507,lon:23.3907},
  {id:"turda",name:"Turda",lat:46.5667,lon:23.7833}
];

export function useRouteSimulation(settings: SimulationSettings, onPause: () => void) {
  const [points,setPoints]=useState<RoutePoint[]>([]);
  const [route,setRoute]=useState<RoadRoute|null>(null);
  const [status,setStatus]=useState<"empty"|"loading"|"ready"|"error">("empty");
  const [error,setError]=useState("");
  const [adding,setAdding]=useState(false);
  const [revision,retry]=useState(0);
  const [progress,setProgress]=useState({distance:0,elapsed:0});
  const editingLocked=Boolean(settings.running&&route&&progress.distance<route.distance);
  const addRequest=useRef<AbortController|null>(null);
  const editVersion=useRef(0);
  const pauseRef=useRef(onPause);
  useEffect(()=>{pauseRef.current=onPause},[onPause]);
  useEffect(()=>()=>addRequest.current?.abort(),[]);

  function edit(next: RoutePoint[]) {
    if(editingLocked)return;
    editVersion.current++;
    addRequest.current?.abort();
    setAdding(false);
    pauseRef.current();
    setRoute(null);setProgress({distance:0,elapsed:0});setError("");
    setStatus(next.length>1?"loading":"empty");
    setPoints(next);
    retry(old=>old+1);
  }
  async function add(point: Coordinate, replaceId?: string) {
    if(editingLocked || adding || addRequest.current)return;
    if(!validCoordinate(point)){setError("Introdu coordonate valide: latitudine între −90 și 90, longitudine între −180 și 180.");return;}
    const controller=new AbortController();
    addRequest.current=controller;
    const version=editVersion.current;
    setAdding(true);setError("");
    try{
      const response=await fetch(`https://router.project-osrm.org/nearest/v1/driving/${point.lon},${point.lat}?number=1`,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(15000)])});
      if(!response.ok)throw new Error("Validarea punctului nu este disponibilă. Reîncearcă.");
      const result=await response.json() as {code:string;waypoints?:{location:number[];distance:number}[]};
      const road=result.waypoints?.[0];
      if(result.code!=="Ok"||!road||road.distance>500)throw new Error("Punctul este la peste 500 m de un drum accesibil. Alege un punct mai aproape de drum.");
      const snapped={lat:road.location[1],lon:road.location[0]};
      if(!validCoordinate(snapped))throw new Error("Serviciul de rutare a returnat coordonate invalide.");
      if(points.some(p=>p.id!==replaceId&&distanceKm(p,snapped)<.01))throw new Error("Există deja un punct la această poziție.");
      if(version!==editVersion.current)return;
      edit(replaceId?points.map(p=>p.id===replaceId?{...p,...snapped}:p):[...points,{...snapped,id:crypto.randomUUID(),name:`Punct ${points.length+1}`}]);
    }catch(cause){
      if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Punctul nu a putut fi validat.");
    }finally{
      if(addRequest.current===controller){addRequest.current=null;setAdding(false);}
    }
  }
  const routeKey=points.map(p=>`${p.lat},${p.lon}`).join(";");
  useEffect(()=>{
    if(points.length<2){setRoute(null);setStatus("empty");return;}
    const controller=new AbortController();
    setStatus("loading");setRoute(null);setProgress({distance:0,elapsed:0});
    const timer=setTimeout(async()=>{
      try{
        const coordinates=points.map(p=>`${p.lon},${p.lat}`).join(";");
        const radiuses=points.map(()=>"500").join(";");
        const response=await fetch(`https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson&radiuses=${radiuses}`,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
        if(!response.ok)throw new Error("Serviciul de rutare nu răspunde. Reîncearcă.");
        const result=await response.json() as RoutingResponse;
        const geometry=result.routes?.[0]?.geometry.coordinates.map(([lon,lat])=>({lat,lon}));
        if(result.code!=="Ok"||!geometry||geometry.length<2)throw new Error("Nu există un traseu auto între punctele alese.");
        if(geometry.some(p=>!validCoordinate(p)))throw new Error("Serviciul de rutare a returnat un traseu invalid.");
        const cumulative=[0];
        for(let i=1;i<geometry.length;i++)cumulative.push(cumulative[i-1]+distanceKm(geometry[i-1],geometry[i]));
        if(cumulative.at(-1)!<=0)throw new Error("Traseul trebuie să conțină puncte distincte.");
        if(controller.signal.aborted)return;
        setRoute({geometry,cumulative,distance:cumulative.at(-1)!});setStatus("ready");setError("");
      }catch(cause){
        if(!controller.signal.aborted){setStatus("error");setError(cause instanceof Error?cause.message:"Traseu indisponibil.");}
      }
    },350);
    return ()=>{controller.abort();clearTimeout(timer)};
  },[routeKey,revision]);
  useEffect(()=>{setProgress({distance:0,elapsed:0})},[settings.reset]);
  useEffect(()=>{
    if(!route||!settings.running)return;
    let last=performance.now();
    const timer=setInterval(()=>{
      const now=performance.now(),seconds=(now-last)/1000*settings.rate;last=now;
      setProgress(old=>{
        const remaining=route.distance-old.distance;
        const usedSeconds=settings.speed>0?Math.min(seconds,Math.max(0,remaining)*3600/settings.speed):seconds;
        return {distance:Math.min(route.distance,old.distance+settings.speed*usedSeconds/3600),elapsed:old.elapsed+usedSeconds};
      });
    },100);
    return ()=>clearInterval(timer);
  },[route,settings.running,settings.speed,settings.rate]);
  const completed=Boolean(route&&progress.distance>=route.distance);
  useEffect(()=>{if(completed&&settings.running)pauseRef.current()},[completed,settings.running]);
  const position=useMemo(()=>route?locateOnRoute(route.geometry,route.cumulative,progress.distance):points[0]?{lat:points[0].lat,lon:points[0].lon,heading:0}:null,[route,progress.distance,points]);
  return {points,route,status,error,adding,progress,position,completed,editingLocked,add,edit,
    rename:(id:string,name:string)=>{if(!editingLocked)setPoints(old=>old.map(p=>p.id===id?{...p,name}:p))},
    retry:()=>retry(old=>old+1),
    seek:(fraction:number)=>{pauseRef.current();setProgress({distance:(route?.distance??0)*fraction,elapsed:settings.speed>0?(route?.distance??0)*fraction/settings.speed*3600:0})}
  };
}
export type RouteSimulation = ReturnType<typeof useRouteSimulation>;
