import type {Trip} from "../types";

export interface Point {lat:number;lon:number}
export interface Poi extends Point {id:string; name:string; category?:string|null; dist_km?:number}
export type Phase = "ready"|"moving"|"parked"|"unknown";
export const phaseLabels:Record<Phase,string>={ready:"Ready to leave",moving:"On the move",parked:"At a stop",unknown:"No data from core"};
/** Where the trip stands, from core's ``State.trip`` (shared/contracts.py: speed_kmh, stopped). */
export function tripPhase(trip:Trip|undefined):Phase {
  if (!trip || typeof trip.speed_kmh!=="number") return "unknown";
  if (trip.speed_kmh>0) return "moving";
  return trip.stopped===true?"parked":"ready";
}
export const categoryNames: Record<string,string>={fuel:"Fuel station",cafe:"Café",pharmacy:"Pharmacy",supermarket:"Supermarket",auto_parts:"Auto parts"};
/** The driver's enrolled profile name (P1 face recognition, ``State.occupants``), for greeting; undefined if unknown. */
export function driverName(occupants:{seat?:string;profile?:string|null}[]|undefined){
  const profile=occupants?.find(o=>o.seat==="driver")?.profile?.trim();
  return profile?profile.charAt(0).toUpperCase()+profile.slice(1):undefined;
}
