import type { ReactNode } from "react";
import type {DriverUI, Phase, Point, Poi} from "./driver/contracts";

export type Reading = number | null;
export interface Assessment { ts?:number; attention?: Reading; fatigue?: Reading; disengagement?: Reading; risk?: Reading }
export interface Trip {
  speed_kmh?: Reading; elapsed_min?: Reading; eta_min?: Reading; road?: string;
  id?: string|null; phase?: Phase; distance_km?: Reading; scene?:number;pos?:Point;at_poi?:Poi|null;
  stopped?: boolean; next_poi?: {id?:string;name?:string;category?:string|null;dist_km?:Reading}|null;
}
export interface Driver {
  eyes?: {ear?: Reading; eye_used?: string; perclos_60s?: Reading; blink_ms?: Reading; microsleep?: boolean; reliable?: boolean; closed_ms?: Reading; open_baseline?: Reading; blink_rate?: Reading; squint?: boolean; state?: string; long_closure?: boolean};
  gaze?: {zone?: string; off_road_ms?: Reading; source?: string; conf?: Reading; vats_60s?: Reading; entropy_60s?: Reading};
  head?: {yaw?: Reading; pitch?: Reading; roll?: Reading; nodding?: boolean; answer?: string | null};
  reaction?: Partial<Record<`${"visual" | "verbal" | "gesture"}_ms`, Reading>> & {baseline_ms?: Partial<Record<"visual" | "verbal" | "gesture", Reading>>; missed?: Reading; response_rate_10min?: Reading};
  phone?: {in_use?: boolean; source?: string | null; conf?: Reading}; yawn?: boolean; speaking?: boolean; gesture?: string | null;
}
export interface PerformanceState {
  [key: `${string}_ms_p50`]: Reading | undefined;
  [key: `${string}_ms_p95`]: Reading | undefined;
  cameras?: Record<string, {capture_fps?: Reading; process_fps?: Reading; dropped_frames?: Reading}>;
  stages_ms?: Record<string, Record<string, {p50?: Reading; p95?: Reading}>>;
  cpu?: Reading; ram_mb?: Reading; gpu?: Reading; alarm_ms_last?: Reading;
  llm_ttft_ms?: Reading; llm_total_ms?: Reading; stt_final_ms?: Reading; tts_first_audio_ms?: Reading; msg_to_voice_ms?: Reading;
}
export interface DashboardState {
  ts?: number; seq?: number; trip?: Trip; driver?: Driver; assessment?: Assessment; perf?: PerformanceState;
  safety?: {monitoring_ok?: boolean; alert?: string | {text?: string} | null; level?: string; alarm_ms_last?: Reading; llm_enabled?: boolean; llm_allowed?: boolean};
  cause?: {label?: string | null; target?: string | null; glances_30s?: Reading; sources?: string[]; conf?: Reading};
  occupants?: {id?: string | number; profile?: string; seat?: string; source?: string; role?: string}[];
  messages?: {id?: string; from?: string; app?: string; state?: string; deferred_reason?: string | null;text?:string;replyable?:boolean;reply?:string;ts?:number}[];
  reminders?: {id?: string; task?: string; state?: string; trigger?: {category?: string}}[];
  passenger?: {present?: boolean; awake?: boolean; speaking?: boolean; holding_phone?: boolean; gesture?: string | null};
  conversation?: boolean; phone?: {connected?: boolean; battery?: Reading};
  safe_contact?: {name?: string; consent?: boolean; notified_ts?: number | null};
  media?: {playing?: boolean; title?: string | null; track_id?:string|null;artist?:string;volume?: Reading};
  driver_ui?: DriverUI;
  scorecard?: {longest_focus_min?: Reading; hands_free_messages?: Reading; phone_touches?: Reading; suggestions_accepted?: Reading; suggestions_rejected?: Reading; reminders_done?: Reading};
  ab?: {naive_alerts?: Reading; our_alerts?: Reading}; blind_m?: {last?: Reading; trip?: Reading};
  intervention?: {last?: string | null; effect_pct?: Reading};
  interaction?: {state?: string; addressed_to?: string | null; dialog_window_open?: boolean; last_input?: {channel?: string; value?: string; ts?: number} | null};
  assistant?: {muted_until?: number | null; mute_reason?: string | null};
}
export interface DashboardEvent {type: string; ts: number; source?: string; text?: string; explanation?: string; channel?: string; latency_ms?: number}
export interface SessionSocket extends EventTarget {readonly readyState:number;send(data:string):void}
export interface SessionData {state: DashboardState; history: (Assessment | null | undefined)[]; log: DashboardEvent[]; socket: SessionSocket | null; cue: number; speech: string; connection: string}
export type StateProps = {s: DashboardState};
export type RowsData = [string, ReactNode][];
