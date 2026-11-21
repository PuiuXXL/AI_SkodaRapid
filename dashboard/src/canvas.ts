import type {Assessment} from "./types";
export function drawHistory(canvas: HTMLCanvasElement | null, historyPoints: (Assessment | null | undefined)[]) {
  if (!canvas) return;
  const scores: (keyof Assessment)[] = ["attention","fatigue","disengagement"]; const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle = "#608da233"; ctx.setLineDash([]); ctx.lineWidth = 1;
  for (const y of [3,37,71]) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(720,y); ctx.stroke(); }
  scores.forEach((key,i) => {
    ctx.beginPath(); ctx.strokeStyle = ["#91bde7","#d9b681","#9baac3"][i];
    ctx.setLineDash([[],[8,4],[2,4]][i]); ctx.lineWidth = 2;
    let connected = false;
    historyPoints.forEach((point,index) => {
      const v = point?.[key];
      if (!Number.isFinite(v)) { connected = false; return; }
      const x = (120-historyPoints.length+index)*719/119, y = 71-68*Math.min(1,Math.max(0,v!));
      if (connected) ctx.lineTo(x,y); else ctx.moveTo(x,y);
      connected = true;
    });
    ctx.stroke();
  });
}
