import React, {memo, useId} from "react";

// Static vector detail; only simulated gaze changes the iris position.
const irisFibres = Array.from({length: 180}, (_, i) => {
  const inner=14+2.5*Math.sin(i*2.31),outer=35+2*Math.cos(i*1.37);
  const bend=1.8*Math.sin(i*.83),fork=24+3*Math.cos(i*1.63);
  return <g key={i} transform={`rotate(${i*2} 120 66)`}>
    <path d={`M120 ${66-inner} Q${120+bend*2} ${66-fork} ${120+bend} ${66-outer}`}
      stroke={i%3===0?"var(--optic-iris-light)":"var(--optic-iris-shadow)"}
      strokeWidth={i%5===0?1.1:.55} strokeOpacity={.35+.2*Math.cos(i)}/>
    {i%3===0&&<path d={`M${120+bend} ${66-fork} q${2+bend} -4 ${1+bend} -9`}
      stroke="var(--ui-accent-hover)" strokeWidth=".45" strokeOpacity=".5"/>}
  </g>;
});
const irisCrypts=Array.from({length:36},(_,i)=>{
  const radius=19+2*Math.sin(i*2.4);
  return <ellipse key={i} cx="120" cy={66-radius} rx={.7+.3*Math.cos(i)} ry={1.8+.7*Math.sin(i)}
    transform={`rotate(${i*10} 120 66)`} fill="var(--optic-iris-shadow)" opacity=".65"/>;
});

export const Optic = memo(function Optic({sideways = false}: {sideways?: boolean}) {
  const id = useId();
  const paint = (name: string) => `url(#${id}-${name})`;
  const aperture = "M19 70C45 43 77 22 116 24c48 1 77 18 105 40-31 29-61 46-104 45C73 108 45 89 19 70Z";
  return <svg viewBox="0 0 240 136" className="optic-art" aria-hidden="true" focusable="false">
    <defs>
      <clipPath id={id+"-lid"}><path d={aperture}/></clipPath>
      <clipPath id={id+"-iris-clip"}><circle cx="120" cy="66" r="38"/></clipPath>
      <radialGradient id={id+"-white"} cx=".47" cy=".65" r=".65"><stop stopColor="var(--optic-sclera-light)"/><stop offset=".56" stopColor="var(--optic-sclera)"/><stop offset="1" stopColor="var(--ui-inset)"/></radialGradient>
      <radialGradient id={id+"-iris"}><stop stopColor="var(--optic-iris-shadow)"/><stop offset=".36" stopColor="var(--ui-accent)"/><stop offset=".58" stopColor="var(--optic-iris-mid)"/><stop offset=".83" stopColor="var(--optic-iris-shadow)"/><stop offset="1" stopColor="var(--ui-inset)"/></radialGradient>
      <radialGradient id={id+"-pupil"} cx=".42" cy=".3"><stop stopColor="var(--ui-surface-2)"/><stop offset="1" stopColor="var(--ui-bg)"/></radialGradient>
      <linearGradient id={id+"-shade"} x2="0" y2="1"><stop stopColor="var(--ui-bg)" stopOpacity=".85"/><stop offset=".5" stopColor="var(--ui-bg)" stopOpacity="0"/><stop offset="1" stopColor="var(--ui-bg)" stopOpacity=".3"/></linearGradient>
      <linearGradient id={id+"-rim"} x2="1" y2=".4"><stop stopColor="var(--optic-lid)"/><stop offset=".48" stopColor="var(--ui-accent-hover)"/><stop offset="1" stopColor="var(--optic-lid)"/></linearGradient>
    </defs>
    <g fill="none" strokeLinecap="round">
      <path d="M25 51C74 4 159 3 212 45" stroke="var(--optic-lid)" strokeWidth="1.2"/>
      <path d="M44 40C91 9 154 11 194 34" stroke="var(--ui-stroke-strong)" strokeWidth=".6"/>
      <path d="M35 94Q122 153 207 91" stroke="var(--optic-lid)" strokeWidth=".8"/>
    </g>
    <g clipPath={paint("lid")}>
      <path d={aperture} fill={paint("white")}/>
      <g fill="none" stroke="var(--optic-lid)" strokeWidth=".6" opacity=".45">
        <path d="M24 70q19-4 37 8m-20-7 12-9m-2 14 10 10M214 65q-20 2-35 15m20-10-9-8m3 14-7 12"/>
      </g>
      <g transform={sideways ? "translate(-12 0)" : undefined}>
        <circle cx="120" cy="66" r="39" fill="var(--ui-bg)" stroke="var(--optic-lid)" strokeWidth=".7"/>
        <g clipPath={paint("iris-clip")}>
          <circle cx="120" cy="66" r="38" fill={paint("iris")}/>
          <g fill="none">{irisFibres}</g>
          {irisCrypts}
          <circle cx="120" cy="66" r="35.5" fill="none" stroke="var(--optic-iris-light)" strokeWidth=".55" opacity=".4"/>
          <circle cx="120" cy="66" r="16.5" fill="none" stroke="var(--optic-iris-light)" strokeWidth="1" strokeDasharray=".6 1.8" opacity=".65"/>
          <circle cx="120" cy="66" r="13.5" fill={paint("pupil")} stroke="var(--optic-iris-shadow)" strokeWidth="1.5"/>
          <path d="M96 53a29 29 0 0 1 38-13" fill="none" stroke="var(--ui-text)" strokeWidth="2.5" strokeLinecap="round" opacity=".18"/>
          <ellipse cx="109" cy="52" rx="6" ry="3.5" transform="rotate(-28 109 52)" fill="var(--ui-text)" opacity=".85"/>
          <ellipse cx="116" cy="49" rx="1.5" ry="1" fill="var(--ui-text)" opacity=".6"/>
          <circle cx="133" cy="80" r="1.6" fill="var(--optic-iris-light)" opacity=".7"/>
          <path d="M103 91a30 30 0 0 0 28 1" fill="none" stroke="var(--optic-iris-light)" strokeWidth=".8" opacity=".35"/>
        </g>
      </g>
      <path d={aperture} fill={paint("shade")}/>
    </g>
    <path d={aperture} fill="none" stroke="var(--optic-lid)" strokeWidth="1.2"/>
    <path d="M19 70C45 43 77 22 116 24c48 1 77 18 105 40" fill="none" stroke="var(--ui-inset)" strokeWidth="4" strokeLinecap="round"/>
    <path d="M24 67C76 11 158 13 216 61" fill="none" stroke={paint("rim")} strokeWidth="1" strokeLinecap="round" opacity=".8"/>
    <path d="M22 73Q117 145 218 67" fill="none" stroke={paint("rim")} strokeWidth="1.1" opacity=".7"/>
    <path d="M27 69l7 1-4 5Z" fill="var(--ui-accent)" opacity=".45"/>
  </svg>;
});
