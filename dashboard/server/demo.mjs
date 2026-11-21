import {randomUUID} from "node:crypto";
import {readFileSync} from "node:fs";
import {defaultProfile, InputError} from "./profile.mjs";
import {defaultRoute, makeRoute, positionAt} from "./trip.mjs";

const readJson = path => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
const seed = readJson("../../tests/assistant/fixtures/state_example.json");
const quiz = readJson("../../assistant/data/quiz.json").questions;
const normalize = s => String(s ?? "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
const short = (s, max = 300) => {
  if (typeof s !== "string" || !s.trim() || s.length > max) throw new InputError("Verifică textul introdus.");
  return s.trim();
};
const categories = {fuel:"benzinărie", cafe:"cafenea", pharmacy:"farmacie", supermarket:"supermarket", auto_parts:"magazin de piese"};
export const demoCommands = ["start_trip","resume_trip","stop_at_poi","end_trip","scene","set_llm","set_child","inject_message","apply_route","play_youtube","play_catalog","stop_media","create_reminder","complete_reminder","defer_reminder","read_message","reply_message","answer","request","set_rate","set_speed","reset","replay"];

export class DemoDrive {
  constructor({profile = defaultProfile, now = () => Date.now()/1000, emit = () => {}} = {}) {
    this.profile = profile; this.now = now; this.emit = emit;
    this.route = defaultRoute(); this.lastReport = null; this.previousReport = null; this.seq = 0;
    this.reset();
  }
  reset() {
    this.phase = "ready"; this.tripId = null; this.scene = 1; this.distance = 0; this.elapsed = 0;
    this.speed = 72; this.rate = 1; this.lastTick = this.now(); this.elapsedTicks = 0;
    this.atPoi = null; this.stopsMade = 0; this.child = false; this.llm = true;
    this.monitoring = true; this.alert = null; this.pending = null; this.speech = ""; this.speechId = null;
    this.mutedUntil = 0; this.notice = null; this.sosAt = null; this.contactAt = null;
    this.messages = []; this.reminders = []; this.log = []; this.effects = []; this.history = [];
    this.media = {playing:false, title:null, track_id:null, volume:this.profile.preferences.volume};
    this.requestedVideo = null; this.answers = {accepted:0,rejected:0}; this.focusMinutes=0; this.longestFocus=0; this.blindMetres=0; this.blindSegments=[]; this.lastOffroad=false; this.lastCue=0;
    this.quizIndex=0; this.replayState=null; this.lastStopOffer=false; this.lastProactive=-Infinity; this.effectWindow=null;
  }
  event(type, text, extra = {}) {
    const event = {type, ts:this.now(), text, source:"SIMULAT", ...extra};
    this.log = [event, ...this.log].slice(0,60);
    this.emit({type:"event",event});
  }
  say(text, isQuestion=false, id=randomUUID()) {
    this.speech=text; this.speechId=id;
    this.emit({type:"speak",id,to:"driver",is_question:isQuestion,text,sentences:[{id,text}]});
  }
  ask(kind, question, data={}) {
    const id=randomUUID();
    this.pending = {id, kind, question, data, until:this.now()+20, dialogUntil:null};
    this.say(question,true,id);
  }
  confirmable(id) {
    const p=this.pending;
    if (!p || p.id!==id || this.now()>p.until) throw new InputError("Întrebarea a expirat sau a primit deja un răspuns.",409);
    return p;
  }
  requireStop() {
    if (this.phase==="moving") throw new InputError("Această comandă este disponibilă la oprire.",409);
  }
  nextPoi() { return this.route.stops.find(s => s.km>this.distance+0.001) ?? null; }
  stopAtNext() {
    if(this.phase!=="moving") throw new InputError("Pornește călătoria întâi.",409);
    const next=this.nextPoi();
    this.distance=next?.km ?? this.route.total; this.atPoi=next; this.phase="parked"; this.stopsMade++;
    const reminder=this.reminders.find(r=>r.state==="active" && next?.category && r.trigger.category===next.category);
    this.pending=null;
    if(reminder) this.ask("complete", "Ai zis să iei " + reminder.task + ". Ai rezolvat?", {id:reminder.id});
    this.event("stop_reached",next?.name ?? "Destinație atinsă");
  }
  start() {
    if (!["ready","finished"].includes(this.phase)) throw new InputError("Călătoria a început deja.",409);
    // Reminders and music prepared before departure belong to the upcoming trip.
    if(this.phase==="finished") this.reset();
    this.phase="moving"; this.tripId=randomUUID(); this.lastTick=this.now();
    this.event("trip_start","Călătoria a început."); this.say("Drum bun, " + this.profile.name + ".");
  }
  stopMusic() {
    this.requestedVideo=null; this.media={playing:false,track_id:null,title:null,volume:this.profile.preferences.volume};
    this.emit({type:"media",action:"stop"});
  }
  finish() {
    if(this.phase!=="parked") throw new InputError("Încheie călătoria după oprire.",409);
    this.phase="finished"; this.pending=null; this.stopMusic();
    this.event("trip_end","Călătoria s-a încheiat.");
    const s=this.state();
    this.previousReport=this.lastReport;
    this.lastReport={id:this.tripId,at:this.now(),distance_km:this.distance,elapsed_min:this.elapsed/60,
      stops:this.stopsMade,scorecard:s.scorecard,blind_m:s.blind_m,ab:s.ab,history:this.history.slice(-120),effects:[...this.effects],
      route:s.driver_ui.route,blind_segments:[...this.blindSegments],reaction:s.driver.reaction,log:this.log.slice(0,25)};
  }
  receiveMessage(text, from="DriveMate Contact", app="contact_app") {
    const msg={id:randomUUID(),text:short(text,500),from,app,ts:this.now(),replyable:true,
      state:this.phase==="moving"?"deferred":"pending",deferred_reason:this.phase==="moving"?"driving":null};
    this.messages=[msg,...this.messages].slice(0,60);
    this.event("message_received","Mesaj de la " + from);
    return msg;
  }
  recommend() {
    const track=this.profile.music_genres.flatMap(g=>this.profile.youtube_tracks.filter(t=>t.genre===g))[0] ?? this.profile.youtube_tracks[0];
    if(!track || this.child) return this.ask("quiz_offer","Facem un quiz scurt?");
    this.ask("music","Pare monoton drumul. Pun ceva " + track.genre + "?",{id:track.id});
  }
  play(id) {
    if (!/^[\w-]{11}$/.test(id)) throw new InputError("Link YouTube invalid.");
    if(this.alert) throw new InputError("Redarea așteaptă încheierea alertei.",409);
    if(this.child)throw new InputError("Piesele YouTube nu sunt validate pentru copilul declarat.",409);
    this.requestedVideo=id;
    this.emit({type:"media",action:"play",provider:"youtube",video_id:id,title:this.profile.youtube_tracks.find(t=>t.id===id)?.title??"Piesă YouTube",volume:this.scene===6?Math.min(.25,this.profile.preferences.volume):this.profile.preferences.volume});
  }
  answer(id,value) {
    const p=this.confirmable(id); const v=normalize(value);
    const yes=["da","yes","thumbs_up","nod_yes","accept","rezolvat"].includes(v);
    const no=["nu","no","thumbs_down","nod_no","palm","stop","taci","nu acum","lasa-ma in pace"].includes(v);
    if(p.kind==="kss" && !no) {
      const names=["","unu","doi","trei","patru","cinci","sase","sapte","opt","noua"];
      const score=Number(v)||names.indexOf(v);
      if(!Number.isInteger(score)||score<1||score>9)throw new InputError("Alege un răspuns între 1 și 9.");
      this.pending=null;
      if(score>=7){const poi=this.nextPoi();if(poi)this.ask("stop","Oprim la " + poi.name + "?",{id:poi.id});}
      else this.say("Am înțeles. Mulțumesc.");
      return;
    }
    if(p.kind==="quiz") {
      this.pending=null;
      const q=quiz[this.quizIndex % quiz.length]; this.quizIndex++;
      this.say(q.a.includes(v)?"Corect!":"Răspunsul era " + q.say + ".");
      return;
    }
    if(!yes&&!no)throw new InputError("Răspunde cu da sau nu.");
    this.pending=null;
    if(p.kind==="wellbeing") {
      if(yes){this.alert=null;this.sosAt=null;this.say("Am înțeles.");}
      return;
    }
    this.answers[yes?"accepted":"rejected"]++;
    this.event("answer",yes?"Sugestie acceptată":"Sugestie refuzată",{channel:"driver"});
    if(no) {
      if(p.kind==="music") this.ask("quiz_offer","Facem un quiz scurt?");
      else if(p.kind==="kss") {
        this.mutedUntil=this.now()+900;
        this.say("Ok, te las în pace.");
        if(this.profile.consent.safe_contact_notify && this.profile.safe_contact.name && (!this.contactAt||this.now()-this.contactAt>=900)){
          this.contactAt=this.now(); this.notice={type:"fatigue",at:this.contactAt,text:this.profile.name + " pare obosit. Îi poți scrie un mesaj."};
          this.event("contact_notice","Notificare de oboseală simulată.");
          if(this.profile.announce) this.say("Îi dau de veste lui " + this.profile.safe_contact.name + ".");
        }
      }
      return;
    }
    const message=this.messages.find(m=>m.id===p.data.id);
    switch(p.kind) {
      case "music": this.play(p.data.id); break;
      case "quiz_offer": this.ask("quiz",quiz[this.quizIndex%quiz.length].q); break;
      case "reminder":
        this.reminders.push({id:randomUUID(),task:p.data.task,trigger:{category:p.data.category},state:"active"});
        this.say("Notat."); break;
      case "complete": {
        const item=this.reminders.find(r=>r.id===p.data.id);
        if(item && this.phase==="parked" && this.atPoi?.category===item.trigger.category)item.state="done";
        this.say("Am notat."); break;
      }
      case "read":
        if(message){message.state="read";this.say(message.text);if(this.notice?.type==="fatigue"&&!this.lastStopOffer){this.lastStopOffer=true;const poi=this.nextPoi();if(poi)this.ask("stop","Oprim la "+poi.name+"?",{id:poi.id});}} break;
      case "reply": if(message?.replyable){message.state="replied";message.reply=p.data.text;this.say("Răspuns înregistrat în simulare.");} break;
      case "stop": this.event("stop_accepted","Oprire acceptată la " + (this.nextPoi()?.name??"destinație"));this.say("Am notat oprirea.");break;
    }
  }
  newReminder(task,category) {
    if(!Object.hasOwn(categories,category))throw new InputError("Alege categoria opririi.");
    task=short(task,100);this.ask("reminder","Să îți amintesc de " + task + " la " + categories[category] + "?",{task,category});
  }
  request(text) {
    const raw=short(text), v=normalize(raw);
    if(this.pending) return this.answer(this.pending.id,raw);
    if(/opreste muzica|opreste piesa/.test(v)) return this.stopMusic();
    if(/muzica|rock|piesa|cantec/.test(v))return this.recommend();
    if(/mesaj|citeste/.test(v)){const m=this.messages.find(m=>["pending","deferred"].includes(m.state)); if(m)return this.ask("read","Mesaj de la "+m.from+". Îl citesc?",{id:m.id});return this.say("Nu ai mesaje noi.");}
    if(/aminteste|memento/.test(v)) {
      const cat=Object.keys(categories).find(k=>v.includes(normalize(categories[k]).slice(0,5)));
      if(cat) return this.newReminder(raw.replace(/^.*?(?:să iau|sa iau|iau)\s+/i,"").split(/\s+(?:la|când|cand)\s+/i)[0],cat);
      return this.say("Spune la ce fel de oprire vrei mementoul.");
    }
    if(/pauza|oprire/.test(v)){const p=this.nextPoi(); if(p)return this.ask("stop","Oprim la "+p.name+"?",{id:p.id});}
    this.say("Pot ajuta cu muzică, mesaje, pauze și mementouri.");
  }
  setScene(number) {
    if(!Number.isInteger(number)||number<1||number>10)throw new InputError("Scenă necunoscută.");
    if(number===1){this.reset();return;}
    if(this.phase==="ready"||this.phase==="finished")this.start();
    this.scene=number;this.pending=null;this.alert=null;this.sosAt=null;this.monitoring=true;this.replayState=null;
    if(number!==7&&number!==10){this.phase="moving";this.atPoi=null;}
    this.event("scene","Scena " + number);
    switch(number){
      case 2:this.monitoring=false;this.say("Nu te mai văd. Monitorizarea e întreruptă.");break;
      case 3:this.receiveMessage("Salut! Mai durează mult?","Mihai","whatsapp");break;
      case 4:this.say("Maria, îi poți povesti tu?");this.effects.push({reason:"Priviri repetate spre pasager",action:"Delegare către pasager"});break;
      case 5:if(!this.mutedUntil || this.mutedUntil<=this.now())this.recommend();break;
      case 6:this.emit({type:"media",action:"volume",volume:Math.min(.25,this.profile.preferences.volume)});this.ask("kss","Cât de obosit ești, de la 1 la 9?");break;
      case 7:if(this.phase==="moving")this.stopAtNext();break;
      case 8:case 9:
        this.stopMusic();this.alert=number===8?"Alarmă de microsomn":"Șoferul nu răspunde";this.sosAt=this.now()+12;
        this.emit({type:"alarm",id:randomUUID(),clip_url:"/sounds/clips/alarm_andrei.mp3",text:this.alert});
        this.event("alarm",this.alert);this.ask("wellbeing","Ești bine?");break;
      case 10:if(this.phase==="moving")this.stopAtNext();this.finish();break;
    }
  }
  command(cmd,args={}) {
    switch(cmd) {
      case "start_trip":return this.start();
      case "resume_trip":if(this.phase!=="parked" || this.distance>=this.route.total)throw new InputError("Drumul nu poate continua.",409);this.phase="moving";this.atPoi=null;this.pending=null;this.lastTick=this.now();return;
      case "stop_at_poi":return this.stopAtNext();
      case "end_trip":return this.finish();
      case "scene":return this.setScene(args.scene);
      case "set_llm":this.llm=args.enabled===true;return;
      case "set_child":this.child=args.enabled===true;if(this.child)this.stopMusic();return;
      case "inject_message":return this.receiveMessage(args.text,"Mihai","whatsapp");
      case "apply_route":if(this.phase!=="ready"&&this.phase!=="finished")throw new InputError("Încheie călătoria înainte de schimbarea traseului.",409);this.route=makeRoute(args.geometry,args.stops);this.distance=0;this.atPoi=null;return;
      case "play_youtube":this.requireStop();return this.play(args.id);
      case "play_catalog":
        this.requireStop();
        if(this.alert||this.child)throw new InputError("Catalogul local nu este disponibil în acest context.",409);
        if(!/^[a-z0-9_-]{1,40}$/i.test(args.id??""))throw new InputError("Piesă invalidă.");
        this.requestedVideo=args.id;this.emit({type:"media",action:"play",video_id:args.id,title:args.id,url:"/api/driver/media/"+args.id,volume:this.profile.preferences.volume});return;
      case "stop_media":return this.stopMusic();
      case "create_reminder":this.requireStop();return this.newReminder(args.task,args.category);
      case "complete_reminder":case "defer_reminder":{
        const item=this.reminders.find(r=>r.id===args.id&&r.state==="active");
        if(!item||this.phase!=="parked"||item.trigger.category!==this.atPoi?.category)throw new InputError("Mementoul se rezolvă la oprirea potrivită.",409);
        if(cmd==="complete_reminder")item.state="done";
        this.pending=null;this.event("reminder",cmd==="complete_reminder"?"Memento rezolvat":"Păstrat pentru următoarea oprire");return;
      }
      case "read_message":case "reply_message":{
        this.requireStop();const m=this.messages.find(item=>item.id===args.id);
        if(!m)throw new InputError("Mesaj necunoscut.");
        if(cmd==="read_message")return this.ask("read","Mesaj de la "+m.from+". Îl citesc?",{id:m.id});
        if(!m.replyable)throw new InputError("Acest mesaj permite doar citirea.");
        const reply=short(args.text,300);return this.ask("reply","Îi răspund: „"+reply+"”. Trimit?",{id:m.id,text:reply});
      }
      case "answer":return this.answer(args.id,args.value);
      case "request":return this.request(args.text);
      case "set_rate":if(![1,5,20,100].includes(args.rate))throw new InputError("Ritm invalid.");this.rate=args.rate;return;
      case "set_speed":if(!Number.isFinite(args.speed)||args.speed<0||args.speed>160)throw new InputError("Viteză invalidă.");this.speed=args.speed;return;
      case "reset":this.stopMusic();this.reset();return;
      case "replay":{
        if(!args.frame || typeof args.frame!=="object" || !args.frame.driver)throw new InputError("Cadru de percepție invalid.");
        this.replayState={driver:args.frame.driver,passenger:args.frame.passenger,perf:args.frame.perf};return;
      }
      default:throw new InputError("Comandă indisponibilă.");
    }
  }
  voice(msg) {
    if(msg.type==="speech" && msg.final && msg.addressed)this.request(msg.text);
    if(msg.type==="speak_done" && this.pending?.id===msg.id && !msg.interrupted)this.pending.dialogUntil=this.now()+6;
    if(msg.type==="media_status" && this.requestedVideo===msg.video_id) {
      if(msg.status==="playing"){
        const title=short(msg.title||"Piesă YouTube",150);
        if(this.media.playing && this.media.track_id===msg.video_id && this.media.title===title)return;
        this.media={playing:true,track_id:msg.video_id,title,volume:this.profile.preferences.volume};
        this.event("media_playing",title);
        if(this.scene===5 && !this.effectWindow){this.effectWindow={elapsed:this.elapsed,before:this.scores().disengagement};this.effects.push({reason:"Dezinteres pe un drum monoton",action:"Muzică · "+title});}
      }else if(["paused","ended","error","closed"].includes(msg.status)){this.media.playing=false;if(msg.status!=="paused")this.requestedVideo=null;}
    }
  }
  scores() {
    const wave=Math.sin(this.elapsedTicks/15), quiet=this.scene===5, tired=this.scene===6||this.scene===8||this.scene===9;
    return {attention:(tired?.58:quiet?.73:.85)+.03*wave, fatigue:(tired?.73:.27)+.02*wave,
      disengagement:(quiet?(this.media.playing?.5:.73):.32)+.02*wave, risk:this.alert?3:this.phase==="moving"?1:0};
  }
  tick() {
    const now=this.now(),seconds=Math.max(0,now-this.lastTick)*this.rate;this.lastTick=now;
    this.elapsedTicks+=this.rate;
    if(this.pending && (now>this.pending.until || (this.pending.dialogUntil && now>this.pending.dialogUntil)))this.pending=null;
    if(this.phase==="moving"){
      const before=positionAt(this.route,this.distance);
      this.elapsed+=seconds;this.distance=Math.min(this.route.total,this.distance+seconds*this.speed/3600);
      if(this.scene===4 || this.alert){const metres=this.speed*seconds/3.6;this.blindMetres+=metres;
        if(!this.lastOffroad){this.blindSegments.push({from:before,to:before});this.blindSegments=this.blindSegments.slice(-80);}
        this.blindSegments.at(-1).to=positionAt(this.route,this.distance);this.lastOffroad=true;this.focusMinutes=0;
      }else{this.lastOffroad=false;this.focusMinutes+=seconds/60;this.longestFocus=Math.max(this.longestFocus,this.focusMinutes);}
      if(this.distance>=this.route.total){this.distance=Math.max(0,this.route.total-.002);this.stopAtNext();}
      if(this.effectWindow && this.elapsed-this.effectWindow.elapsed>=15){
        const effect=this.effects.findLast(e=>e.action.startsWith("Muzică")&&e.effect_pct==null);
        if(effect) effect.effect_pct=Math.round((this.effectWindow.before-this.scores().disengagement)/this.effectWindow.before*100);
        this.effectWindow=null;
      }
    }
    if(this.sosAt && now>=this.sosAt){
      this.sosAt=null;this.pending=null;this.alert="SOS simulat";this.notice={type:"sos",at:now,text:"Șoferul nu răspunde. Exercițiu SOS în simulator.",channels:{call:"simulat",sms:"simulat",contact:"disponibil"}};
      this.say("Maria, pornește avariile. Rămâi pe linie.");this.event("sos","SOS simulat către contactul de urgență.");
    }
    const cue=Math.floor((this.elapsedTicks+25)/120);
    if(cue>this.lastCue && this.phase==="moving"&&!this.alert)this.event("visual_cue","Semnal discret de probă.");
    this.lastCue=cue;
    this.seq++;this.history.push({...this.scores(),ts:this.now()});if(this.history.length>120)this.history.shift();
  }
  state() {
    const s=structuredClone(seed),scores=this.scores(),next=this.nextPoi();
    const pos=positionAt(this.route,this.distance);
    const speed=this.phase==="moving"?this.speed:0;
    s.ts=this.now();s.seq=this.seq;s.assessment=scores;
    s.trip={id:this.tripId,phase:this.phase,speed_kmh:speed,elapsed_min:this.elapsed/60,distance_km:this.distance,
      eta_min:this.speed>0?(this.route.total-this.distance)/this.speed*60:null,road:this.distance>10?"highway":"city",scene:this.scene,
      stopped:this.phase==="parked",pos,at_poi:this.atPoi,next_poi:next?{...next,dist_km:Math.max(0,next.km-this.distance)}:null};
    s.occupants[0].profile="andrei";if(this.child)s.occupants.push({id:3,profile:"Ioana",seat:"rear",role:"child",source:"declared"});
    s.driver.gaze.zone=this.scene===4?"passenger":this.elapsedTicks%120>=95?"mirror_left":"road";
    s.driver.eyes.reliable=this.monitoring;s.passenger.awake=this.scene!==6;s.passenger.holding_phone=this.scene===4;
    s.cause=this.scene===4?{label:"passenger_showing_phone",target:"passenger",glances_30s:3,sources:["cam_driver","cam_passenger"]}:seed.cause;
    s.safety={...s.safety,monitoring_ok:this.monitoring,llm_enabled:this.llm,llm_allowed:!this.alert,alert:this.alert,level:this.notice?.type==="sos"?"P0":this.alert?"P1":"P4",alarm_ms_last:null};
    s.assistant={muted_until:this.mutedUntil||null,mute_reason:this.mutedUntil>this.now()?"driver_refused":null};
    s.interaction={state:this.pending?"awaiting_answer":"idle",dialog_window_open:!!this.pending,addressed_to:"driver"};
    s.safe_contact={name:this.profile.safe_contact.name,consent:this.profile.consent.safe_contact_notify,notified_ts:this.contactAt};
    s.media=this.media;s.messages=this.messages;s.reminders=this.reminders;
    s.ab={naive_alerts:this.scene>=2?2:0,our_alerts:this.alert?1:0};s.blind_m={trip:Math.round(this.blindMetres)};
    s.scorecard={longest_focus_min:this.longestFocus,hands_free_messages:this.messages.filter(m=>m.state==="replied").length,
      phone_touches:0,suggestions_accepted:this.answers.accepted,suggestions_rejected:this.answers.rejected,reminders_done:this.reminders.filter(r=>r.state==="done").length};
    s.intervention={last:this.effects.at(-1)?.action??null,effect_pct:this.effects.at(-1)?.effect_pct??null};
    s.perf={cameras:{driver:{capture_fps:30,process_fps:24},passenger:{capture_fps:25,process_fps:10}},cpu:61,ram_mb:2100,gpu:35,e2e_ms_p95:95};
    s.driver_ui={commands:demoCommands, pending:this.pending?{id:this.pending.id,kind:this.pending.kind,question:this.pending.question}:null,
      route:{geometry:this.route.geometry.filter((_,i)=>i%Math.ceil(this.route.geometry.length/64)===0||i===this.route.geometry.length-1),stops:this.route.stops,total:this.route.total},
      rate:this.rate,speed:this.speed,child:this.child,notice:this.notice,sos_at:this.sosAt,report_id:this.lastReport?.id??null};
    if(this.replayState)for(const [k,v] of Object.entries(this.replayState))if(v && typeof v==="object")s[k]=v;
    return s;
  }
  contactStatus(){
    const {trip}=this.state();
    return {source:"demo",name:this.profile.name,phase:trip.phase,eta_min:trip.eta_min,updated_at:this.now(),notice:this.notice,
      pos:this.notice?.type==="sos"?trip.pos:null};
  }
}
