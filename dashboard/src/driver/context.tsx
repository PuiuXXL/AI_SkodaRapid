import {createContext,useContext} from "react";
import type {Dispatch,SetStateAction} from "react";
import type {Profile} from "./contracts";
import type {useDriverSession} from "./session";
import type {useDriverAudio} from "./audio";

export interface DriverContextValue extends ReturnType<typeof useDriverSession> {
  live:boolean;setLive:(live:boolean)=>void;profile:Profile|null;profileError:string;
  draft:Profile|null;setDraft:Dispatch<SetStateAction<Profile|null>>;
  saveProfile:()=>Promise<boolean>;reloadProfile:()=>Promise<void>;saving:boolean;
  audio:ReturnType<typeof useDriverAudio>;locked:boolean;
}
export const DriverContext=createContext<DriverContextValue|null>(null);
export function useDriver(){const value=useContext(DriverContext);if(!value)throw new Error("Sesiune DriveMate lipsă");return value;}
