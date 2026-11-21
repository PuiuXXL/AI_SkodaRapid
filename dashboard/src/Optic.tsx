import React, {memo, useId} from "react";

// A fixed optical illustration. Only the iris position responds to simulated gaze.
const irisFibres = Array.from({length: 144}, (_, i) => {
  const depth = 13 + 4 * Math.sin(i * 2.31);
  const bend = 1.8 * Math.sin(i * .83);
  return <path key={i} transform={`rotate(${i * 2.5} 120 66)`}
    d={`M120 ${66 - depth} q${bend} -5 .7 -10 t1 -11`}
    stroke={i % 3 === 0 ? "#d1f3ef" : "#254b64"} strokeOpacity={.32 + .18 * Math.cos(i)} />;
});

export const Optic = memo(function Optic({sideways = false}: {sideways?: boolean}) {
  const id = useId();
  const paint = (name: string) => `url(#${id}-${name})`;
  const aperture = "M19 70C45 43 77 22 116 24c48 1 77 18 105 40-31 29-61 46-104 45C73 108 45 89 19 70Z";
  return <svg viewBox="0 0 240 136" className="optic-art" aria-hidden="true">
    <defs>
      <clipPath id={id+"-lid"}><path d={aperture}/></clipPath>
      <radialGradient id={id+"-white"} cx=".47" cy=".6" r=".63"><stop stopColor="#f0f4f4"/><stop offset=".62" stopColor="#c2d1d9"/><stop offset="1" stopColor="#637b91"/></radialGradient>
      <radialGradient id={id+"-iris"}><stop stopColor="#253e4f"/><stop offset=".34" stopColor="#668881"/><stop offset=".53" stopColor="#9cc2bd"/><stop offset=".82" stopColor="#5b93a5"/><stop offset=".96" stopColor="#355a74"/><stop offset="1" stopColor="#172f47"/></radialGradient>
      <linearGradient id={id+"-shade"} x2="0" y2="1"><stop stopColor="#152f49" stopOpacity=".67"/><stop offset=".38" stopColor="#152f49" stopOpacity="0"/></linearGradient>
    </defs>
    <path d="M22 56Q114 -22 216 51" fill="none" stroke="#9bb9ce" strokeWidth="1.4"/>
    <g clipPath={paint("lid")}>
      <path d={aperture} fill={paint("white")}/>
      <g transform={sideways ? "translate(-12 0)" : undefined}>
        <circle cx="120" cy="66" r="39" fill={paint("iris")}/>
        <g fill="none" strokeWidth=".85">{irisFibres}</g>
        <circle cx="120" cy="66" r="14" fill="#102536"/>
        <ellipse cx="110" cy="53" rx="7" ry="4.8" fill="#f6fbff" opacity=".94"/>
        <circle cx="132" cy="78" r="2.4" fill="#e4f5ff" opacity=".7"/>
      </g>
      <path d={aperture} fill={paint("shade")}/>
    </g>
    <path d="M18 71C81 0 157 14 222 64" fill="none" stroke="#304b61" strokeWidth="4" strokeLinecap="round"/>
    <path d="M20 72Q119 157 220 65" fill="none" stroke="#a4bac7" strokeWidth="1.6"/>
    <path d="M48 99Q123 144 195 92" fill="none" stroke="#8299ab" opacity=".58"/>
  </svg>;
});
