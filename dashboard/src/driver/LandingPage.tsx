import {useEffect,useRef,useState} from "react";
import {BrandLogo} from "../BrandLogo";
import "./landing.css";

const clock=(seconds:number)=>[Math.floor(seconds/60),Math.floor(seconds%60)].map(n=>String(n).padStart(2,"0")).join(":");

export function LandingPage(){
  const film=useRef<HTMLVideoElement>(null);
  const [playing,setPlaying]=useState(false);
  const [elapsed,setElapsed]=useState(0);
  const [duration,setDuration]=useState(0);
  const [unavailable,setUnavailable]=useState(false);
  useEffect(()=>{
    const video=film.current;
    if(!video)return;
    const preference=matchMedia("(prefers-reduced-motion: reduce)");
    function pauseForPreference(){if(preference.matches)video?.pause();}
    function pauseWhenHidden(){if(document.hidden)video?.pause();}
    if(!preference.matches&&!document.hidden)void video.play().catch(()=>{});
    preference.addEventListener("change",pauseForPreference);
    document.addEventListener("visibilitychange",pauseWhenHidden);
    return ()=>{
      preference.removeEventListener("change",pauseForPreference);
      document.removeEventListener("visibilitychange",pauseWhenHidden);
    };
  },[]);
  async function toggleFilm(){
    const video=film.current;
    if(!video)return;
    if(!video.paused){video.pause();return;}
    if(video.ended)video.currentTime=0;
    try{await video.play();}catch{setUnavailable(true);}
  }
  return <main className="dm-premiere">
    <video ref={film} className="dm-premiere-film" src="/film/drivemate-grey.mp4" poster="/film/drivemate-grey.jpg"
      loop muted playsInline preload="metadata" aria-hidden="true" onError={()=>setUnavailable(true)}
      onPlaying={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onEnded={()=>setPlaying(false)}
      onTimeUpdate={e=>setElapsed(e.currentTarget.currentTime)}
      onDurationChange={e=>{const d=e.currentTarget.duration;if(Number.isFinite(d)&&d>0)setDuration(d);}}/>
    <div className="dm-premiere-shade" aria-hidden="true"/>
    <header className="dm-mast">
      <div className="dm-wordmark"><BrandLogo/><span>Copilot<br/>personal</span></div>
      
    </header>
    <div className="dm-premiere-story">
      <small className="dm-film-label">DriveMate / Copilot de drum</small>
      <h1 lang="en">for you <span>safety</span></h1>
      <div className="dm-intro"><p>Tu privești drumul. DriveMate îți urmărește atenția și te avertizează când ai nevoie de o pauză.</p>
        <a className="dm-connect" href="#/salut">Connect <span aria-hidden="true">↗</span></a>
      </div>
    </div>
    <footer className="dm-film-footer">
      <div className="dm-chapter"><small>DriveMate</small><span>Film de prezentare</span></div>
      {unavailable?<small>Cadru din film</small>:<div className="dm-transport">
        <button type="button" onClick={toggleFilm} aria-label={playing?"Pune filmul pe pauză":"Redă filmul"}>
          <span aria-hidden="true">{playing?"Ⅱ":"▶"}</span>
        </button>
        <div><span>{clock(elapsed)} / {duration?clock(duration):"—"}</span>
          <progress value={elapsed} max={duration||1} aria-label="Progres film"/></div>
      </div>}
    </footer>
  </main>;
}
