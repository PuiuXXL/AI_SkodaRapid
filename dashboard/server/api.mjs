import {randomBytes, timingSafeEqual} from "node:crypto";
import {fileURLToPath} from "node:url";
import {createReadStream,existsSync,readFileSync} from "node:fs";
import {DemoDrive} from "./demo.mjs";
import {InputError, profileStore} from "./profile.mjs";

const catalog=JSON.parse(readFileSync(new URL("../../assistant/data/media_catalog.json",import.meta.url),"utf8")).tracks;
function mediaFile(track){
  return [new URL("../public/sounds/music/"+track.file,import.meta.url),new URL("../../assistant/data/media/"+track.file,import.meta.url)].find(path=>existsSync(path));
}

function json(res, status, data) {
  res.writeHead(status, {"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","Referrer-Policy":"no-referrer"});
  res.end(JSON.stringify(data));
}
async function body(req) {
  if (!(req.headers["content-type"]??"").startsWith("application/json")) throw new InputError("Format JSON necesar.",415);
  let bytes=0; const chunks=[];
  for await(const chunk of req) {
    bytes+=chunk.length;if(bytes>350000)throw new InputError("Cererea este prea mare.",413);
    chunks.push(chunk);
  }
  try { const value=JSON.parse(Buffer.concat(chunks).toString("utf8"));if(!value||Array.isArray(value)||typeof value!=="object")throw new Error();return value; }
  catch{throw new InputError("Conținut JSON invalid.");}
}
function isLocal(req) {
  return ["127.0.0.1","::1","::ffff:127.0.0.1"].includes(req.socket.remoteAddress) &&
    /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(req.headers.host??"");
}
function sameOrigin(req) {
  if(!req.headers.origin)return true;
  try {return new URL(req.headers.origin).host===req.headers.host;} catch{return false;}
}
export async function createDriverApi({profilePath=fileURLToPath(new URL("../../profiles/andrei/profile.json",import.meta.url)), token=randomBytes(24).toString("hex"), now}={}) {
  const profiles=profileStore(profilePath);
  const clients=new Set(), receipts=new Map();
  const broadcast=packet=>{
    const data="data: "+JSON.stringify(packet)+"\n\n";
    for(const res of clients) {
      if(res.destroyed || res.writableLength>1024*1024){clients.delete(res);res.destroy();}
      else res.write(data);
    }
  };
  const drive=new DemoDrive({profile:await profiles.load(),now,emit:broadcast});
  const sendState=()=>broadcast({type:"state",state:drive.state()});
  const timer=setInterval(()=>{if(clients.size||drive.phase==="moving"){drive.tick();if(clients.size)sendState();}},100);
  timer.unref();
  async function handler(req,res,next) {
    const path=(req.url??"").split("?")[0];
    if(!path.startsWith("/api/driver/")&&!path.startsWith("/api/contact/")){next();return;}
    try{
      if(!sameOrigin(req))throw new InputError("Origine neacceptată.",403);
      if(path.startsWith("/api/contact/")) {
        const parts=path.slice("/api/contact/".length).split("/");
        const secret=Buffer.from(token), given=Buffer.from(parts[0]);
        if(secret.length!==given.length||!timingSafeEqual(secret,given))throw new InputError("Linkul de contact este invalid sau a expirat.",404);
        if(req.method==="GET"&&parts.length===1){json(res,200,drive.contactStatus());return;}
        if(req.method==="POST"&&parts.length===2&&parts[1]==="messages"){
          const data=await body(req);
          // A retry after a lost response must not insert a second message.
          if(typeof data.id!=="string" || data.id.length>80)throw new InputError("Identificator de mesaj invalid.");
          const key="contact:"+data.id;
          if(!receipts.has(key)){const msg=drive.receiveMessage(data.text);remember(key,{id:msg.id});sendState();}
          json(res,200,receipts.get(key));return;
        }
        throw new InputError("Operație de contact necunoscută.",404);
      }
      if(!isLocal(req))throw new InputError("Comenzile șoferului sunt disponibile pe laptopul local.",403);
      if(req.method==="GET"&&path==="/api/driver/catalog"){
        json(res,200,{tracks:catalog.map(({id,title,artist,genre,kid_safe,...rest})=>({id,title,artist,genre,kid_safe,available:!!mediaFile({file:rest.file})}))});return;
      }
      if(req.method==="GET"&&path.startsWith("/api/driver/media/")){
        const track=catalog.find(track=>track.id===path.slice("/api/driver/media/".length));
        const file=track&&mediaFile(track);if(!file)throw new InputError("Fișierul audio nu este instalat.",404);
        res.writeHead(200,{"Content-Type":"audio/mpeg","Cache-Control":"no-store"});
        const stream=createReadStream(file);stream.on("error",()=>res.destroy());stream.pipe(res);return;
      }
      if(path==="/api/driver/profile"){
        if(req.method==="GET"){json(res,200,drive.profile);return;}
        if(req.method==="PUT"){
          drive.requireStop();
          drive.profile=await profiles.save(await body(req));drive.media.volume=drive.profile.preferences.volume;
          broadcast({type:"profile_changed",revision:drive.profile.revision});sendState();json(res,200,drive.profile);return;
        }
      }
      if(req.method==="GET"&&path==="/api/driver/contact"){json(res,200,{url:"/c/"+token});return;}
      if(req.method==="GET"&&path==="/api/driver/reports"){json(res,200,{latest:drive.lastReport,previous:drive.previousReport});return;}
      if(req.method==="GET"&&path==="/api/driver/events"){
        res.writeHead(200,{"Content-Type":"text/event-stream","Cache-Control":"no-store","Connection":"keep-alive","X-Accel-Buffering":"no"});
        res.write("retry: 1500\n\n");
        res.write("data: "+JSON.stringify({type:"snapshot",state:drive.state(),log:drive.log,history:drive.history,speech:drive.speech})+"\n\n");
        clients.add(res);res.on("close",()=>clients.delete(res));return;
      }
      if(req.method==="POST"&&path==="/api/driver/command"){
        const m=await body(req);
        if(typeof m.id!=="string"||m.id.length>80)throw new InputError("Identificator de comandă invalid.");
        const key="cmd:"+m.id;
        if(!receipts.has(key)){
          if(m.trip_id!==undefined && m.trip_id!==drive.tripId)throw new InputError("Călătoria s-a schimbat.",409);
          if(m.cmd==="play_catalog"){
            const track=catalog.find(track=>track.id===m.args?.id);
            if(!track||!mediaFile(track))throw new InputError("Fișierul audio nu este instalat.",404);
          }
          drive.command(m.cmd,m.args);remember(key,{ok:true});sendState();
        }
        json(res,200,receipts.get(key));return;
      }
      if(req.method==="POST"&&path==="/api/driver/voice"){
        const msg=await body(req);
        if(msg.trip_id!==undefined&&msg.trip_id!==drive.tripId)throw new InputError("Călătoria s-a schimbat.",409);
        drive.voice(msg);sendState();json(res,200,{ok:true});return;
      }
      throw new InputError("Adresă necunoscută.",404);
    }catch(error){json(res,error instanceof InputError?error.status:500,{error:error instanceof InputError?error.message:"Serviciul local nu a putut finaliza operația."});}
  }
  function remember(key,value){receipts.set(key,value);if(receipts.size>512)receipts.delete(receipts.keys().next().value);}
  return {handler,close(){clearInterval(timer);for(const client of clients)client.end();clients.clear();}};
}

export function driverPlugin() {
  async function setup(server){
    const api=await createDriverApi(process.env.DRIVEMATE_PROFILE_PATH?{profilePath:process.env.DRIVEMATE_PROFILE_PATH}:{});
    server.middlewares.use(api.handler);
    server.httpServer?.once("close",()=>api.close());
  }
  return {name:"drivemate-local-driver",configureServer:setup,configurePreviewServer:setup};
}
