import type { ReactNode } from "react";
import type {Point, Poi} from "./driver/contracts";

export type Reading = number | null;
export interface Assessment { ts?:number; attention?: Reading; fatigue?: Reading; disengagement?: Reading; risk?: Reading }
export interface Trip {
  speed_kmh?: Reading; elapsed_min?: Reading; eta_min?: Reading; road?: string;
  scene?:number|null;pos?:Point;at_poi?:Poi|null;
  stopped?: boolean; next_poi?: {id?:string;name?:string;category?:string|null;dist_km?:Reading}|null;
  /** P4 map route (simulator/sim.py): where the car is, in names from the route file. */
  place?: {after?: string; after_km?: Reading; before?: string; before_km?: Reading; destination?: string; destination_km?: Reading} | null;
  /** P4 map route: tourist sights ahead (core/attractions.py proposes them as breaks). */
  attractions_ahead?: {id: string; name: string; kind?: string; dist_km?: Reading; detour_km?: Reading; description?: string}[];
}
/** P1 posture flags (proposed contract field, docs/perception.md §9). */
export interface Posture { leaning_forward?: boolean; leaning_side?: boolean; slumped?: boolean; out_of_position?: boolean }
export type SosState = "normal" | "alarm" | "asking" | "countdown" | "sos_sent";
export interface Driver {
  monitoring_ok?: boolean; monitoring_reason?: string | null; monitoring_warnings?: string[];
  camera_mode?: string | null; face_conf?: Reading; face_too_small?: boolean; gesture_score?: Reading;
  posture?: Posture;
  eyes?: {ear?: Reading; eye_used?: string; perclos_60s?: Reading; blink_ms?: Reading; microsleep?: boolean; reliable?: boolean; closed_ms?: Reading; open_baseline?: Reading; blink_rate?: Reading; squint?: boolean; state?: string; long_closure?: boolean; blink_count?: Reading};
  gaze?: {zone?: string; off_road_ms?: Reading; source?: string | null; conf?: Reading; vats_60s?: Reading; entropy_60s?: Reading; calibrated?: boolean; off_road_60s_ms?: Reading; lap_pattern?: boolean};
  head?: {yaw?: Reading; pitch?: Reading; roll?: Reading; nodding?: boolean; answer?: string | null};
  reaction?: Partial<Record<`${"visual" | "verbal" | "gesture"}_ms`, Reading>> & {baseline_ms?: Partial<Record<"visual" | "verbal" | "gesture", Reading>>; missed?: Reading; response_rate_10min?: Reading};
  phone?: {in_use?: boolean; source?: string | null; conf?: Reading; near_face?: boolean; side?: string | null; usage?: string | null; foreign_seen?: boolean}; yawn?: boolean; speaking?: boolean; gesture?: string | null;
}
export interface PerformanceState {
  [key: `${string}_ms_p50`]: Reading | undefined;
  [key: `${string}_ms_p95`]: Reading | undefined;
  cameras?: Record<string, {capture_fps?: Reading; process_fps?: Reading; dropped_frames?: Reading; available?: boolean; age_ms?: Reading; dropped_results?: Reading; capture_ts?: Reading}>;
  degrade_level?: Reading; publish_ts?: Reading;
  stages_ms?: Record<string, Record<string, {p50?: Reading; p95?: Reading}>>;
  cpu?: Reading; ram_mb?: Reading; gpu?: Reading; alarm_ms_last?: Reading;
  llm_ttft_ms?: Reading; llm_total_ms?: Reading; stt_final_ms?: Reading; tts_first_audio_ms?: Reading; msg_to_voice_ms?: Reading;
}
export interface DashboardState {
  ts?: number; seq?: number; trip?: Trip; driver?: Driver; assessment?: Assessment; perf?: PerformanceState;
  safety?: {monitoring_ok?: boolean; alert?: string | {text?: string} | null; level?: string | null; alarm_ms_last?: Reading; llm_enabled?: boolean; llm_allowed?: boolean;
    sos?: {state?: SosState; since_ts?: Reading; countdown_s?: Reading}};
  cause?: {label?: string | null; target?: string | null; person_id?: Reading; glances_30s?: Reading; sources?: string[]; conf?: Reading};
  occupants?: {id?: string | number; profile?: string | null; seat?: string; source?: string; role?: string; profile_score?: Reading}[];
  messages?: {id?: string; from?: string; app?: string; state?: string; deferred_reason?: string | null;text?:string;replyable?:boolean;reply?:string;ts?:number}[];
  reminders?: {id?: string; task?: string; state?: string; trigger?: {type?: string; category?: string | null}; created_ts?: Reading}[];
  passenger?: {present?: boolean; awake?: boolean; eyes_closed_s?: Reading; speaking?: boolean; holding_phone?: boolean; gesture?: string | null; answer?: string | null;
    monitoring_ok?: boolean; monitoring_reason?: string | null; monitoring_warnings?: string[]; camera_mode?: string | null; face_conf?: Reading; posture?: Posture};
  conversation?: boolean; phone?: {connected?: boolean; battery?: Reading};
  safe_contact?: {name?: string | null; configured?: boolean; consent?: boolean; announce?: boolean; notified_ts?: number | null; last_reply_msg_id?: string | null};
  call?: Record<string, unknown> | null;
  integrations?: {phone_bridge?: string; twilio?: string; contact_app?: string; llm?: string};
  media?: {playing?: boolean; title?: string | null; track_id?:string|null;artist?:string;volume?: Reading; reason?: string | null; kid_safe?: boolean; source?: string | null};
  scorecard?: {longest_focus_min?: Reading; hands_free_messages?: Reading; phone_touches?: Reading; suggestions_accepted?: Reading; suggestions_rejected?: Reading; reminders_done?: Reading};
  ab?: {naive_alerts?: Reading; our_alerts?: Reading}; blind_m?: {last?: Reading; trip?: Reading};
  intervention?: {last?: string | null; effect_pct?: Reading; stats?: Record<string, number>};
  interaction?: {state?: string | null; addressed_to?: string | number | null; dialog_window_open?: boolean; last_input?: {from?: number | null; channel?: string | null; value?: string | null; ts?: number | null} | null};
  assistant?: {muted_until?: number | null; mute_reason?: string | null;
    // P3's interaction preferences, copied by core every tick (assistant/preferences.py).
    preferences?: {talkativeness?: "low" | "normal" | "high"; follow_up?: "always" | "never"; answer_length?: "short" | "normal"}};
}
export interface DashboardEvent {type: string; ts: number; source?: string | null; text?: string | null; explanation?: string | null; channel?: string | null; latency_ms?: number | null; data?: Record<string, unknown>}
export interface SessionSocket extends EventTarget {readonly readyState:number;send(data:string):void}
export interface SessionData {state: DashboardState; history: (Assessment | null | undefined)[]; log: DashboardEvent[]; socket: SessionSocket | null; cue: number; speech: string; connection: string}
export type StateProps = {s: DashboardState};
export type RowsData = [string, ReactNode][];
