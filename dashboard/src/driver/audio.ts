import {useEffect,useRef,useState} from "react";
import type {SessionSocket} from "../types";
import {VoicePlayer} from "../voice/player.js";
import {SpeechInput} from "../voice/stt.js";
import {OnsetDetector} from "../voice/onset.js";

export function useDriverAudio(socket:SessionSocket|null) {
  const [audio,setAudio]=useState(false),[microphone,setMicrophone]=useState("Stopped"),[speaking,setSpeaking]=useState(false),[transcript,setTranscript]=useState(""),[error,setError]=useState("");
  const player=useRef<VoicePlayer|null>(null),recognition=useRef<SpeechInput|null>(null),onset=useRef<OnsetDetector|null>(null),transport=useRef(socket),dialogOpen=useRef(false);
  const releaseAudio=useRef<(()=>void)|null>(null),acquiring=useRef(false),generation=useRef(0);
  transport.current=socket;
  const send=(message:Record<string,unknown>)=>{if(transport.current?.readyState===1)transport.current.send(JSON.stringify({ts:Date.now()/1000,...message}));};
  useEffect(()=>{
    function receive(event:Event){
      let packet;try{packet=JSON.parse((event as MessageEvent).data)}catch{return;}
      if(packet.type==="state")dialogOpen.current=!!packet.state?.interaction?.dialog_window_open;
      const output=player.current;if(!output)return;
      if(packet.type==="speak")output.speak(packet);
      if(packet.type==="alarm")output.alarm(packet);
      if(packet.type==="media"){
        if(packet.action==="play"&&packet.video_id){
          const status=(value:string)=>send({type:"media_status",video_id:packet.video_id,title:packet.title,status:value});
          output.music.onplaying=()=>status("playing");
          output.music.onerror=()=>{status("error");setError("Unable to play this track. Check the file or media service.");};
          output.music.onended=()=>status("ended");
        }
        output.media(packet.provider==="youtube"?{...packet,url:"/media/yt/"+packet.video_id+".m4a",loop:false}:packet);
      }
      if(packet.type==="speak_control"){
        if(packet.action==="pause")output.pause();
        if(packet.action==="resume")output.resume();
        if(packet.action==="stop")output.stop();
      }
    }
    socket?.addEventListener("message",receive);
    return ()=>{generation.current++;releaseAudio.current?.();releaseAudio.current=null;socket?.removeEventListener("message",receive);player.current?.stop();player.current?.stopMusic();recognition.current?.stop();recognition.current=null;stopOnset();player.current=null;setAudio(false);setSpeaking(false);setMicrophone("Stopped");};
  },[socket]);
  function createPlayer(){
    const output=new VoicePlayer({
      onSpeakStart:()=>{setSpeaking(true);onset.current?.setSuppressed(true);if(recognition.current){recognition.current.pause();setMicrophone("Paused");}},
      onSpeakDone:(utterance:any,info:any)=>{setSpeaking(false);send({type:"speak_done",id:utterance.id,is_question:!!utterance.is_question,interrupted:info.interrupted});onset.current?.setSuppressed(false);recognition.current?.resume();},
      onAlarmPlayed:(alarm:any,ts:number)=>send({type:"alarm_played",id:alarm.id,ts})
    });
    output.unlock();player.current=output;setAudio(true);setError("");
  }
  async function activateAudio(){
    if(player.current)return true;
    if(!socket||socket.readyState!==1){setError("Connect your session before enabling audio.");return false;}
    if(acquiring.current)return false;
    if(!navigator.locks){setError("Use a browser that supports exclusive audio sessions, such as Chrome on localhost.");return false;}
    acquiring.current=true;const version=generation.current;
    return new Promise<boolean>(resolve=>{
      void navigator.locks.request("drivemate.audio",{ifAvailable:true},async lock=>{
        acquiring.current=false;
        if(!lock){setError("Audio is active in another DriveMate window. Disable it there to move it here.");resolve(false);return;}
        if(version!==generation.current){resolve(false);return;}
        createPlayer();resolve(true);
        await new Promise<void>(release=>{releaseAudio.current=release;});
      }).catch(()=>{acquiring.current=false;setError("Unable to enable the audio session.");resolve(false);});
    });
  }
  async function activateMicrophone(){
    if(!await activateAudio()||!player.current||recognition.current)return;
    try{
      const input:SpeechInput=new SpeechInput({lang:"ro-RO",isDialogOpen:()=>dialogOpen.current,
        onResult:(result:any)=>{setTranscript(result.text);if(result.final&&result.addressed)send({type:"speech",text:result.text,final:true,addressed:true});},
        onError:(reason:string)=>{if(recognition.current!==input)return;recognition.current=null;input.stop();setMicrophone("Unavailable");setError(reason==="not-allowed"?"Microphone permission denied. Audio and navigation remain available.":"Speech recognition unavailable: "+reason);},
        onStatus:(status:string)=>{
          if(recognition.current!==input||input.paused)return;
          if(status==="microphone audio received")setMicrophone("Active");
          if(status==="stopped, restarting"||status==="microphone audio ended")setMicrophone("Starting");
        }
      });
      const paused=player.current.isSpeaking();
      recognition.current=input;setError("");setMicrophone(paused?"Paused":"Starting");input.start(paused);
      void startOnset(paused);
    }catch{setMicrophone("Unavailable");setError("This browser does not support compatible speech recognition.");}
  }
  // Exact start of the driver's voice (WebAudio), sent as speech_onset: core measures the verbal reaction time from the
  // end of a question (speak_done) to this moment (core/scoring/reaction.py). Optional: speech recognition works
  // without it, so a refused or missing second microphone stream only disables the measurement.
  async function startOnset(paused:boolean){
    if(onset.current)return;
    const detector=new OnsetDetector({onOnset:(ts:number)=>send({type:"speech_onset",ts})});
    onset.current=detector;
    try{await detector.start();if(onset.current!==detector){detector.stop();return;}detector.setSuppressed(paused);}
    catch{if(onset.current===detector)onset.current=null;}
  }
  function stopOnset(){onset.current?.stop();onset.current=null;}
  function stopMicrophone(){recognition.current?.stop();recognition.current=null;stopOnset();setMicrophone("Stopped");}
  function silence(){generation.current++;player.current?.stop();player.current?.stopMusic();recognition.current?.stop();recognition.current=null;stopOnset();player.current=null;releaseAudio.current?.();releaseAudio.current=null;setAudio(false);setSpeaking(false);setMicrophone("Stopped");}
  return {audio,microphone,speaking,transcript,error,activateAudio,activateMicrophone,stopMicrophone,silence};
}
