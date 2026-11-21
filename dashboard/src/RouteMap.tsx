import React,{useEffect,useRef,useState} from "react";
import type * as Leaflet from "leaflet";
import type {RouteSimulation} from "./route-simulation";
import "leaflet/dist/leaflet.css";

const mapViews = [
  {id:"soft",label:"Soft"},
  {id:"streets",label:"Rutier"},
  {id:"satellite",label:"Satelit"},
  {id:"terrain",label:"Relief"}
] as const;
type MapView = typeof mapViews[number]["id"];

export function RouteMap({simulation,disabled,pointsOpen,onOpenLayers}: {simulation:RouteSimulation;disabled:boolean;pointsOpen:boolean;onOpenLayers:()=>void}) {
  const host=useRef<HTMLDivElement>(null),map=useRef<Leaflet.Map|null>(null);
  const library=useRef<typeof Leaflet|null>(null),layers=useRef<Leaflet.LayerGroup|null>(null);
  const car=useRef<Leaflet.Marker|null>(null),latest=useRef({simulation,disabled});
  const [ready,setReady]=useState(false),[mapError,setMapError]=useState("");
  const [mapView,setMapView]=useState<MapView>("soft");
  const [showRoute,setShowRoute]=useState(true),[showPoints,setShowPoints]=useState(true),[showCar,setShowCar]=useState(true);
  const layerPanel=useRef<HTMLDetailsElement>(null);
  const tileKind=mapView==="soft"?"streets":mapView;
  useEffect(()=>{if(pointsOpen&&(host.current?.clientWidth??0)<620&&layerPanel.current)layerPanel.current.open=false},[pointsOpen]);
  useEffect(()=>{latest.current={simulation,disabled}},[simulation,disabled]);
  useEffect(()=>{
    let cancelled=false;
    let observer:ResizeObserver|undefined;
    async function init(){
      try{
        const L=await import("leaflet");
        if(cancelled||!host.current)return;
        library.current=L;
        const view=L.map(host.current,{worldCopyJump:true,minZoom:2,maxZoom:18,scrollWheelZoom:true});
        map.current=view;
        view.fitBounds([[46.48,23.24],[46.86,23.94]],host.current.clientWidth<600?
          {paddingTopLeft:[10,310],paddingBottomRight:[10,20]}:
          {paddingTopLeft:[20,20],paddingBottomRight:[350,20]});
        L.control.scale({imperial:false}).addTo(view);
        layers.current=L.layerGroup().addTo(view);
        view.on("click",(event:Leaflet.LeafletMouseEvent)=>{
          const point=event.latlng.wrap();
          if(!latest.current.disabled)void latest.current.simulation.add({lat:point.lat,lon:point.lng});
        });
        observer=new ResizeObserver(()=>view.invalidateSize({pan:false}));
        observer.observe(host.current);
        setReady(true);
      }catch{if(!cancelled)setMapError("Harta nu a putut fi încărcată. Reîncarcă pagina.")}
    }
    void init();
    return ()=>{cancelled=true;observer?.disconnect();map.current?.remove();map.current=null;car.current=null;layers.current=null};
  },[]);
  useEffect(()=>{
    const L=library.current,view=map.current;
    if(!ready||!L||!view)return;
    setMapError("");
    const sources={
      streets:{url:"https://tile.openstreetmap.org/{z}/{x}/{y}.png",attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'},
      satellite:{url:"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",attribution:'Tiles &copy; Esri, Vantor, Earthstar Geographics, GIS User Community · <a href="https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer">Surse</a>'},
      terrain:{url:"https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",attribution:'Tiles &copy; Esri · <a href="https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer">Surse și atribuiri</a>'}
    };
    const source=sources[tileKind];
    const tiles=L.tileLayer(source.url,{attribution:source.attribution,maxZoom:19});
    tiles.on("tileerror",()=>setMapError("Unele imagini ale hărții nu s-au încărcat. Verifică conexiunea sau alege alt strat."));
    tiles.addTo(view);
    return ()=>{tiles.off();tiles.remove()};
  },[ready,tileKind]);
  useEffect(()=>{
    const L=library.current,group=layers.current;
    if(!ready||!L||!group)return;
    group.clearLayers();
    const coordinates=simulation.route?.geometry??simulation.points;
    if(showRoute&&coordinates.length>1){
      const path=coordinates.map(p=>[p.lat,p.lon] as [number,number]);
      L.polyline(path,{color:"#f7fff9",weight:9,opacity:.8,interactive:false}).addTo(group);
      L.polyline(path,{color:"#009c73",weight:4.5,opacity:1,dashArray:simulation.route?undefined:"5 8",lineCap:"round"}).addTo(group);
    }
    if(showPoints)simulation.points.forEach((point,index)=>{
      const tooltip=document.createElement("span");tooltip.textContent=point.name;
      const marker=L.marker([point.lat,point.lon],{
        draggable:!disabled&&!simulation.adding,
        icon:L.divIcon({className:"route-waypoint"+(index===0?" waypoint-start":index===simulation.points.length-1?" waypoint-end":""),html:`<span>${index+1}</span>`,iconSize:[30,30],iconAnchor:[15,15]}),
        title:`${index+1}. ${point.name}`,keyboard:true
      }).bindTooltip(tooltip).addTo(group);
      marker.on("dragend",()=>{
        const dropped=marker.getLatLng().wrap();
        marker.setLatLng([point.lat,point.lon]);
        void latest.current.simulation.add({lat:dropped.lat,lon:dropped.lng},point.id);
      });
    });
  },[ready,simulation.points,simulation.route,simulation.adding,disabled,showRoute,showPoints]);
  useEffect(()=>{
    const L=library.current,view=map.current,position=simulation.position;
    if(!ready||!L||!view)return;
    if(!position||!showCar){car.current?.remove();car.current=null;return;}
    if(!car.current)car.current=L.marker([position.lat,position.lon],{
      interactive:false,zIndexOffset:1000,
      icon:L.divIcon({className:"route-car",html:'<span aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M8 3h8l3 5v12h-3v-3H8v3H5V8l3-5Z" fill="white"/><path d="m9 5-2 4h10l-2-4H9Z" fill="#007c5b"/><path d="M8 13h1m6 0h1" stroke="#007c5b" stroke-width="2" stroke-linecap="round"/></svg></span>',iconSize:[36,36],iconAnchor:[18,18]})
    }).addTo(view);
    car.current.setLatLng([position.lat,position.lon]);
    const arrow=car.current.getElement()?.querySelector("span") as HTMLElement|null;
    if(arrow)arrow.style.transform=`rotate(${position.heading}deg)`;
  },[ready,simulation.position,showCar]);
  function fit(route:boolean){
    const compact=(host.current?.clientWidth??0)<600;
    const points=latest.current.simulation.route?.geometry??latest.current.simulation.points;
    const bounds:Leaflet.LatLngTuple[]=route?points.map(p=>[p.lat,p.lon]):[[46.48,23.24],[46.86,23.94]];
    if(!bounds.length)return;
    map.current?.fitBounds(bounds,{
      animate:false,maxZoom:15,paddingTopLeft:compact?[10,310]:[20,20],paddingBottomRight:compact?[10,20]:[350,20]
    });
  }
  return <div className="route-map-shell">
    <div className="route-map-toolbar"><span>Hartă rutieră · navigare liberă</span><div><button onClick={()=>fit(false)} disabled={!ready}>Cluj–A3</button><button onClick={()=>fit(true)} disabled={!ready||!simulation.points.length}>Vezi traseul</button></div></div>
    <div className="route-map-canvas">
      <div ref={host} className="route-map" data-view={mapView} role="region" aria-label="Hartă rutieră interactivă. Apasă pentru a adăuga un punct."/>
      <details ref={layerPanel} className="map-layers" onToggle={event=>{if(event.currentTarget.open&&(host.current?.clientWidth??0)<620)onOpenLayers()}} onKeyDown={event=>{if(event.key==="Escape"){event.currentTarget.open=false;event.currentTarget.querySelector("summary")?.focus()}}}>
        <summary><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m3 7 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 17l9 5 9-5"/></svg><span>Straturi</span><small>{mapViews.find(item=>item.id===mapView)?.label}</small></summary>
        <div className="map-layer-content">
          <fieldset><legend>Vizualizare hartă</legend><div className="map-view-options">{mapViews.map(item=><button key={item.id} aria-pressed={mapView===item.id} onClick={()=>setMapView(item.id)} disabled={!ready}><span className="map-view-swatch" data-view={item.id} aria-hidden="true"/>{item.label}</button>)}</div></fieldset>
          <fieldset className="map-overlay-options"><legend>Elemente vizibile</legend><label><input type="checkbox" checked={showRoute} onChange={event=>setShowRoute(event.target.checked)}/>Traseu</label><label><input type="checkbox" checked={showPoints} onChange={event=>setShowPoints(event.target.checked)}/>Puncte de oprire</label><label><input type="checkbox" checked={showCar} onChange={event=>setShowCar(event.target.checked)}/>Mașină</label></fieldset>
        </div>
      </details>
      <div className="map-route-legend" aria-hidden="true"><i/>{simulation.editingLocked?"Simulare în curs":simulation.route?"Traseu auto":"Planificare traseu"}</div>
    </div>
    {mapError&&<p className="map-notice" role="status">{mapError}</p>}
  </div>;
}
