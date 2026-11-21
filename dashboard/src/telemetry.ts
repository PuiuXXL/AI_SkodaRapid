// A short client-side buffer of the signals core publishes at 10 Hz, sampled at 2 Hz (about one minute of history),
// so the dashboard can chart P1 / P2 readings that the State carries only as "now" values (gaze zone, PERCLOS, head
// pose, resources, latency). Only received values are stored: a stale or missing state adds nothing.
import {useEffect,useRef,useState} from "react";
import type {DashboardState,Reading} from "./types";

export interface Sample {
  ts: number; zone?: string; perclos?: Reading; ear?: Reading; closed?: Reading; offRoad?: Reading; blinkRate?: Reading;
  yaw?: Reading; pitch?: Reading; speed?: Reading; risk?: Reading;
  e2e?: Reading; cpu?: Reading; gpu?: Reading; ram?: Reading; fpsDriver?: Reading; fpsPassenger?: Reading;
}
const PERIOD_S=.5;

export function sampleOf(s: DashboardState): Sample | null {
  if(typeof s.ts!=="number"||!Number.isFinite(s.ts))return null;
  const d=s.driver,p=s.perf;
  const tracked=d?.monitoring_ok!==false&&d?.eyes?.reliable!==false;
  return {
    ts:s.ts,zone:d?.monitoring_ok===false?undefined:d?.gaze?.zone,
    perclos:tracked?d?.eyes?.perclos_60s:null,ear:tracked?d?.eyes?.ear:null,closed:tracked?d?.eyes?.closed_ms:null,
    offRoad:d?.gaze?.off_road_ms,blinkRate:d?.eyes?.blink_rate,yaw:d?.head?.yaw,pitch:d?.head?.pitch,
    speed:s.trip?.speed_kmh,risk:s.assessment?.risk,
    e2e:p?.e2e_ms_p95,cpu:p?.cpu,gpu:p?.gpu,ram:p?.ram_mb,fpsDriver:p?.cameras?.driver?.process_fps,fpsPassenger:p?.cameras?.passenger?.process_fps,
  };
}

/** The last `size` samples of the state stream, at most one every 0.5 s; cleared when the clock goes back (new trip). */
export function useTelemetry(s: DashboardState,size=120): Sample[] {
  const [samples,setSamples]=useState<Sample[]>([]);
  const last=useRef<number | null>(null);
  useEffect(()=>{
    const sample=sampleOf(s);
    if(!sample)return;
    if(last.current!==null&&sample.ts<last.current-5){last.current=sample.ts;setSamples([sample]);return;}
    if(last.current!==null&&sample.ts-last.current<PERIOD_S)return;
    last.current=sample.ts;
    setSamples(old=>[...old.slice(-(size-1)),sample]);
  },[s,size]);
  return samples;
}

/** Share of samples per gaze zone, most frequent first (only samples that carry a zone count). */
export function zoneShares(samples: Sample[]): {zone: string; share: number; seconds: number}[] {
  const counts=new Map<string,number>();
  for(const sample of samples)if(sample.zone)counts.set(sample.zone,(counts.get(sample.zone)??0)+1);
  const total=[...counts.values()].reduce((a,b)=>a+b,0);
  return [...counts].map(([zone,count])=>({zone,share:count/total,seconds:count*PERIOD_S})).sort((a,b)=>b.share-a.share);
}
