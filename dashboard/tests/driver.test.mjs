import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm,readFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {Readable,Writable} from "node:stream";
import {DemoDrive} from "../server/demo.mjs";
import {createDriverApi} from "../server/api.mjs";
import {defaultProfile,profileStore} from "../server/profile.mjs";

async function fixture(t){
  const directory=await mkdtemp(join(tmpdir(),"drivemate-driver-"));
  const profilePath=join(directory,"profile.json");
  const api=await createDriverApi({profilePath,token:"test-contact-token"});
  t.after(async()=>{api.close();await rm(directory,{recursive:true,force:true});});
  async function request(path,{method="GET",data,remote="127.0.0.1",origin}={}){
    const req=Readable.from(data===undefined?[]:[Buffer.from(JSON.stringify(data))]);
    req.url=path;req.method=method;req.socket={remoteAddress:remote};req.headers={host:"localhost:5173","content-type":"application/json",...(origin?{origin}:{})};
    let status,headers,output="";
    const res=new Writable({write(chunk,encoding,done){output+=chunk;done();}});
    res.writeHead=(code,values)=>{status=code;headers=values;};
    await api.handler(req,res,()=>{throw new Error("Unexpected middleware fallthrough");});
    return {status,headers,body:output?JSON.parse(output):null};
  }
  return {request,profilePath};
}
test("profile writes keep identity, advance revisions and reject stale edits",async t=>{
  const {profilePath}=await fixture(t),store=profileStore(profilePath);
  const initial=await store.load();
  const saved=await store.save({...initial,id:"another-person",name:"Alex",consent:{safe_contact_notify:false}});
  assert.equal(saved.id,"andrei");assert.equal(saved.name,"Alex");assert.equal(saved.revision,1);
  await assert.rejects(()=>store.save({...initial,name:"Stale"}),/altă fereastră/);
  assert.equal(JSON.parse(await readFile(profilePath,"utf8")).name,"Alex");
});
test("profile consent requires a named trusted contact",async t=>{
  const {profilePath}=await fixture(t),store=profileStore(profilePath),profile=await store.load();
  await assert.rejects(()=>store.save({...profile,consent:{safe_contact_notify:true}}),/numele contactului/);
});
test("API enforces local commands and isolates token contact access",async t=>{
  const {request}=await fixture(t);
  assert.equal((await request("/api/driver/profile",{remote:"192.0.2.1"})).status,403);
  assert.equal((await request("/api/contact/wrong-token",{remote:"192.0.2.1"})).status,404);
  const contact=await request("/api/contact/test-contact-token",{remote:"192.0.2.1"});
  assert.equal(contact.status,200);assert.equal(contact.body.source,"demo");assert.equal(contact.body.pos,null);
  assert.equal(contact.body.preferences,undefined);assert.equal(contact.body.consent,undefined);
  assert.equal((await request("/api/driver/profile",{origin:"https://untrusted.example"})).status,403);
});
test("command receipts make retried starts idempotent and forbid profile editing in motion",async t=>{
  const {request}=await fixture(t);
  const profile=(await request("/api/driver/profile")).body;
  const command={id:"same-request",cmd:"start_trip",trip_id:null};
  assert.equal((await request("/api/driver/command",{method:"POST",data:command})).status,200);
  assert.equal((await request("/api/driver/command",{method:"POST",data:command})).status,200);
  assert.equal((await request("/api/driver/profile",{method:"PUT",data:{...profile,name:"Changed while moving"}})).status,409);
  assert.equal((await request("/api/driver/profile")).body.name,profile.name);
});
test("contact message retries do not produce duplicate messages",async t=>{
  const {request}=await fixture(t);
  const data={id:"same-message",text:"Drum bun!"};
  const first=await request("/api/contact/test-contact-token/messages",{method:"POST",data});
  const second=await request("/api/contact/test-contact-token/messages",{method:"POST",data});
  assert.equal(first.status,200);assert.deepEqual(first.body,second.body);
});
test("message replies remain pending until explicit confirmation and cannot be confirmed twice",()=>{
  const drive=new DemoDrive();const message=drive.receiveMessage("Ajungi curând?","Mihai");
  drive.command("reply_message",{id:message.id,text:"Ajung în 20 de minute."});
  assert.notEqual(message.state,"replied");const question=drive.pending.id;
  drive.command("answer",{id:question,value:"da"});assert.equal(message.state,"replied");
  assert.throws(()=>drive.command("answer",{id:question,value:"da"}),/expirat/);
});
test("a reminder requires confirmation and a compatible actual stop",()=>{
  const drive=new DemoDrive();
  drive.command("create_reminder",{task:"apă",category:"fuel"});assert.equal(drive.reminders.length,0);
  drive.command("answer",{id:drive.pending.id,value:"da"});const item=drive.reminders[0];
  assert.throws(()=>drive.command("complete_reminder",{id:item.id}),/oprirea potrivită/);
  drive.command("start_trip");drive.command("stop_at_poi");
  drive.command("complete_reminder",{id:item.id});assert.equal(item.state,"done");
});
test("music state is confirmed by the audio player and child context blocks unverified YouTube",()=>{
  const drive=new DemoDrive();
  drive.command("play_youtube",{id:"abcdefghijk"});assert.equal(drive.media.playing,false);
  drive.voice({type:"media_status",video_id:"abcdefghijk",status:"playing",title:"Piesă de test"});
  assert.equal(drive.media.title,"Piesă de test");assert.equal(drive.media.playing,true);
  drive.command("set_child",{enabled:true});assert.equal(drive.media.playing,false);
  assert.throws(()=>drive.command("play_youtube",{id:"abcdefghijk"}),/copil/);
});
test("a report is created only after a confirmed stop and retains the previous trip",()=>{
  let now=1000;const drive=new DemoDrive({now:()=>now});
  drive.command("start_trip");assert.throws(()=>drive.command("end_trip"),/după oprire/);
  now+=60;drive.tick();drive.command("stop_at_poi");drive.command("end_trip");
  const first=drive.lastReport;assert(first.id);assert(first.distance_km>0);assert(first.elapsed_min>0);
  drive.command("start_trip");now+=30;drive.tick();drive.command("stop_at_poi");drive.command("end_trip");
  assert.equal(drive.previousReport.id,first.id);assert.notEqual(drive.lastReport.id,first.id);
});
test("SOS contact position is available only during a simulated SOS",()=>{
  let now=1000;const drive=new DemoDrive({now:()=>now});
  assert.equal(drive.contactStatus().pos,null);drive.command("scene",{scene:9});now+=13;drive.tick();
  const status=drive.contactStatus();assert.equal(status.notice.type,"sos");assert.equal(status.source,"demo");assert(status.pos);assert.equal(status.notice.channels.call,"simulat");
});
