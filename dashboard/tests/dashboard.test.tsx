import {strict as assert} from "node:assert";
import {test} from "node:test";
import {renderToStaticMarkup} from "react-dom/server";
import {MotionConfig} from "motion/react";
import {General, Eyes, Reaction} from "../src/App";
import {Cabin, Scorecard, Performance, VisionDiagnostics, fmt} from "../src/Panels";
import {Assistant} from "../src/Assistant";
import {withState, appendEvent} from "../src/session-state";
import type {DashboardState, SessionData} from "../src/types";
import {validCoordinate,distanceKm,locateOnRoute} from "../src/route-simulation";
import {MonitorPage} from "../src/driver/MonitorPage";
import {DriverContext} from "../src/driver/context";
import type {DriverContextValue} from "../src/driver/context";
import {EventJournal} from "../src/driver/EventJournal";
import {ScoreHistory} from "../src/ScoreHistory";

const empty: SessionData = {state:{},history:[],log:[],socket:null,cue:0,speech:"",connection:"Test"};

test("dashboard exposes every instrument and its details without tabs or a details dialog",()=>{
 const session={data:empty,live:false,fresh:true,setLive:()=>{}} as DriverContextValue;
 const html=renderToStaticMarkup(<DriverContext.Provider value={session}><MonitorPage/></DriverContext.Provider>);
 for(const label of ["Scoruri","Privire","Reacție","Cabină","Fișă","Sistem","Jurnal","Control","Unde privește","PERCLOS · 60 s","Scene demonstrative","Percepție · camere","Calitatea semnalului ocular","Modele · p50 / p95","Mesaje, muzică și mementouri","Răspunsuri și canale"])assert(html.includes(label),label);
 assert.doesNotMatch(html,/<dialog|Alege instrumentul|Detalii ↗|NaN|Infinity|undefined/);
 assert.equal((html.match(/class="instrument-card"/g)??[]).length,8);
});

test("dashboard journal paginates long sessions and keeps event explanations visible",()=>{
 const events=Array.from({length:20},(_,i)=>({type:"event",ts:1000-i,text:`Eveniment ${i}`,explanation:`Explicație ${i}`}));
 const html=renderToStaticMarkup(<EventJournal events={events} pageSize={4}/>);
 assert.equal((html.match(/aria-pressed=/g)??[]).length,4);
 assert(html.includes("Explicație 0"));assert(html.includes("1 / 5"));
 assert.doesNotMatch(html,/Eveniment 4</);
});

test("score charts retain separate traces across missing telemetry and label empty series",()=>{
 const html=renderToStaticMarkup(<ScoreHistory points={[{attention:.5,ts:1},null,{attention:.8,ts:3}]}/>);
 assert.equal((html.match(/vector-effect="non-scaling-stroke"/g)??[]).length,2);
 assert(html.includes("În așteptarea datelor"));
 assert.doesNotMatch(html,/NaN|Infinity/);
});

test("route points accept worldwide coordinates while rejecting invalid geographic values",()=>{
 assert(validCoordinate({lat:46.77,lon:23.59}));
 assert(validCoordinate({lat:44.43,lon:26.1}));
 assert(validCoordinate({lat:-33.87,lon:151.21}));
 assert(validCoordinate({lat:90,lon:180}));
 assert(validCoordinate({lat:-90,lon:-180}));
 assert(!validCoordinate({lat:NaN,lon:23.6}));
 assert(!validCoordinate({lat:91,lon:23.6}));
 assert(!validCoordinate({lat:46.7,lon:181}));
 assert(!validCoordinate({lat:46.7,lon:Infinity}));
});

test("simulated location interpolates along the road geometry and stops at its endpoints",()=>{
 const geometry=[{lat:46.77,lon:23.59},{lat:46.76,lon:23.59},{lat:46.76,lon:23.61}];
 const first=distanceKm(geometry[0],geometry[1]),total=first+distanceKm(geometry[1],geometry[2]);
 const cumulative=[0,first,total];
 assert.equal(locateOnRoute(geometry,cumulative,-5)?.lat,geometry[0].lat);
 const middle=locateOnRoute(geometry,cumulative,first/2)!;
 assert(Math.abs(middle.lat-46.765)<.000001);
 assert.equal(middle.lon,23.59);
 assert(Math.abs(middle.heading-180)<.01);
 const last=locateOnRoute(geometry,cumulative,total+100)!;
 assert.equal(last.lat,geometry[2].lat);assert.equal(last.lon,geometry[2].lon);
 assert.equal(locateOnRoute([],[],0),null);
});

test("partial live state renders all dashboard modules without fabricated values", () => {
 const html=renderToStaticMarkup(<MotionConfig reducedMotion="always"><General s={{}} points={[]}/><Eyes s={{}} live/><Reaction s={{}}/><Cabin s={{}}/><Scorecard s={{}}/><Performance s={{}}/><Assistant s={{}} data={empty} live={false}/></MotionConfig>);
 assert.match(html,/Direcție nedeterminată/);
 assert.match(html,/Decupaj ocular indisponibil/);
 assert.match(html,/—/);
 assert.doesNotMatch(html,/NaN|Infinity|undefined/);
});

test("zero readings and false flags survive display formatting", () => {
 assert.equal(fmt(0," ms"),"0 ms");
 assert.equal(fmt(null),"—");
 const s: DashboardState={assessment:{attention:0,fatigue:0,disengagement:0},phone:{connected:false},occupants:[],messages:[]};
 const html=renderToStaticMarkup(<><General s={s} points={[]}/><Cabin s={s}/></>);
 assert.match(html,/Telefon conectat<b>Nu/);
 assert.doesNotMatch(html,/NaN|Infinity/);
});

test("invalid or absent reaction baseline never produces a ratio", () => {
 for(const base of [0,null,undefined]) {
  const html=renderToStaticMarkup(<Reaction s={{driver:{reaction:{visual_ms:0,baseline_ms:{visual:base}}}}}/>);
  assert.doesNotMatch(html,/style="left|NaN|Infinity/);
 }
});

test("a connected core without camera frames exposes the reason and masks default ocular zeros",()=>{
 const state:DashboardState={
   driver:{monitoring_ok:false,monitoring_reason:"no_frames",eyes:{reliable:false,perclos_60s:0,closed_ms:0}},
   perf:{cameras:{driver:{available:false,age_ms:630,dropped_results:0}}},
 };
 const html=renderToStaticMarkup(<><VisionDiagnostics s={state} connection="Live · conectat"/><Eyes live s={state}/></>);
 assert.match(html,/no_frames/);
 assert.match(html,/630 ms/);
 assert.match(html,/Rezultate pierdute<\/dt><dd>0/);
 assert.match(html,/PERCLOS · 60 s<b>—/);
});

test("unknown gaze and unreliable eyes never render a synthetic eye in live mode", () => {
 const html=renderToStaticMarkup(<Eyes live s={{driver:{eyes:{reliable:false},gaze:{zone:"unknown",off_road_ms:1000}}}}/>);
 assert.match(html,/Semnal ocular nesigur/);
 assert.doesNotMatch(html,/class="optic-art"|<img/);
});

test("missed state sequence inserts a gap and history stays bounded", () => {
 const next=withState({...empty,state:{seq:10},history:Array.from({length:120},()=>({attention:.5}))},{seq:12,assessment:{attention:0}});
 assert.equal(next.history.length,120);
 assert.equal(next.history.at(-2),null);
 assert.deepEqual(next.history.at(-1),{attention:0});
 const contiguous=withState(next,{seq:13,assessment:{attention:1}});
 assert.deepEqual(contiguous.history.at(-2),{attention:0});
});

test("event log stays bounded and only visual cues increment the cue signal", () => {
 let session=empty;
 for(let i=0;i<80;i++) session=appendEvent(session,{type:i===79?"visual_cue":"alarm",ts:i});
 assert.equal(session.log.length,60);
 assert.equal(session.log[0].ts,79);
 assert.equal(session.cue,1);
});

// --- Live command bridge: the same fixture is validated against core's contract in tests/contract (Python) ---------
import uiMessages from "../../tests/contract/fixtures/dashboard_ui_messages.json";
import {liveMessage,LIVE_COMMANDS} from "../src/driver/session";
import {sampleOf,zoneShares} from "../src/telemetry";
import {Gauge,MiniBars,RangeBars,RankBars,Ring,Spark,StackBar,runs,smoothPath} from "../src/charts";
import {ControlPanel} from "../src/driver/ControlPanel";
import {KpiStrip,Overview,StatusStrip} from "../src/driver/MonitorParts";

test("every dashboard action maps to the message core expects in Live",()=>{
 for(const item of uiMessages as {name:string;args:Record<string,unknown>;state?:DashboardState;message:Record<string,unknown>}[]){
  const sent=liveMessage(item.name,item.args,item.state??{});
  assert(sent,item.name);
  const {ts,...rest}=sent as Record<string,unknown>;
  assert.deepEqual(rest,item.message,item.name);
  assert(LIVE_COMMANDS.has(item.name),item.name);
  if(item.message.type==="speech")assert.equal(typeof ts,"number");
 }
});

test("actions without a contract command are refused in Live instead of being sent as something else",()=>{
 for(const name of ["create_reminder","reply_message","play_youtube","apply_route","replay","unknown"])assert.equal(liveMessage(name,{},{}),null,name);
 assert.equal(liveMessage("calibrate",{profile:"  "},{}),null);
 assert.equal(liveMessage("enroll",{},{}),null);
 assert.equal(liveMessage("scene",{scene:"4"},{}),null);
 assert.equal(liveMessage("set_child",{enabled:false},{occupants:[]}),null);
 assert.equal(liveMessage("request",{text:"   "},{}),null);
});

test("telemetry samples hide untracked eye readings and zone shares add up",()=>{
 assert.equal(sampleOf({}),null);
 const lost=sampleOf({ts:10,driver:{monitoring_ok:false,eyes:{perclos_60s:0,ear:.3},gaze:{zone:"road"}}})!;
 assert.equal(lost.perclos,null);assert.equal(lost.zone,undefined);
 const shares=zoneShares([{ts:1,zone:"road"},{ts:2,zone:"road"},{ts:3,zone:"mirror_left"},{ts:4}]);
 assert.deepEqual(shares.map(s=>s.zone),["road","mirror_left"]);
 assert(Math.abs(shares.reduce((sum,s)=>sum+s.share,0)-1)<1e-9);
 assert.equal(shares[0].seconds,1);
});

test("charts keep gaps as gaps and never draw a missing value",()=>{
 assert.equal(runs([1,null,2,3,undefined],i=>i,v=>v).length,2);
 assert.equal(smoothPath([]),"");
 assert.match(smoothPath([[0,0],[10,5]]),/^M0 0 C/);
 const html=renderToStaticMarkup(<><Spark values={[.2,null,.4,.5]} label="s"/><MiniBars values={[null,.5]} label="b"/><Gauge value={null} label="g"/><Ring value={undefined} label="r"/>
   <RankBars items={[{label:"Drum",value:.7},{label:"Fără",value:null}]}/><StackBar parts={[{label:"A",value:0},{label:"B",value:0}]} label="st"/><RangeBars items={[{label:"x",lo:null,hi:undefined}]}/></>);
 assert.doesNotMatch(html,/NaN|Infinity|undefined/);
 assert.match(html,/Fără măsurători încă/);
 assert.equal((html.match(/stroke-dasharray/g)??[]).length,0);  // an unknown gauge / ring draws only its track
});

test("status, KPIs, overview and the control panel render an empty state without inventing values",()=>{
 const session={data:empty,live:true,fresh:false,busy:false} as unknown as DriverContextValue;
 const html=renderToStaticMarkup(<DriverContext.Provider value={session}><StatusStrip s={{}} connection="Live · conectare"/><KpiStrip s={{}} history={[]} samples={[]}/><Overview s={{}} samples={[]}/><ControlPanel/></DriverContext.Provider>);
 assert.doesNotMatch(html,/NaN|Infinity|undefined/);
 assert.match(html,/Direcție nedeterminată/);
 assert.match(html,/Nicio cauză de distragere raportată/);
 assert.equal((html.match(/<button[^>]*disabled/g)??[]).length,(html.match(/<button/g)??[]).length);  // no session: nothing is clickable
});

test("the status strip shows a camera failure, an SOS countdown and a degraded pipeline from the contract fields",()=>{
 const html=renderToStaticMarkup(<StatusStrip connection="Live · conectat" s={{safety:{level:"P0",alert:"no_response",sos:{state:"countdown",countdown_s:7.2}},
   driver:{monitoring_ok:false,monitoring_reason:"occluded"},perf:{degrade_level:2,cameras:{passenger:{available:false}}},integrations:{twilio:"down",phone_bridge:"ok"}}}/>);
 for(const text of ["P0 · Urgență","Numărătoare SOS · 8 s","Obiectiv acoperit","Indisponibilă","Treapta 2","căzut"])assert(html.includes(text),text);
});
