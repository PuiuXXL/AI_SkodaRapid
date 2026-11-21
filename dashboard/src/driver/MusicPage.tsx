import {useEffect,useState} from "react";
import {useDriver} from "./context";
import {api,errorText,genres} from "./contracts";
import {PageHeading,AudioControls,Copilot} from "./DrivingPages";

interface CatalogTrack {id:string;title:string;artist:string;genre:string;available:boolean;kid_safe:boolean}
export function youtubeId(value:string){
  if(/^[\w-]{11}$/.test(value))return value;
  try{const url=new URL(value);if(!["https:","http:"].includes(url.protocol))return null;const host=url.hostname.toLowerCase();const id=host==="youtu.be"?url.pathname.slice(1):["youtube.com","www.youtube.com","m.youtube.com"].includes(host)?url.searchParams.get("v")??url.pathname.match(/^\/(?:embed|shorts)\/([\w-]{11})$/)?.[1]:null;return id&&/^[\w-]{11}$/.test(id)?id:null;}catch{return null;}
}
export function MusicPage(){
  const {data,profile,draft,setDraft,saveProfile,live,locked,fresh,busy,command,audio}=useDriver();
  const [catalog,setCatalog]=useState<CatalogTrack[]>([]),[error,setError]=useState(""),[link,setLink]=useState(""),[title,setTitle]=useState(""),[genre,setGenre]=useState("rock");
  useEffect(()=>{api<{tracks:CatalogTrack[]}>("/api/driver/catalog").then(result=>setCatalog(result.tracks)).catch(e=>setError(errorText(e)));},[]);
  const [chosen,setChosen]=useState("");
  const selected=catalog.find(track=>track.id===chosen)??catalog[0];
  const media=data.state.media,child=data.state.driver_ui?.child;
  return <><PageHeading label="MUZICĂ" title="Coloana sonoră a drumului" description="Piesa curentă este confirmată de player. Copilotul poate propune muzică potrivită contextului."/>
    <section className="music-current"><div className="record-mark large" aria-hidden="true"><span/></div><div><small>ACUM ASCULȚI</small><h2>{media?.playing?media.title??"Redare în curs":media?.playing===false?"Muzica e oprită":"Stare indisponibilă"}</h2>{media?.artist&&<p>{media.artist}</p>}<button disabled={live||busy||!fresh} onClick={()=>command("stop_media")}>Oprește muzica</button><p>Volum confirmat: {typeof media?.volume==="number"?Math.round(media.volume*100)+"%":"—"}</p></div></section><AudioControls/>
    <div className="music-library"><section><h2>Catalog local</h2>{error&&<p role="alert">{error}</p>}<ul className="driver-list">{catalog.map(track=><li key={track.id}><button className="track-choice" aria-pressed={selected?.id===track.id} onClick={()=>setChosen(track.id)}><strong>{track.title}</strong><span>{track.artist||"Artist necunoscut"} · {track.genre}</span></button></li>)}</ul></section><section className="track-detail"><small>Piesă selectată</small>{selected?<><h2>{selected.title}</h2><p>{selected.artist} · {selected.genre}</p><p>{selected.available?"Fișier local disponibil":"Fișierul audio nu este instalat pe acest laptop."}</p><button className="primary-action" disabled={!selected.available||!audio.audio||locked||live||busy||!fresh||(child&&!selected.kid_safe)} onClick={()=>command("play_catalog",{id:selected.id})}>Redă piesa</button></>:<p>Catalogul nu conține piese disponibile.</p>}{child&&<p>Cu un copil declarat, sunt disponibile numai piesele marcate potrivite pentru copii.</p>}</section>
    <section className="saved-library"><h2>Biblioteca ta YouTube</h2><p>Piesele salvate sunt păstrate în profil. Redarea audio necesită serviciul media al core-ului.</p><ul className="driver-list">{profile?.youtube_tracks.map(track=><li key={track.id}><div><strong>{track.title}</strong><p>{track.genre}</p></div><button disabled={!audio.audio||locked||live||busy||!fresh||child} onClick={()=>command("play_youtube",{id:track.id})}>Redă</button></li>)}</ul>{!profile?.youtube_tracks.length&&<p className="empty-state">Nu ai salvat încă piese YouTube.</p>}
      <fieldset disabled={live||locked||!fresh}><legend>Adaugă o piesă în profil</legend><label>Link sau ID YouTube<input value={link} maxLength={300} onChange={e=>setLink(e.target.value)} placeholder="https://www.youtube.com/watch?v=…"/></label><label>Titlul piesei<input value={title} maxLength={120} onChange={e=>setTitle(e.target.value)}/></label><label>Gen<select value={genre} onChange={e=>setGenre(e.target.value)}>{genres.map(g=><option key={g}>{g}</option>)}</select></label><button disabled={!youtubeId(link)||!title.trim()||!draft||draft.youtube_tracks.length>=40} onClick={()=>{const id=youtubeId(link);if(!id||!draft)return;if(draft.youtube_tracks.some(t=>t.id===id)){setError("Piesa este deja în bibliotecă.");return;}setDraft({...draft,youtube_tracks:[...draft.youtube_tracks,{id,title:title.trim(),genre:genre as typeof genres[number]}]});setLink("");setTitle("");setError("Piesa este în ciorna profilului. Salvează biblioteca pentru a o folosi.");}}>Adaugă în bibliotecă</button><button className="primary-action" disabled={!draft||JSON.stringify(draft.youtube_tracks)===JSON.stringify(profile?.youtube_tracks)} onClick={async()=>{if(await saveProfile())setError("Bibliotecă salvată.");}}>Salvează biblioteca</button></fieldset>
    </section></div><Copilot/>
  </>;
}
