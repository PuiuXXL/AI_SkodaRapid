import type {Assessment} from "./types";
export function drawHistory(canvas: HTMLCanvasElement | null, historyPoints: (Assessment | null | undefined)[]) {
  if (!canvas) return;
  const scores: (keyof Assessment)[] = ["attention","fatigue","disengagement"]; const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width || !height) return;
  const pixelRatio = window.devicePixelRatio || 1;
  const backingWidth = Math.round(width * pixelRatio), backingHeight = Math.round(height * pixelRatio);
  if (canvas.width !== backingWidth) canvas.width = backingWidth;
  if (canvas.height !== backingHeight) canvas.height = backingHeight;
  ctx.setTransform(backingWidth/width, 0, 0, backingHeight/height, 0, 0);
  ctx.clearRect(0,0,width,height);
  const colors = getComputedStyle(canvas);
  ctx.strokeStyle = colors.getPropertyValue("--line").trim(); ctx.setLineDash([]); ctx.lineWidth = 1;
  for (const y of [3,height/2,height-3]) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(width,y); ctx.stroke(); }
  scores.forEach((key,i) => {
    ctx.beginPath(); ctx.strokeStyle = colors.getPropertyValue(["--series-attention","--series-fatigue","--series-disengagement"][i]).trim();
    ctx.setLineDash([[],[8,4],[2,4]][i]); ctx.lineWidth = 2;
    let connected = false;
    historyPoints.forEach((point,index) => {
      const v = point?.[key];
      if (!Number.isFinite(v)) { connected = false; return; }
      const x = 1 + (120-historyPoints.length+index)*(width-2)/119;
      const y = height-3-(height-6)*Math.min(1,Math.max(0,v!));
      if (connected) ctx.lineTo(x,y);
      else { ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(x-1, y-1, 2, 2); ctx.moveTo(x,y); }
      connected = true;
    });
    ctx.stroke();
  });
}
