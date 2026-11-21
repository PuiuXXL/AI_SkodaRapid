import {useSyncExternalStore} from "react";
export const pageTitles={start:"DriveMate",salut:"Salut, Andrei!",volan:"La volan",profil:"Profil",muzica:"Muzică",drum:"Drum și mementouri",mesaje:"Mesaje",rezumat:"Fișa călătoriei",dashboard:"Dashboard",simulator:"Simulator locație",player:"YouTube",missing:"Pagina nu există"} as const;
export type Page=keyof typeof pageTitles;
const legacy=new Set(["#assistant","#workspace","#eyes","#performance","#general","#recent-events","#score-history"]);
export function readPage(hash:string):Page{
  if(!hash||hash==="#"||hash==="#/")return "start";
  if(legacy.has(hash))return "dashboard";
  const key=hash.split("?")[0].replace(/^#\//,"");
  return Object.hasOwn(pageTitles,key)?key as Page:"missing";
}
export function navigate(page:Page){location.hash=page==="start"?"/":"/"+page;}
const sub=(fn:()=>void)=>{window.addEventListener("hashchange",fn);return ()=>window.removeEventListener("hashchange",fn);};
export const usePage=()=>useSyncExternalStore(sub,()=>readPage(location.hash),()=>"start" as Page);

