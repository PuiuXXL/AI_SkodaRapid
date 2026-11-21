import {InputError} from "./profile.mjs";

const coordinate = p => Number.isFinite(p?.lat) && Math.abs(p.lat) <= 90 && Number.isFinite(p.lon) && Math.abs(p.lon) <= 180;
function km(a, b) {
  const deg = Math.PI / 180;
  const h = Math.sin((b.lat-a.lat)*deg/2)**2 + Math.cos(a.lat*deg)*Math.cos(b.lat*deg)*Math.sin((b.lon-a.lon)*deg/2)**2;
  return 12742 * Math.asin(Math.sqrt(Math.min(1, h)));
}

export function makeRoute(geometry, stops) {
  if (!Array.isArray(geometry) || geometry.length < 2 || geometry.length > 3000 || !geometry.every(coordinate) ||
      !Array.isArray(stops) || stops.length > 60) throw new InputError("Geometrie de traseu invalidă.");
  const cumulative = [0];
  for (let i = 1; i < geometry.length; i++) cumulative.push(cumulative[i-1] + km(geometry[i-1], geometry[i]));
  const total = cumulative.at(-1);
  if (!(total > 0)) throw new InputError("Alege două puncte distincte.");
  const routeStops = stops.map((p, i) => {
    if (!coordinate(p) || typeof p.name !== "string" || !p.name.trim() || p.name.length > 100) throw new InputError("Oprire invalidă.");
    const nearest = geometry.reduce((best, v, j) => km(p, v) < km(p, geometry[best]) ? j : best, 0);
    return {id: "poi-" + i, name: p.name.trim(), lat: p.lat, lon: p.lon, km: cumulative[nearest],
      category: ["fuel","cafe","pharmacy","supermarket","auto_parts"].includes(p.category) ? p.category : null};
  }).sort((a,b) => a.km - b.km);
  return {geometry: geometry.map(({lat,lon}) => ({lat,lon})), cumulative, total, stops: routeStops};
}

export function defaultRoute() {
  const points = [
    {lat:46.769, lon:23.589}, {lat:46.758, lon:23.556}, {lat:46.751, lon:23.511},
    {lat:46.745, lon:23.486}, {lat:46.750, lon:23.429}, {lat:46.751, lon:23.391},
    {lat:46.724, lon:23.405}, {lat:46.686, lon:23.468}, {lat:46.644, lon:23.506},
    {lat:46.602, lon:23.566}, {lat:46.559, lon:23.669}, {lat:46.567, lon:23.783}
  ];
  return makeRoute(points, [
    {...points[3], name:"Benzinărie · Florești", category:"fuel"},
    {...points[5], name:"Cafenea · Gilău", category:"cafe"},
    {...points.at(-1), name:"Turda", category:null}
  ]);
}

export function positionAt(route, distance) {
  const d = Math.max(0, Math.min(route.total, distance));
  let end = route.cumulative.findIndex(n => n >= d);
  end = Math.max(1, end);
  const a = route.geometry[end-1], b = route.geometry[end];
  const fraction = (d-route.cumulative[end-1])/(route.cumulative[end]-route.cumulative[end-1] || 1);
  return {lat:a.lat+(b.lat-a.lat)*fraction, lon:a.lon+(b.lon-a.lon)*fraction};
}
