export type ArtSubject = "camera" | "route" | "music" | "message" | "chart" | "eye" |
  "pulse" | "cabin" | "report" | "chip" | "journal" | "sliders" | "microphone" |
  "ribbons" | "conversation" | "car";

export function CardArt({subject}: {subject: ArtSubject}) {
  return <img aria-hidden="true" alt="" className="card-art" width="256" height="256"
    src={new URL(`./voice/illustrations/${subject}.png`, import.meta.url).href} decoding="async"/>;
}
