import {strict as assert} from "node:assert";
import {test} from "node:test";
import {renderToStaticMarkup} from "react-dom/server";
import {MotionConfig} from "motion/react";
import {General, Eyes, Reaction} from "../src/App";
import {Cabin, Scorecard, Performance, fmt} from "../src/Panels";
import {Assistant} from "../src/Assistant";
import {withState, appendEvent} from "../src/session-state";
import type {DashboardState, SessionData} from "../src/types";

const empty: SessionData = {state:{},history:[],log:[],socket:null,cue:0,speech:"",connection:"Test"};

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

test("unknown gaze and unreliable eyes never render a synthetic eye in live mode", () => {
 const html=renderToStaticMarkup(<Eyes live s={{driver:{eyes:{reliable:false},gaze:{zone:"unknown",off_road_ms:1000}}}}/>);
 assert.match(html,/Semnal ocular nesigur/);
 assert.doesNotMatch(html,/eye-plate|<img/);
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
