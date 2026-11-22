// "Copilot preferences" (#/setari): how the copilot talks to the driver. P3's interaction preferences
// (assistant/preferences.py, allowed values in assistant/config/assistant.yaml -> preferences).
// The current values come from core (state.assistant.preferences, copied every tick); a click sends the
// "assistant_preference" command (session.ts liveMessage). Core applies it at once, for this trip: a reset
// brings back the profile values. Nothing here touches safety: alarms and their rules never read these values.
import {useDriver} from "./context";
import {CardArt, type ArtSubject} from "../CardArt";
import {PageHeading} from "./PageHeading";

type Option = {value: string; label: string; hint: string};
type Setting = {art: ArtSubject; key: "talkativeness" | "answer_length" | "follow_up"; title: string; description: string; voice: string; options: Option[]};

/** The three preferences, in the order shown. Values must match assistant.yaml -> preferences. */
export const copilotSettings: Setting[] = [
  {art: "microphone", key: "talkativeness", title: "Proactive suggestions",
    description: "How often your copilot offers suggestions, such as music on a monotonous drive.",
    voice: "„Speak less often”",
    options: [
      {value: "low", label: "Occasionally", hint: "at most once every 2 minutes"},
      {value: "normal", label: "Normal", hint: "at most once every 30 seconds"},
      {value: "high", label: "Frequently", hint: "at most once every 15 seconds"},
    ]},
  {art: "ribbons", key: "answer_length", title: "Response length",
    description: "How much detail your copilot gives when you ask for help.",
    voice: "„Keep it short”",
    options: [
      {value: "short", label: "Short", hint: "one sentence, about 12 words"},
      {value: "normal", label: "Standard", hint: "up to 30 words"},
    ]},
  {art: "conversation", key: "follow_up", title: "„Anything else I can help with?”",
    description: "Let your copilot ask a follow-up question so you can keep talking without saying its name again.",
    voice: "„Skip follow-up questions”",
    options: [
      {value: "always", label: "Yes", hint: "ask after every answer"},
      {value: "never", label: "No", hint: "answer without a follow-up"},
    ]},
];

export function SettingsPage(){
  const driver=useDriver();
  const prefs=(driver.fresh?driver.data.state.assistant?.preferences:undefined) as Record<string,string>|undefined;
  const can=driver.can?.("set_assistant_preference")??false;
  return <>
    <PageHeading label="PERSONAL COPILOT / SETTINGS" title="Copilot preferences" description="Choose how your copilot talks with you. Safety alerts work independently of these preferences."/>
    {!can&&<p className="settings-note" role="status">Connect to core to change these preferences.</p>}
    <div className="settings-grid">{copilotSettings.map(setting=>{
      const current=prefs?.[setting.key];
      return <section key={setting.key} className="fx-control-group settings-card" aria-labelledby={"setting-"+setting.key}>
        <header><CardArt subject={setting.art}/><h3 id={"setting-"+setting.key}>{setting.title}</h3></header>
        <p>{setting.description}</p><blockquote><small>Voice command</small>{setting.voice}</blockquote>
        <div className="settings-options" role="group" aria-label={setting.title}>{setting.options.map(option=>
          <button key={option.value} type="button" aria-pressed={current===option.value} disabled={!can||!current}
            onClick={()=>{if(option.value!==current)void driver.command?.("set_assistant_preference",{key:setting.key,value:option.value});}}>
            <b>{option.label}</b><small>{option.hint}</small>
          </button>)}</div>
      </section>;})}</div>
    <p className="settings-note">Preferences apply until the trip resets. Your driver profile supplies the initial settings.</p>
  </>;
}
