import type {Assessment, DashboardEvent, DashboardState, Trip} from "../types";

export const genres = ["pop","rock","electronic","jazz","classical","lofi","acoustic","dance","hiphop","kids"] as const;
export type Genre = typeof genres[number];
export interface Track {id:string; title:string; genre:Genre}
export interface Profile {
  id:string; name:string; revision:number; music_genres:Genre[];
  preferences:{talkativeness:"low"|"normal"|"high";volume:number};
  safe_contact:{name:string}; emergency_contact:{name:string};
  consent:{safe_contact_notify:boolean}; announce:boolean; youtube_tracks:Track[];
}
export interface Point {lat:number;lon:number}
export interface Poi extends Point {id:string; name:string; category?:string|null; km?:number;dist_km?:number}
export interface Road {geometry:Point[];stops:Poi[];total:number}
export type Phase = "ready"|"moving"|"parked"|"finished"|"unknown";
export interface Notice {type:"fatigue"|"sos"; at:number;text:string;channels?:Record<string,string>}
export interface Report {
  id:string;at:number;distance_km:number;elapsed_min:number;stops:number;
  scorecard?:DashboardState["scorecard"];blind_m?:DashboardState["blind_m"];ab?:DashboardState["ab"];
  history:(Assessment|null|undefined)[];effects:{reason:string;action:string;effect_pct?:number}[];
  route?:Road;blind_segments?:{from:Point;to:Point}[];reaction?:NonNullable<DashboardState["driver"]>["reaction"];
  reaction_mean_ms?:Partial<Record<"visual"|"verbal"|"gesture",number>>;
  log:DashboardEvent[];
}
export interface Reports {latest:Report|null;previous:Report|null}
export interface DriverUI {
  commands?:string[];pending?:{id:string;kind:string;question:string}|null;
  route?:Road;rate?:number;speed?:number;child?:boolean;notice?:Notice|null;sos_at?:number|null;
  report_id?:string|null;reports?:Reports;contact_url?:string;calibrated?:boolean;
}
export interface ContactState {name:string;source:"demo"|"live";phase:Phase;eta_min?:number|null;pos?:Point|null;notice?:Notice|null;updated_at:number}
export function tripPhase(trip:Trip|undefined):Phase {
  if (!trip) return "unknown";
  if (trip.phase && ["ready","moving","parked","finished"].includes(trip.phase)) {
    if ((trip.speed_kmh??0)>0 && trip.phase!=="moving") return "moving";
    return trip.phase;
  }
  if (trip.stopped===true && trip.speed_kmh===0) return "parked";
  if (typeof trip.speed_kmh==="number" && trip.speed_kmh>0) return "moving";
  return "unknown";
}
export const categoryNames: Record<string,string>={fuel:"Benzinărie",cafe:"Cafenea",pharmacy:"Farmacie",supermarket:"Supermarket",auto_parts:"Piese auto"};
export async function api<T>(path:string,method="GET",payload?:unknown):Promise<T>{
  const response=await fetch(path,{method,headers:payload===undefined?{}:{"Content-Type":"application/json"},
    body:payload===undefined?undefined:JSON.stringify(payload),cache:"no-store",signal:AbortSignal.timeout(8000)});
  if(!response.ok){const detail=await response.json().catch(()=>null);throw new Error(detail?.error??"Serviciul nu este disponibil.");}
  return response.json();
}
export const errorText=(e:unknown)=>e instanceof Error?e.message:"Cererea nu a putut fi finalizată.";
export function newId(){return typeof crypto.randomUUID==="function"?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint32Array(4)),n=>n.toString(16)).join("-");}
export type Command=(name:string,args?:Record<string,unknown>)=>Promise<boolean>;

