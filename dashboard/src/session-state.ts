import type {DashboardState, DashboardEvent, SessionData} from "./types";

export function withState(old: SessionData, state: DashboardState): SessionData {
  const gap = typeof old.state.seq === "number" && typeof state.seq === "number" && state.seq !== old.state.seq + 1;
  return {...old, state, history: [...old.history, ...(gap ? [null] : []), state.assessment].slice(-120)};
}

export function appendEvent(old: SessionData, event: DashboardEvent): SessionData {
  return {...old, log: [event, ...old.log].slice(0, 60), cue: old.cue + (event.type === "visual_cue" ? 1 : 0)};
}
