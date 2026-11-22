import {createContext,useContext} from "react";
import type {useDriverSession} from "./session";
import type {useDriverAudio} from "./audio";

/** The Live session with core (state, events, commands) plus the browser's voice and sound. */
export interface DriverContextValue extends ReturnType<typeof useDriverSession> {
  audio:ReturnType<typeof useDriverAudio>;
}
export const DriverContext=createContext<DriverContextValue|null>(null);
export function useDriver(){const value=useContext(DriverContext);if(!value)throw new Error("DriveMate session missing");return value;}
