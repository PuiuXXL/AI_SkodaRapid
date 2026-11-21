import {useEffect,useState} from "react";
import {useDriver} from "./context";
import {api,errorText} from "./contracts";
import type {Reports} from "./contracts";
import {PageHeading} from "./DrivingPages";
import {Metrics,fmt,Scorecard} from "../Panels";
import {ScoreHistory} from "../ScoreHistory";
import {EventJournal} from "./EventJournal";
import {RouteDiagram} from "./RouteDiagram";

export function ReportPage(){
  const {data,live}=useDriver();
  const [reports,setReports]=useState<Reports>({latest:null,previous:null}),[error,setError]=useState("");
  useEffect(()=>{
    let cancelled=false;
    if(live){setReports(data.state.driver_ui?.reports??{latest:null,previous:null});return;}
    api<Reports>("/api/driver/reports").then(value=>{if(!cancelled){setReports(value);setError("");}}).catch(e=>{if(!cancelled)setError(errorText(e));});
    return ()=>{cancelled=true};
  },[live,data.state.driver_ui?.report_id]);
  const report=reports.latest;
  return <><PageHeading label="FIȘA CĂLĂTORIEI" title="Drumul, privit înapoi" description="Un rezumat al măsurătorilor și al intervențiilor din călătoria încheiată."/>
    {error&&<p role="alert">{error}</p>}{!report?<section className="empty-state"><h2>Nicio călătorie încheiată</h2><p>Fișa apare după oprire și confirmarea încheierii călătoriei.{live?" Core-ul Live trebuie să furnizeze fișa finală.":" Fișele demonstrative se păstrează cât timp rulează serverul local."}</p></section>:<>
      <section className="report-lead"><small>{new Date(report.at*1000).toLocaleString("ro-RO")}</small><h2>{typeof report.distance_km==="number"?fmt(report.distance_km," km")+" parcurși":"Călătorie încheiată"}</h2><Metrics items={[["Cel mai lung interval concentrat",fmt(report.scorecard?.longest_focus_min," min")],["Mesaje fără mâini",fmt(report.scorecard?.hands_free_messages)],["Mementouri rezolvate",fmt(report.scorecard?.reminders_done)],["Distanță",fmt(report.distance_km," km")],["Durată",fmt(report.elapsed_min," min")],["Opriri",fmt(report.stops)]]}/></section>
      <div className="report-review"><section><h2>Traseu și metri orbi</h2><RouteDiagram route={report.route} blind={report.blind_segments}/><p>Metri orbi: {fmt(report.blind_m?.trip," m")}. Segmentele marcate provin din măsurătorile acestei sesiuni.</p></section><EventJournal events={report.log??[]}/></div><section><h2>De ce a intervenit copilotul?</h2>{report.effects.length?<ul className="driver-list">{report.effects.map((effect,i)=><li key={i}><strong>{effect.action}</strong><p>{effect.reason}</p><p>{typeof effect.effect_pct==="number"?"Efect măsurat: "+fmt(effect.effect_pct,"% "):"Efect în curs de măsurare / indisponibil"}</p></li>)}</ul>:<p className="empty-state">Nu au fost înregistrate intervenții explicate în această călătorie.</p>}</section>
      <div className="content"><ScoreHistory points={report.history}/><Scorecard s={{scorecard:report.scorecard,blind_m:report.blind_m,ab:report.ab}}/></div>
      {reports.previous&&<section><h2>Călătoria anterioară</h2><p>Comparație descriptivă între două sesiuni; traseele și condițiile pot fi diferite.</p><table><thead><tr><th>Măsurare</th><th>Acum</th><th>Anterior</th></tr></thead><tbody><tr><th>Distanță</th><td>{fmt(report.distance_km," km")}</td><td>{fmt(reports.previous.distance_km," km")}</td></tr><tr><th>Interval concentrat</th><td>{fmt(report.scorecard?.longest_focus_min," min")}</td><td>{fmt(reports.previous.scorecard?.longest_focus_min," min")}</td></tr></tbody></table></section>}
    </>}
  </>;
}
