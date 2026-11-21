// Romanian labels for the contract's vocabularies (shared/contracts.py). An unknown code is shown as received
// (underscores as spaces), never hidden: a new backend value stays visible on the dashboard.
export const zones: Record<string,string>={road:"Drum",passenger:"Pasager",lap:"Poală",mirror_left:"Oglinda stângă",mirror_right:"Oglinda dreaptă",mirror_rear:"Oglinda centrală",cluster:"Bord",infotainment:"Ecran",away:"În altă direcție",rear_seat:"Bancheta din spate"};
/** Zones that count as looking at the road scene (road and mirrors); the rest is off-road. */
export const drivingZones=new Set(["road","mirror_left","mirror_right","mirror_rear"]);
export const monitoringReasons: Record<string,string>={
  camera_unavailable:"Cameră indisponibilă",camera_frozen:"Imagine înghețată",camera_covered:"Obiectiv acoperit",face_lost:"Fața nu se vede",
  no_frames:"Fără cadre",frozen:"Imagine înghețată",mode_switch:"Comutare zi / noapte",occluded:"Obiectiv acoperit",too_dark:"Prea întuneric",
  blurred:"Imagine neclară",camera_fallback:"Cameră de rezervă",face_too_small:"Față prea mică",
};
export const safetyLevels: Record<string,string>={P0:"Urgență",P1:"Alarmă",P2:"Avertizare",P3:"Sugestie",P4:"Normal"};
/** ``safety.alert`` codes of core's safety rules (core/safety). */
export const alerts: Record<string,string>={microsleep:"Microsomn",phone:"Telefon în mână",off_road:"Privire în afara drumului",distraction:"Distragere",
  fatigue:"Oboseală",fatigue_high:"Oboseală ridicată",nodding:"Cădere de cap",monitoring_lost:"Nu te mai văd",are_you_ok:"Ești bine?",
  unresponsive:"Șoferul nu răspunde",sos_countdown:"Numărătoare SOS",sos_sent:"SOS trimis"};
export const sosStates: Record<string,string>={normal:"Normal",alarm:"Alarmă activă",asking:"Întreabă șoferul",countdown:"Numărătoare SOS",sos_sent:"SOS trimis"};
export const causes: Record<string,string>={passenger_showing_phone:"Pasagerul arată telefonul",passenger_talk:"Conversație cu pasagerul",incoming_message:"Mesaj primit",phone:"Telefon",child_activity:"Copil în spate"};
export const phoneUsage: Record<string,string>={call:"La ureche",hand:"În mână",visible:"Vizibil",lap:"În poală"};
export const postures: Record<string,string>={leaning_forward:"Aplecat în față",leaning_side:"Aplecat lateral",slumped:"Lăsat pe scaun",out_of_position:"În afara poziției"};
export const integrationNames: Record<string,string>={phone_bridge:"Punte telefon",twilio:"Apel SOS",contact_app:"Aplicație contact",llm:"LLM"};
export const integrationStates: Record<string,string>={ok:"activ",down:"căzut",off:"oprit",unknown:"necunoscut"};
export const seats: Record<string,string>={driver:"Șofer",front_right:"Pasager față",rear:"Spate"};
export const roads: Record<string,string>={city:"Oraș",highway:"Autostradă",rural:"Drum național",national:"Drum național"};
export const label=(table: Record<string,string>,code: unknown)=>typeof code==="string"&&code?table[code]??code.replaceAll("_"," "):"—";
