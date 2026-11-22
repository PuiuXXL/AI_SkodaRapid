// Romanian labels for the contract's vocabularies (shared/contracts.py). An unknown code is shown as received
// (underscores as spaces), never hidden: a new backend value stays visible on the dashboard.
export const zones: Record<string,string>={road:"Road",passenger:"Passenger",lap:"Lap",mirror_left:"Left mirror",mirror_right:"Right mirror",mirror_rear:"Rear-view mirror",cluster:"Instruments",infotainment:"Screen",away:"Looking away",rear_seat:"Rear seat"};
/** Zones that count as looking at the road scene (road and mirrors); the rest is off-road. */
export const drivingZones=new Set(["road","mirror_left","mirror_right","mirror_rear"]);
export const monitoringReasons: Record<string,string>={
  camera_unavailable:"Camera unavailable",camera_frozen:"Frozen image",camera_covered:"Lens covered",face_lost:"Face not visible",
  no_frames:"No frames",frozen:"Frozen image",mode_switch:"Day / night switch",occluded:"Lens covered",too_dark:"Too dark",
  blurred:"Blurred image",camera_fallback:"Backup camera",face_too_small:"Face too small",
};
export const safetyLevels: Record<string,string>={P0:"Emergency",P1:"Alarm",P2:"Warning",P3:"Suggestion",P4:"Normal"};
/** ``safety.alert`` codes of core's safety rules (core/safety). */
export const alerts: Record<string,string>={microsleep:"Microsleep",phone:"Phone in hand",off_road:"Eyes off the road",distraction:"Distraction",
  fatigue:"Fatigue",fatigue_high:"High fatigue",nodding:"Head nodding",monitoring_lost:"Monitoring lost",are_you_ok:"Are you OK?",
  unresponsive:"Driver unresponsive",sos_countdown:"SOS countdown",sos_sent:"SOS sent"};
export const sosStates: Record<string,string>={normal:"Normal",alarm:"Active alarm",asking:"Asking driver",countdown:"SOS countdown",sos_sent:"SOS sent"};
export const causes: Record<string,string>={passenger_showing_phone:"Passenger showing phone",passenger_talk:"Passenger conversation",incoming_message:"Incoming message",phone:"Phone",child_activity:"Child in rear seat"};
export const phoneUsage: Record<string,string>={call:"At ear",hand:"In hand",visible:"Visible",lap:"In lap"};
export const postures: Record<string,string>={leaning_forward:"Leaning forward",leaning_side:"Leaning sideways",slumped:"Slumped",out_of_position:"Out of position"};
export const integrationNames: Record<string,string>={phone_bridge:"Phone bridge",twilio:"SOS call",contact_app:"Contact app",llm:"LLM"};
export const integrationStates: Record<string,string>={ok:"active",down:"down",off:"off",unknown:"unknown"};
export const seats: Record<string,string>={driver:"Driver",front_right:"Front passenger",rear:"Rear"};
export const roads: Record<string,string>={city:"City",highway:"Highway",rural:"National road",national:"National road"};
export const label=(table: Record<string,string>,code: unknown)=>typeof code==="string"&&code?table[code]??code.replaceAll("_"," "):"—";
