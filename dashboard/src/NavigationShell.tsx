import {useEffect,useRef,useState} from "react";
import {BrandLogo} from "./BrandLogo";
import type {ReactNode} from "react";

export function useMobileNavigation() {
  const [mobile,setMobile]=useState(()=>typeof matchMedia!=="undefined"&&matchMedia("(max-width:767px)").matches);
  useEffect(()=>{
    const media=matchMedia("(max-width:767px)");
    const update=()=>setMobile(media.matches);
    update();media.addEventListener("change",update);
    return ()=>media.removeEventListener("change",update);
  },[]);
  return mobile;
}

export function NavigationShell({mobile,navigationKey,children,dark}: {dark:boolean;mobile:boolean;navigationKey:string;children:ReactNode}) {
  const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
  const [open,setOpen]=useState(false);
  useEffect(()=>setOpen(false),[mobile,navigationKey]);
  useEffect(()=>{
    const panel=dialog.current;
    if(!mobile||!panel)return;
    if(!open){if(panel.open)panel.close();return;}
    panel.showModal();
    const dashboard=panel.closest<HTMLElement>(".dashboard");
    const previous=dashboard?.style.overflowY;
    if(dashboard)dashboard.style.overflowY="hidden";
    return ()=>{
      if(panel.open)panel.close();
      if(dashboard)dashboard.style.overflowY=previous??"";
      trigger.current?.focus({preventScroll:true});
    };
  },[mobile,open]);
  const content=<header className={"app-header"+(mobile?"":" desktop-sidebar")} onClick={event=>{
    if(mobile&&(event.target as Element).closest(".page-link,.section-nav button,.brand"))setOpen(false);
  }}>{children}{mobile&&<button className="mobile-close" aria-label="Închide meniul" onClick={()=>setOpen(false)}>Închide meniul</button>}</header>;
  if(!mobile)return content;
  return <>
    <div className="mobile-toolbar"><BrandLogo dark={dark}/><button ref={trigger} className="mobile-menu-button" aria-haspopup="dialog" aria-controls="mobile-navigation" aria-expanded={open} onClick={()=>setOpen(true)}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>Meniu</button></div>
    <dialog ref={dialog} id="mobile-navigation" className="mobile-drawer" aria-label="Navigare DriveMate" onCancel={()=>setOpen(false)} onClose={()=>setOpen(false)} onClick={event=>{
      if(event.target===event.currentTarget){
        const bounds=event.currentTarget.getBoundingClientRect();
        if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)setOpen(false);
      }
    }}>{content}</dialog>
  </>;
}
