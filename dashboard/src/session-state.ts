import type {DashboardState, DashboardEvent, SessionData} from "./types";

export function withState(old: SessionData, state: DashboardState): SessionData {
  const gap = typeof old.state.seq === "number" && typeof state.seq === "number" && state.seq !== old.state.seq + 1;
  const sample=state.assessment&&Number.isFinite(state.ts)?{...state.assessment,ts:state.ts}:state.assessment;
  return {...old, state, history: [...old.history, ...(gap ? [null] : []), sample].slice(-120)};
}

export function appendEvent(old: SessionData, event: DashboardEvent): SessionData {
  return {...old, log: [event, ...old.log].slice(0, 60), cue: old.cue + (event.type === "visual_cue" ? 1 : 0)};
}
