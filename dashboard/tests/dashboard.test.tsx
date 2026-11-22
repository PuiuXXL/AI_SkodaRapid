import {strict as assert} from "node:assert";
import {test} from "node:test";
import {renderToStaticMarkup} from "react-dom/server";
import {MotionConfig} from "motion/react";
import {General, Eyes, Reaction} from "../src/App";
import {Cabin, Scorecard, Performance, VisionDiagnostics, fmt} from "../src/Panels";
import {Assistant} from "../src/Assistant";
import {withState, appendEvent} from "../src/session-state";
import type {DashboardState, SessionData} from "../src/types";
import {MonitorPage} from "../src/driver/MonitorPage";
import {DriverContext} from "../src/driver/context";
import type {DriverContextValue} from "../src/driver/context";
import {EventJournal} from "../src/driver/EventJournal";
import {ScoreHistory} from "../src/ScoreHistory";

const empty: SessionData = {state:{},history:[],log:[],socket:null,cue:0,speech:"",connection:"Test"};

test("dashboard exposes every instrument and its details without tabs or a details dialog",()=>{
 const session={data:empty,fresh:true} as unknown as DriverContextValue;
 const html=renderToStaticMarkup(<DriverContext.Provider value={session}><MonitorPage/></DriverContext.Provider>);
 for(const label of ["Scoruri","Privire","Reacție","Cabină","Fișă","Sistem","Jurnal","Control","Unde privește","PERCLOS · 60 s","Scene demonstrative","Percepție · camere","Calitatea semnalului ocular","Modele · p50 / p95","Mesaje, muzică și mementouri","Răspunsuri și canale"])assert(html.includes(label),label);
 assert.doesNotMatch(html,/<dialog|Alege instrumentul|Detalii ↗|NaN|Infinity|undefined/);
 assert.equal((html.match(/class="instrument-card"/g)??[]).length,8);
 // Live only: no simulated source, placeholder camera or illustrative eye is offered anywhere.
 assert.doesNotMatch(html,/Simulat|SIMULAT|Sursa sesiunii|Camera în așteptare|Schemă ilustrativă|optic-art/);
 assert.equal((html.match(/<img src="[^"]*\/video\/(driver|passenger)"/g)??[]).length,2);
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

test("partial live state renders all dashboard modules without fabricated values", () => {
 const html=renderToStaticMarkup(<MotionConfig reducedMotion="always"><General s={{}} points={[]}/><Eyes s={{}}/><Reaction s={{}}/><Cabin s={{}}/><Scorecard s={{}}/><Performance s={{}}/><Assistant s={{}} data={empty}/></MotionConfig>);
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
 const html=renderToStaticMarkup(<><VisionDiagnostics s={state} connection="Live · conectat"/><Eyes s={state}/></>);
 assert.match(html,/no_frames/);
 assert.match(html,/630 ms/);
 assert.match(html,/Rezultate pierdute<\/dt><dd>0/);
 assert.match(html,/PERCLOS · 60 s<b>—/);
});

test("unknown gaze and unreliable eyes never render an eye image", () => {
 const html=renderToStaticMarkup(<Eyes s={{driver:{eyes:{reliable:false},gaze:{zone:"unknown",off_road_ms:1000}}}}/>);
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
import {driverName,tripPhase} from "../src/driver/contracts";
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
 const session={data:empty,fresh:false} as unknown as DriverContextValue;
 const html=renderToStaticMarkup(<DriverContext.Provider value={session}><StatusStrip s={{}} connection="Live · conectare"/><KpiStrip s={{}} history={[]} samples={[]}/><Overview s={{}} samples={[]}/><ControlPanel/></DriverContext.Provider>);
 assert.doesNotMatch(html,/NaN|Infinity|undefined/);
 assert.match(html,/Direcție nedeterminată/);
 assert.match(html,/Nicio cauză de distragere raportată/);
 assert.doesNotMatch(html,/P4 · Normal|<b>100%<\/b>|Telefon<\/dt><dd>Nu/);  // nothing looks measured without data
 // with data, a null level means "nothing active" (shared/contracts.py Safety.level)
 assert.match(renderToStaticMarkup(<StatusStrip s={{safety:{level:null}}} connection="c"/>),/P4 · Normal/);
 assert.equal((html.match(/<button[^>]*disabled/g)??[]).length,(html.match(/<button/g)??[]).length);  // no session: nothing is clickable
});

test("the status strip shows a camera failure, an SOS countdown and a degraded pipeline from the contract fields",()=>{
 const html=renderToStaticMarkup(<StatusStrip connection="Live · conectat" s={{safety:{level:"P0",alert:"no_response",sos:{state:"countdown",countdown_s:7.2}},
   driver:{monitoring_ok:false,monitoring_reason:"occluded"},perf:{degrade_level:2,cameras:{passenger:{available:false}}},integrations:{twilio:"down",phone_bridge:"ok"}}}/>);
 for(const text of ["P0 · Urgență","Numărătoare SOS · 8 s","Obiectiv acoperit","Indisponibilă","Treapta 2","căzut"])assert(html.includes(text),text);
});

test("trip phase and the driver's name come only from core's state",()=>{
 assert.equal(tripPhase(undefined),"unknown");
 assert.equal(tripPhase({}),"unknown");
 assert.equal(tripPhase({speed_kmh:0,stopped:false}),"ready");
 assert.equal(tripPhase({speed_kmh:0,stopped:true}),"parked");
 assert.equal(tripPhase({speed_kmh:54,stopped:false}),"moving");
 assert.equal(driverName([{seat:"passenger",profile:"maria"},{seat:"driver",profile:"andrei"}]),"Andrei");
 assert.equal(driverName([{seat:"driver",profile:null}]),undefined);
 assert.equal(driverName(undefined),undefined);
});

test("without fresh data from core the monitor shows no stale values",()=>{
 const stale={...empty,state:{trip:{speed_kmh:87},assessment:{attention:.42}},history:[{attention:.42,ts:1}]};
 const html=renderToStaticMarkup(<DriverContext.Provider value={{data:stale,fresh:false} as unknown as DriverContextValue}><MonitorPage/></DriverContext.Provider>);
 assert.doesNotMatch(html,/87 km\/h|>42</);
});

// --- Location simulator (#/simulator): the route file core follows (simulator/route.py) ---------------------------
import routeFixture from "../../tests/contract/fixtures/dashboard_route_file.json";
import {EXAMPLE_POINTS,attractionsFromWiki,geosearchUrl,locateOnRoute,nearestOnRoute,projectOnRoute,roadRoute,routeFile,searchCircles,shortDescription,distanceKm,validCoordinate} from "../src/route-simulation";
import type {RoutePlanner} from "../src/route-simulation";
import {Simulator} from "../src/Simulator";

test("route points accept worldwide coordinates while rejecting invalid geographic values",()=>{
 for(const p of [{lat:46.77,lon:23.59},{lat:-33.87,lon:151.21},{lat:90,lon:180},{lat:-90,lon:-180}])assert(validCoordinate(p));
 for(const p of [{lat:NaN,lon:23.6},{lat:91,lon:23.6},{lat:46.7,lon:181},{lat:46.7,lon:Infinity}])assert(!validCoordinate(p));
});

test("positions along the road interpolate, project back and stop at the ends",()=>{
 const geometry=[{lat:46.77,lon:23.59},{lat:46.76,lon:23.59},{lat:46.76,lon:23.61}];
 const road=roadRoute(geometry)!,first=distanceKm(geometry[0],geometry[1]);
 assert.equal(locateOnRoute(road.geometry,road.cumulative,-5)?.lat,geometry[0].lat);
 const middle=locateOnRoute(road.geometry,road.cumulative,first/2)!;
 assert(Math.abs(middle.lat-46.765)<1e-6);assert(Math.abs(middle.heading-180)<.01);
 assert(Math.abs(projectOnRoute(road.geometry,road.cumulative,middle)-first/2)<1e-3);
 assert.equal(locateOnRoute(road.geometry,road.cumulative,road.distance+100)!.lon,geometry[2].lon);
 assert.equal(roadRoute([geometry[0]]),null);assert.equal(roadRoute([geometry[0],geometry[0]]),null);
});

test("the map turns its points and road into exactly the route file core accepts (shared fixture)",()=>{
 const points=[{id:"a",name:"Sud",category:"waypoint",lat:46,lon:23},{id:"b",name:"Benzinărie",category:"fuel",lat:46.03,lon:23},
   {id:"w",name:"Nod",category:"waypoint",lat:46.05,lon:23},{id:"d",name:" Nord ",category:"cafe",lat:46.1,lon:23}];
 const road=roadRoute(Array.from({length:11},(_,i)=>({lat:46+i*.01,lon:23})));
 const sights=[{id:"wiki-ro-1",name:"Cetate",kind:"fort",lat:46.07,lon:23.02,description:" O cetate medievală. ",wikipedia:"ro:Cetate",source:"wikipedia" as const,selected:true,score:3},
   {id:"wiki-ro-2",name:"Neales",kind:"museum",lat:46.08,lon:23.01,source:"wikipedia" as const,selected:false}];
 const file=routeFile(points,road,{id:"route-fixture",ts:1795000000,speed:72,attractions:sights});
 assert.deepEqual(file,routeFixture);  // first point = origin, last = destination whatever their type, names trimmed; only chosen sights
 assert.equal("attractions" in routeFile(points,road,{id:"x",ts:0,attractions:[sights[1]]})!,false);
 const near=nearestOnRoute(road!.geometry,road!.cumulative,sights[0]);
 assert(Math.abs(near.km-7.78)<.02&&Math.abs(near.offset-1.55)<.05,JSON.stringify(near));
 assert.equal(routeFile(points.slice(0,1),road,{id:"x",ts:0}),null);
 assert.equal(routeFile(points,null,{id:"x",ts:0}),null);
 assert.equal(routeFile([{...points[0]},{...points[1],category:"bogus"},points[3]],road,{id:"x",ts:0})!.stops[0].category,"waypoint");
});

test("the location simulator page sends to core and drives nothing until core follows the route",()=>{
 const planner={points:EXAMPLE_POINTS,route:null,status:"loading",error:"",adding:false,position:null,draft:null,core:null,coreError:"",sending:false,synced:false,
   coreRoute:null,travelled:null,search:{status:"idle",error:""},placing:false,setPlacing:()=>{},toggleAttraction:()=>{},placeAttraction:()=>{},editAttraction:()=>{},removeAttraction:()=>{},findAttractions:()=>{},
   sights:[{id:"wiki-ro-1",name:"Salina Turda",kind:"attraction",lat:46.58,lon:23.79,source:"wikipedia",selected:true,km:null,detour:7.2}],add:async()=>{},edit:()=>{},send:async()=>{},clear:async()=>{},seek:async()=>{},refresh:async()=>{},rename:()=>{},setCategory:()=>{},retry:()=>{}} as unknown as RoutePlanner;
 const session={data:empty,fresh:false,can:()=>false,command:async()=>false} as unknown as DriverContextValue;
 const html=renderToStaticMarkup(<DriverContext.Provider value={session}><Simulator planner={planner}/></DriverContext.Provider>);
 for(const text of ["Trimite la core","Descarcă JSON","Deplasarea mașinii","Benzinărie · Gilău","Plecare","Destinație","Trimite traseul la core pentru a-l parcurge",
   "Ce e de văzut pe drum","Salina Turda","Atracție","Prea departe de drum","Adaugă obiectiv pe hartă"])assert(html.includes(text),text);
 assert.match(html,/<button class="primary-action" disabled="">Trimite la core/);
 assert.match(html,/<fieldset class="simulator-controls" disabled="">/);
 assert.doesNotMatch(html,/NaN|Infinity|undefined/);
});

test("tourist sights from Wikipedia: places dropped, sights ranked, chosen by default only when worth a break",()=>{
 const at=(lat:number,lon:number)=>[{lat,lon}];
 const found=attractionsFromWiki([
   {pageid:1,title:"Turda",description:"municipiu din județul Cluj, România",coordinates:at(46.57,23.78)},
   {pageid:2,title:"Comuna Mihai Viteazu, Cluj",description:"",coordinates:at(46.55,23.75)},
   {pageid:3,title:"Bădeni, Cluj",description:"sat în comuna Moldovenești, județul Cluj, România",coordinates:at(46.5,23.7)},
   {pageid:4,title:"Statuia Lupa Capitolina din Turda",coordinates:at(46.57,23.78)},
   {pageid:5,title:"Salina Turda",description:"salină din Turda",coordinates:at(46.58,23.79)},
   {pageid:6,title:"Fabrica de Bere din Turda",coordinates:at(46.57,23.78)},          // not a sight
   {pageid:7,title:"Cheile Turzii",coordinates:at(46.56,23.68)},
   {pageid:5,title:"Salina Turda",description:"salină din Turda",coordinates:at(46.58,23.79)},  // twice from two circles
   {pageid:8,title:"Castel fără coordonate"},
 ]);
 // without a road: one window, the best sight chosen, at most three kept
 assert.deepEqual(found.map(a=>[a.id,a.kind,a.selected]),[["wiki-ro-5","attraction",true],["wiki-ro-7","nature",false],["wiki-ro-4","monument",false]]);
 assert.equal(found[0].wikipedia,"ro:Salina Turda");
 const road=roadRoute([{lat:46,lon:23},{lat:46.6,lon:23}])!;  // 66.7 km
 const circles=searchCircles(road);
 assert.equal(circles.length,6);assert(circles.every(c=>c.radius>=7700&&c.radius<=10000));  // ~15 km apart, 2 km corridor covered
 assert.match(geosearchUrl(circles[0]),/generator=geosearch&ggscoord=46\.00000\|23\.00000&ggsradius=\d+&ggslimit=100&prop=coordinates\|description&colimit=max/);
 const long=searchCircles(roadRoute([{lat:44,lon:23},{lat:48,lon:23}])!);  // 445 km: still at most 24 calls, wider circles
 assert(long.length<=25&&long[0].radius<=10000);
 const measure=(point:{lat:number;lon:number})=>nearestOnRoute(road.geometry,road.cumulative,point);
 const near=attractionsFromWiki([{pageid:9,title:"Muzeul Aproape",coordinates:at(46.05,23.01)},{pageid:10,title:"Muzeul Departe",coordinates:at(46.05,23.1)},
   {pageid:11,title:"Piața Muzeului",coordinates:at(46.05,23)}],measure);
 assert.deepEqual(near.map(a=>a.name),["Muzeul Aproape"]);  // too far from the road; a square is not a museum
 // spread along the road: a city at the start is listed but not chosen; one chosen per 15 km stretch
 const spread=attractionsFromWiki([
   {pageid:20,title:"Palatul A",coordinates:at(46.001,23)},{pageid:21,title:"Castelul B",coordinates:at(46.002,23)},
   {pageid:22,title:"Muzeul C",coordinates:at(46.003,23)},{pageid:23,title:"Cetatea D",coordinates:at(46.004,23)},  // 4 at km 0: 3 kept
   {pageid:24,title:"Castelul E",coordinates:at(46.2,23)},{pageid:25,title:"Cheile F",coordinates:at(46.21,23)},     // km 22-23
   {pageid:26,title:"Salina G",coordinates:at(46.45,23)}],measure);                                                    // km 50
 assert.equal(spread.filter(a=>a.km===undefined).length,7-1);
 assert.deepEqual(spread.filter(a=>a.selected).map(a=>a.name),["Castelul E","Salina G"]);
 assert.equal(shortDescription("Salina Turda este o salină. Se află în Turda. "+"x".repeat(300)+"."),"Salina Turda este o salină. Se află în Turda.");
});

// --- Setări copilot (#/setari): P3's interaction preferences --------------------------------------------------------
import {SettingsPage,copilotSettings} from "../src/driver/SettingsPage";
import {readPage} from "../src/driver/routes";

test("the settings page shows core's preferences and sends only contract commands",()=>{
 assert.equal(readPage("#/setari"),"setari");
 const offline=renderToStaticMarkup(<DriverContext.Provider value={{data:empty,fresh:false} as unknown as DriverContextValue}><SettingsPage/></DriverContext.Provider>);
 assert.doesNotMatch(offline,/NaN|undefined|aria-pressed="true"/);  // no values invented without core
 assert.equal((offline.match(/<button[^>]*disabled/g)??[]).length,(offline.match(/<button/g)??[]).length);
 const live={data:{...empty,state:{assistant:{preferences:{talkativeness:"low",answer_length:"normal",follow_up:"never"}}}},fresh:true,
  can:(name:string)=>LIVE_COMMANDS.has(name),command:()=>undefined} as unknown as DriverContextValue;
 const html=renderToStaticMarkup(<DriverContext.Provider value={live}><SettingsPage/></DriverContext.Provider>);
 assert.equal((html.match(/aria-pressed="true"/g)??[]).length,3);
 assert.doesNotMatch(html,/<button[^>]*disabled/);
 for(const setting of copilotSettings)for(const option of setting.options){
  const message=liveMessage("set_assistant_preference",{key:setting.key,value:option.value},{});
  assert.deepEqual(message,{type:"command",cmd:"assistant_preference",value:{key:setting.key,value:option.value}});
 }
});
