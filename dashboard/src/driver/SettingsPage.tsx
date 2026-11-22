// "Setări copilot" (#/setari): how the copilot talks to the driver. P3's interaction preferences
// (assistant/preferences.py, allowed values in assistant/config/assistant.yaml -> preferences).
// The current values come from core (state.assistant.preferences, copied every tick); a click sends the
// "assistant_preference" command (session.ts liveMessage). Core applies it at once, for this trip: a reset
// brings back the profile values. Nothing here touches safety: alarms and their rules never read these values.
import {useDriver} from "./context";
import {PageHeading} from "./PageHeading";

type Option = {value: string; label: string; hint: string};
type Setting = {key: "talkativeness" | "answer_length" | "follow_up"; title: string; description: string; voice: string; options: Option[]};

/** The three preferences, in the order shown. Values must match assistant.yaml -> preferences. */
export const copilotSettings: Setting[] = [
  {key: "talkativeness", title: "Sugestii de confort",
    description: "Cât de des îți propune copilotul ceva din proprie inițiativă, de exemplu muzică pe un drum monoton.",
    voice: "„Vorbește mai rar”",
    options: [
      {value: "low", label: "Rar", hint: "cel mult o dată la 2 minute"},
      {value: "normal", label: "Normal", hint: "cel mult o dată la 30 de secunde"},
      {value: "high", label: "Des", hint: "cel mult o dată la 15 secunde"},
    ]},
  {key: "answer_length", title: "Lungimea răspunsurilor",
    description: "Cât de mult vorbește copilotul când îi ceri ceva.",
    voice: "„Răspunde mai scurt”",
    options: [
      {value: "short", label: "Scurte", hint: "o propoziție, cam 12 cuvinte"},
      {value: "normal", label: "Normale", hint: "până la 30 de cuvinte"},
    ]},
  {key: "follow_up", title: "„Te mai ajut cu ceva?”",
    description: "Dacă, după un răspuns, copilotul întreabă dacă mai ai nevoie de ceva, ca să poți continua fără să-l strigi.",
    voice: "„Nu mă mai întreba dacă mai vreau ceva”",
    options: [
      {value: "always", label: "Da", hint: "întreabă după fiecare răspuns"},
      {value: "never", label: "Nu", hint: "răspunde și tace"},
    ]},
];

export function SettingsPage(){
  const driver=useDriver();
  const prefs=(driver.fresh?driver.data.state.assistant?.preferences:undefined) as Record<string,string>|undefined;
  const can=driver.can?.("set_assistant_preference")??false;
  return <>
    <PageHeading label="COPILOT PERSONAL / SETĂRI" title="Setări copilot" description="Cum vorbește copilotul cu tine. Alertele de siguranță nu depind de aceste setări."/>
    {!can&&<p className="settings-note" role="status">Setările se pot schimba când core-ul este conectat.</p>}
    <div className="settings-grid">{copilotSettings.map(setting=>{
      const current=prefs?.[setting.key];
      return <section key={setting.key} className="fx-control-group settings-card" aria-labelledby={"setting-"+setting.key}>
        <header><h3 id={"setting-"+setting.key}>{setting.title}</h3><small>Prin voce: {setting.voice}</small></header>
        <p>{setting.description}</p>
        <div className="settings-options" role="group" aria-label={setting.title}>{setting.options.map(option=>
          <button key={option.value} type="button" aria-pressed={current===option.value} disabled={!can||!current}
            onClick={()=>{if(option.value!==current)void driver.command?.("set_assistant_preference",{key:setting.key,value:option.value});}}>
            <b>{option.label}</b><small>{option.hint}</small>
          </button>)}</div>
      </section>;})}</div>
    <p className="settings-note">Schimbările țin până la resetarea călătoriei. La pornire, valorile vin din profilul șoferului.</p>
  </>;
}
