// Route planning on the map (#/simulator) and the route file core follows (simulator/route.py, core/route_api.py).
// The map draws a road route (OSRM) through the points; the page turns it into the route file, sends it to core
// (PUT /simulator/route) and lets the user download it. Core's trip source then moves the car along it: the car on
// the map is where core says it is (State.trip.pos), and the engine and the LLM read the same trip.
// Tourist sights near the road come from Wikipedia (geosearch, with the article's summary), or are added by hand;
// the chosen ones travel in the route file and core proposes them as breaks (core/attractions.py).
import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import type {Trip} from "./types";

export interface Coordinate { lat: number; lon: number }
export interface RoutePoint extends Coordinate { id: string; name: string; category: string }
export interface RoadRoute { geometry: Coordinate[]; cumulative: number[]; distance: number }
/** A tourist sight near the road. ``description`` comes from Wikipedia or the user, never from the LLM. */
export interface Attraction extends Coordinate {
  id: string; name: string; kind: string; description?: string; wikipedia?: string; source: "wikipedia" | "manual";
  selected: boolean; score?: number;
}
export const attractionKinds: Record<string,string>={attraction:"Atracție",viewpoint:"Belvedere",museum:"Muzeu",castle:"Castel",
  fort:"Cetate",monument:"Monument",ruins:"Ruine",archaeological_site:"Sit arheologic",monastery:"Mănăstire",nature:"Natură",church:"Lăcaș de cult",
  palace:"Palat",manor:"Conac"};

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
/** The road's nearest point to ``point``: its distance along the road and how far ``point`` is from it (km). */
export function nearestOnRoute(geometry: Coordinate[], cumulative: number[], point: Coordinate) {
  const k=Math.cos(point.lat*Math.PI/180);
  let best=Infinity,km=0;
  for(let i=0;i<geometry.length-1;i++){
    const a=geometry[i],b=geometry[i+1];
    const ax=(a.lon-point.lon)*k,ay=a.lat-point.lat,dx=(b.lon-a.lon)*k,dy=b.lat-a.lat,length=dx*dx+dy*dy;
    const t=length?Math.max(0,Math.min(1,-(ax*dx+ay*dy)/length)):0;
    const px=ax+t*dx,py=ay+t*dy,d=px*px+py*py;
    if(d<best){best=d;km=cumulative[i]+t*(cumulative[i+1]-cumulative[i]);}
  }
  return {km,offset:Math.sqrt(best)*Math.PI/180*6371};
}
/** Distance along the road (km) of the road's nearest point to ``point``. */
export function projectOnRoute(geometry: Coordinate[], cumulative: number[], point: Coordinate) {
  return nearestOnRoute(geometry,cumulative,point).km;
}
export function roadRoute(geometry: Coordinate[]): RoadRoute | null {
  if(geometry.length<2||geometry.some(p=>!validCoordinate(p)))return null;
  const cumulative=[0];
  for(let i=1;i<geometry.length;i++)cumulative.push(cumulative[i-1]+distanceKm(geometry[i-1],geometry[i]));
  return cumulative.at(-1)!>0?{geometry,cumulative,distance:cumulative.at(-1)!}:null;
}

/** Stop categories: the reminders' POI categories (assistant.yaml) plus a waypoint that only shapes the road. */
export const stopCategories=[
  {id:"fuel",label:"Benzinărie"},{id:"cafe",label:"Cafenea"},{id:"pharmacy",label:"Farmacie"},
  {id:"supermarket",label:"Supermarket"},{id:"auto_parts",label:"Piese auto"},{id:"waypoint",label:"Punct de trecere"},
] as const;
export const EXAMPLE_POINTS: RoutePoint[] = [
  {id:"cluj",name:"Cluj-Napoca",category:"origin",lat:46.769,lon:23.589},
  {id:"gilau",name:"Benzinărie · Gilău",category:"fuel",lat:46.7507,lon:23.3907},
  {id:"turda",name:"Turda",category:"destination",lat:46.5667,lon:23.7833}
];

/** The route file (simulator/route.py, ``drivemate_route`` v1): origin, stops in order, destination last, the road. */
export interface RouteFile {
  type:"drivemate_route"; version:1; id:string; name:string; source:"dashboard_map"; created_ts:number;
  origin:{id:string;name:string;category:"origin";lat:number;lon:number};
  stops:{id:string;name:string;category:string;lat:number;lon:number}[];
  geometry:Coordinate[]; distance_km:number; speed_kmh?:number;
  attractions?:{id:string;name:string;kind:string;lat:number;lon:number;description?:string;wikipedia?:string;source:string}[];
}
const round=(value:number,digits:number)=>Number(value.toFixed(digits));
export function routeFile(points: RoutePoint[], route: RoadRoute | null, options: {id:string;ts:number;speed?:number;attractions?:Attraction[]}): RouteFile | null {
  if(points.length<2||!route)return null;
  const named=(point:RoutePoint,index:number)=>point.name.trim().slice(0,80)||`Punct ${index+1}`;
  const [origin,...rest]=points;
  const chosen=(options.attractions??[]).filter(a=>a.selected);
  return {type:"drivemate_route",version:1,id:options.id,name:`${named(origin,0)} → ${named(points.at(-1)!,points.length-1)}`.slice(0,120),
    source:"dashboard_map",created_ts:round(options.ts,3),
    origin:{id:origin.id,name:named(origin,0),category:"origin",lat:origin.lat,lon:origin.lon},
    stops:rest.map((point,i)=>({id:point.id,name:named(point,i+1),
      category:i===rest.length-1?"destination":stopCategories.some(c=>c.id===point.category)?point.category:"waypoint",lat:point.lat,lon:point.lon})),
    geometry:route.geometry.map(p=>({lat:round(p.lat,6),lon:round(p.lon,6)})),distance_km:round(route.distance,3),
    ...(options.speed===undefined?{}:{speed_kmh:options.speed}),
    ...(chosen.length?{attractions:chosen.map(a=>({id:a.id,name:a.name.trim().slice(0,80)||"Obiectiv",kind:a.kind,lat:round(a.lat,6),lon:round(a.lon,6),
      ...(a.description?.trim()?{description:a.description.trim().slice(0,300)}:{}),...(a.wikipedia?{wikipedia:a.wikipedia.slice(0,200)}:{}),source:a.source}))}:{})};
}
export function pointsOf(file: RouteFile): RoutePoint[] {
  return [file.origin,...file.stops].map(p=>({id:p.id,name:p.name,category:p.category,lat:p.lat,lon:p.lon}));
}
export function attractionsOf(file: RouteFile): Attraction[] {
  return (file.attractions??[]).map(a=>({...a,source:a.source==="manual"?"manual":"wikipedia",selected:true}));
}
const pointsKey=(points:RoutePoint[])=>points.map(p=>`${p.id}:${p.lat},${p.lon}`).join(";");
/** What makes two route files the same route for core (not their id, time or the order core writes the fields in). */
const fileKey=(file:RouteFile)=>JSON.stringify([file.distance_km,...[file.origin,...file.stops].map(p=>[p.id,p.name,p.category,p.lat,p.lon]),
  ...(file.attractions??[]).map(a=>[a.id,a.name,a.kind,a.lat,a.lon,a.description??"",a.wikipedia??"",a.source])]);

// --- Tourist sights: Wikipedia articles with coordinates within SEARCH_KM of the road -----------------------------
// Wikipedia's geosearch answers in under a second (the public OpenStreetMap Overpass server did not answer from the
// team's network). Places (villages, communes, towns) and articles that do not name a sight are dropped; the
// description comes from the same article, so what the assistant may say is what Wikipedia says.
export const SEARCH_KM=2;
const MAX_FOUND=14,PRESELECT=6,MAX_CALLS=24,WIKI_LANG="ro";
/** Points along the road whose search circles cover a SEARCH_KM corridor: [{lat, lon, radius_m}]; about one per 15 km. */
export function searchCircles(road:RoadRoute){
  const spacing=Math.max(15,road.distance/(MAX_CALLS-1));
  const radius=Math.min(10000,Math.ceil(Math.sqrt((spacing/2)**2+SEARCH_KM**2)*1000)+200);
  const count=Math.max(1,Math.ceil(road.distance/spacing)+1);
  return Array.from({length:count},(_,i)=>{const at=locateOnRoute(road.geometry,road.cumulative,Math.min(road.distance,i*spacing))!;return {lat:at.lat,lon:at.lon,radius};});
}
export function geosearchUrl(circle:{lat:number;lon:number;radius:number}){
  return `https://${WIKI_LANG}.wikipedia.org/w/api.php?action=query&format=json&origin=*&generator=geosearch`+
    `&ggscoord=${circle.lat.toFixed(5)}|${circle.lon.toFixed(5)}&ggsradius=${circle.radius}&ggslimit=100&prop=coordinates|description&colimit=max`;
}
export interface WikiPage {pageid:number;title:string;description?:string;coordinates?:{lat:number;lon:number}[]}
// Title / description words -> kind and how strongly it is a sight (3: worth a break, 1: on the way).
const KINDS:[RegExp,string,number][]=[
  [/\bsalin/i,"attraction",3],[/\b(chei|defileu|peșter|pester|cascad|rezervați|rezervati|parcul natural|lacul|vârful|varful)/i,"nature",3],
  [/\bcastel/i,"castle",3],[/\b(cetat|castru|fortăre|fortare)/i,"fort",3],[/\bmuze(u|ul)\b/i,"museum",3],
  [/\bpalat/i,"palace",2],[/\bconac/i,"manor",2],[/\b(mănăstir|manastir|schit)/i,"monastery",2],
  [/\b(sit arheologic|dava|ruine)/i,"archaeological_site",2],[/\b(belvedere|panoram)/i,"viewpoint",2],
  [/\b(statui|monument|memorial|obelisc)/i,"monument",1],[/\b(biseric|catedral|sinagog|templ|moschee)/i,"church",1],
];
const PLACE=/^(sat|comună|comuna|municipiu|oraș|oras|localitate|cartier|râu|rau|pârâu|parau)\b|\b(sat|comună|municipiu|oraș) (în|din)\b/i;
const NOT_A_SIGHT=/^(Comuna|Piața|Strada|Bulevardul|Calea|Cartierul|Gara|Stadionul|Universitatea|Liceul|Colegiul|Școala|Spitalul|Aeroportul)\b/;
// Spread along the road: at most PER_WINDOW sights per WINDOW_KM (a city has dozens), one of them chosen by default,
// and none chosen in the first START_KM (the car is there before core may propose anything).
const WINDOW_KM=15,PER_WINDOW=3,START_KM=5;
export function attractionsFromWiki(pages:WikiPage[],measure?:(point:Coordinate)=>{km:number;offset:number}):Attraction[]{
  const seen=new Set<number>(),candidates:(Attraction&{km?:number})[]=[];
  for(const page of pages){
    const at=page.coordinates?.[0],description=page.description??"";
    if(!at||seen.has(page.pageid)||!validCoordinate(at)||NOT_A_SIGHT.test(page.title)||PLACE.test(description))continue;
    const near=measure?.(at);
    if(near&&near.offset>SEARCH_KM)continue;
    const match=KINDS.find(([pattern])=>pattern.test(page.title)||pattern.test(description));
    if(!match)continue;
    seen.add(page.pageid);
    candidates.push({id:`wiki-${WIKI_LANG}-${page.pageid}`,name:page.title.slice(0,80),kind:match[1],lat:at.lat,lon:at.lon,source:"wikipedia",
      selected:false,score:match[2],wikipedia:`${WIKI_LANG}:${page.title}`,km:near?.km});
  }
  candidates.sort((a,b)=>(b.score??0)-(a.score??0));
  const windows=new Map<number,number>(),chosenIn=new Set<number>(),kept:Attraction[]=[];
  let chosen=0;
  for(const {km,...sight} of candidates){
    const window=km===undefined?0:Math.floor(km/WINDOW_KM);
    if((windows.get(window)??0)>=PER_WINDOW||kept.length>=MAX_FOUND)continue;
    windows.set(window,(windows.get(window)??0)+1);
    const pick=chosen<PRESELECT&&(sight.score??0)>=2&&!chosenIn.has(window)&&(km===undefined||km>=START_KM);
    if(pick){chosen++;chosenIn.add(window);}
    kept.push({...sight,selected:pick});
  }
  return kept;
}
/** The first sentences of the Wikipedia summary (``ro:Salina Turda``), at most 200 characters. */
export function shortDescription(extract:string){
  const sentences=extract.replace(/\s+/g," ").trim().match(/[^.!?]+[.!?]+/g)??[extract.trim()];
  let text="";
  for(const sentence of sentences){if((text+sentence).trim().length>200)break;text+=sentence;}
  return (text||sentences[0].slice(0,197)+"…").trim();
}
async function wikipediaSummary(tag:string,signal:AbortSignal){
  const [lang,...title]=tag.split(":");
  if(!/^[a-z-]{2,12}$/.test(lang)||!title.length)return undefined;
  const response=await fetch(`https://${lang}.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title.join(":").replaceAll(" ","_"))}`,{signal});
  if(!response.ok)return undefined;
  const data=await response.json() as {extract?:string};
  return data.extract?shortDescription(data.extract):undefined;
}

/** core's answer on /simulator/route (simulator/sim.py ``route_status``). */
export interface CoreRoute {revision:number;active:boolean;route:RouteFile|null;summary:{length_km:number;destination:string}|null;
  km:number|null;running:boolean|null;speed_kmh:number;time_scale:number;arrived:boolean}
/** Same origin as the page: Vite proxies /simulator to core (vite.config.js). */
export async function simulatorApi<T>(path:string,method="GET",body?:unknown):Promise<T>{
  const response=await fetch("/simulator"+path,{method,cache:"no-store",signal:AbortSignal.timeout(10000),
    headers:body===undefined?{}:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(typeof data?.detail==="string"?data.detail:response.status===404?"Core rulează fără simulatorul de traseu (simulator/).":"Core nu a acceptat cererea.");
  return data as T;
}

export function useRoutePlanner(trip: Trip | undefined) {
  const [points,setPoints]=useState<RoutePoint[]>([]);
  const [route,setRoute]=useState<RoadRoute|null>(null);
  const [status,setStatus]=useState<"empty"|"loading"|"ready"|"error">("empty");
  const [error,setError]=useState("");
  const [adding,setAdding]=useState(false);
  const [revision,retry]=useState(0);
  const [core,setCore]=useState<CoreRoute|null>(null),[coreError,setCoreError]=useState(""),[sending,setSending]=useState(false);
  const [sentKey,setSentKey]=useState("");
  const [attractions,setAttractions]=useState<Attraction[]>([]);
  const [search,setSearch]=useState<{status:"idle"|"loading"|"ready"|"error";error:string}>({status:"idle",error:""});
  const [placing,setPlacing]=useState(false);
  const searchRequest=useRef<AbortController|null>(null);
  const addRequest=useRef<AbortController|null>(null);
  const editVersion=useRef(0),preloaded=useRef("");
  useEffect(()=>()=>addRequest.current?.abort(),[]);

  function edit(next: RoutePoint[]) {
    editVersion.current++;
    addRequest.current?.abort();
    setAdding(false);
    setRoute(null);setError("");
    setStatus(next.length>1?"loading":"empty");
    setPoints(next);
    retry(old=>old+1);
  }
  async function add(point: Coordinate, replaceId?: string) {
    if(adding || addRequest.current)return;
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
      edit(replaceId?points.map(p=>p.id===replaceId?{...p,...snapped}:p):[...points,{...snapped,id:crypto.randomUUID(),name:`Punct ${points.length+1}`,category:"waypoint"}]);
    }catch(cause){
      if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Punctul nu a putut fi validat.");
    }finally{
      if(addRequest.current===controller){addRequest.current=null;setAdding(false);}
    }
  }
  const routeKey=pointsKey(points);
  useEffect(()=>{
    if(preloaded.current&&preloaded.current===routeKey){preloaded.current="";return;}  // the road came with core's file
    if(points.length<2){setRoute(null);setStatus("empty");return;}
    const controller=new AbortController();
    setStatus("loading");setRoute(null);
    const timer=setTimeout(async()=>{
      try{
        const coordinates=points.map(p=>`${p.lon},${p.lat}`).join(";");
        const radiuses=points.map(()=>"500").join(";");
        const response=await fetch(`https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson&radiuses=${radiuses}`,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
        if(!response.ok)throw new Error("Serviciul de rutare nu răspunde. Reîncearcă.");
        const result=await response.json() as {code:string;routes?:{geometry:{coordinates:number[][]}}[]};
        const geometry=result.routes?.[0]?.geometry.coordinates.map(([lon,lat])=>({lat,lon}));
        if(result.code!=="Ok"||!geometry||geometry.length<2)throw new Error("Nu există un traseu auto între punctele alese.");
        const road=roadRoute(geometry);
        if(!road)throw new Error("Serviciul de rutare a returnat un traseu invalid.");
        if(controller.signal.aborted)return;
        setRoute(road);setStatus("ready");setError("");
        void findAttractions(road);
      }catch(cause){
        if(!controller.signal.aborted){setStatus("error");setError(cause instanceof Error?cause.message:"Traseu indisponibil.");}
      }
    },350);
    return ()=>{controller.abort();clearTimeout(timer)};
  },[routeKey,revision]);

  // --- tourist sights ---------------------------------------------------------------------------------------------
  async function findAttractions(road:RoadRoute){
    searchRequest.current?.abort();
    const controller=new AbortController();searchRequest.current=controller;
    setSearch({status:"loading",error:""});
    try{
      const signal=AbortSignal.any([controller.signal,AbortSignal.timeout(30000)]);
      const pages:WikiPage[]=[];
      for(const circle of searchCircles(road)){  // one request at a time, as Wikipedia asks of API clients
        const response=await fetch(geosearchUrl(circle),{signal});
        if(!response.ok)throw new Error(response.status===429?"Wikipedia a limitat căutările. Reîncearcă peste un minut.":"Wikipedia nu răspunde. Reîncearcă.");
        pages.push(...Object.values(((await response.json()) as {query?:{pages?:Record<string,WikiPage>}}).query?.pages??{}));
      }
      const found=attractionsFromWiki(pages,point=>nearestOnRoute(road.geometry,road.cumulative,point));
      if(controller.signal.aborted)return;
      setAttractions(old=>[...old.filter(a=>a.source==="manual"),...found]);
      setSearch({status:"ready",error:""});
      for(const sight of found.filter(a=>a.selected&&a.wikipedia))await describe(sight.id,sight.wikipedia!,controller.signal);
    }catch(cause){
      if(!controller.signal.aborted)setSearch({status:"error",error:cause instanceof Error&&cause.name!=="TimeoutError"&&cause.name!=="TypeError"?cause.message:"Căutarea obiectivelor nu răspunde. Reîncearcă."});
    }
  }
  async function describe(id:string,tag:string,signal:AbortSignal){
    try{const text=await wikipediaSummary(tag,AbortSignal.any([signal,AbortSignal.timeout(10000)]));
      if(text)setAttractions(old=>old.map(a=>a.id===id&&!a.description?{...a,description:text}:a));}
    catch{/* A sight without a description is still a sight. */}
  }
  function toggleAttraction(id:string){
    const sight=attractions.find(a=>a.id===id);
    setAttractions(old=>old.map(a=>a.id===id?{...a,selected:!a.selected}:a));
    if(sight&&!sight.selected&&!sight.description&&sight.wikipedia)void describe(id,sight.wikipedia,new AbortController().signal);
  }
  function placeAttraction(point:Coordinate){
    setPlacing(false);
    if(!validCoordinate(point))return;
    const count=attractions.filter(a=>a.source==="manual").length+1;
    setAttractions(old=>[...old,{id:"manual-"+crypto.randomUUID().slice(0,8),name:`Obiectiv ${count}`,kind:"attraction",lat:point.lat,lon:point.lon,source:"manual",selected:true}]);
  }
  const editAttraction=(id:string,change:Partial<Pick<Attraction,"name"|"description">>)=>setAttractions(old=>old.map(a=>a.id===id?{...a,...change}:a));
  const removeAttraction=(id:string)=>setAttractions(old=>old.filter(a=>a.id!==id));
  useEffect(()=>()=>searchRequest.current?.abort(),[]);
  // A sight is shown with its place on the road; one too far from it (> 5 km, simulator.yaml) is refused by core.
  const sights=useMemo(()=>attractions.map(a=>{const near=route?nearestOnRoute(route.geometry,route.cumulative,a):null;
    return {...a,km:near?.km??null,detour:near?.offset??null};}).sort((a,b)=>(a.km??0)-(b.km??0)),[attractions,route]);

  // --- core: what it follows, sending, seeking -------------------------------------------------------------------
  const adopt=useCallback((answer:CoreRoute,load:boolean)=>{
    setCore(answer);setCoreError("");
    if(!answer.route){setSentKey("");return;}
    setSentKey(fileKey(answer.route));
    if(!load)return;
    const loaded=pointsOf(answer.route);
    const road=roadRoute(answer.route.geometry);
    preloaded.current=pointsKey(loaded);
    editVersion.current++;
    setPoints(loaded);setRoute(road);setStatus(road?"ready":"error");setError("");
    setAttractions(attractionsOf(answer.route));setSearch({status:"ready",error:""});
  },[]);
  const refresh=useCallback(async(load=false)=>{
    try{adopt(await simulatorApi<CoreRoute>("/route"),load);}
    catch(cause){setCoreError(cause instanceof Error&&cause.name!=="TimeoutError"?cause.message:"Core nu răspunde. Pornește core pentru a trimite traseul.");}
  },[adopt]);
  useEffect(()=>{void refresh(true);},[refresh]);  // a reload shows the route core is following
  const draft=useMemo(()=>routeFile(points,route,{id:crypto.randomUUID(),ts:Date.now()/1000,attractions}),[points,route,attractions]);
  async function send(speed?:number){
    if(!draft||sending)return;
    setSending(true);setCoreError("");
    try{adopt(await simulatorApi<CoreRoute>("/route","PUT",{...draft,created_ts:Date.now()/1000,...(speed===undefined?{}:{speed_kmh:speed})}),false);}
    catch(cause){setCoreError(cause instanceof Error?cause.message:"Traseul nu a putut fi trimis.");}
    finally{setSending(false);}
  }
  async function clear(){
    try{adopt(await simulatorApi<CoreRoute>("/route","DELETE"),false);}catch(cause){setCoreError(cause instanceof Error?cause.message:"Cererea a eșuat.");}
  }
  async function seek(fraction:number){
    try{setCore(await simulatorApi<CoreRoute>("/seek","POST",{fraction}));setCoreError("");}catch(cause){setCoreError(cause instanceof Error?cause.message:"Cererea a eșuat.");}
  }
  // In step with core when core follows exactly this file (compared as the file normalises the points).
  const synced=Boolean(core?.active&&draft&&sentKey===fileKey(draft));
  const coreRoute=useMemo(()=>core?.route?roadRoute(core.route.geometry):null,[core?.route]);
  // The car: core's position on core's road (its heading from the road); before a route, the first point.
  const travelled=coreRoute&&trip?.pos?projectOnRoute(coreRoute.geometry,coreRoute.cumulative,trip.pos):null;
  const position=useMemo(()=>{
    if(coreRoute&&travelled!==null&&trip?.pos){const at=locateOnRoute(coreRoute.geometry,coreRoute.cumulative,travelled);return {lat:trip.pos.lat,lon:trip.pos.lon,heading:at?.heading??0};}
    return points[0]?{lat:points[0].lat,lon:points[0].lon,heading:0}:null;
  },[coreRoute,travelled,trip?.pos,points]);
  return {points,route,status,error,adding,position,add,edit,draft,core,coreError,sending,synced,coreRoute,travelled,send,clear,seek,refresh,
    sights,search,placing,setPlacing,toggleAttraction,placeAttraction,editAttraction,removeAttraction,
    findAttractions:()=>{if(route)void findAttractions(route);},
    rename:(id:string,name:string)=>setPoints(old=>old.map(p=>p.id===id?{...p,name}:p)),
    setCategory:(id:string,category:string)=>setPoints(old=>old.map(p=>p.id===id?{...p,category}:p)),
    retry:()=>retry(old=>old+1)};
}
export type RoutePlanner = ReturnType<typeof useRoutePlanner>;
