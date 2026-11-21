import React from "react";

const strokes = {
  speed: "M3 18a10 10 0 1 1 18 0 M12 14l5-6 M5 13h2 M12 5v2",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 1 1 18 0 M12 6v6l4 2",
  arrival: "M5 21V4 M5 4c5-4 9 4 15 0v9c-6 4-10-4-15 0",
  fatigue: "M3 9q9 11 18 0 M7 13l-2 3 M12 15v3 M17 13l2 3",
  focus: "M3 9V4h5 M16 4h5v5 M21 15v5h-5 M8 20H3v-5 M15 12a3 3 0 1 1-6 0 3 3 0 1 1 6 0"
};
export function MeasureIcon({name}: {name: keyof typeof strokes}) {
  return <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d={strokes[name]}/></svg>;
}
