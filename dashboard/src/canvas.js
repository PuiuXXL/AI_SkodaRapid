export function drawHistory(canvas, historyPoints) {
  const scores = ["attention","fatigue","disengagement"]; const ctx = canvas.getContext("2d");
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle = "#dbe3df"; ctx.setLineDash([]); ctx.lineWidth = 1;
  for (const y of [3,37,71]) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(720,y); ctx.stroke(); }
  scores.forEach((key,i) => {
    ctx.beginPath(); ctx.strokeStyle = ["#116c63","#965a27","#715990"][i];
    ctx.setLineDash([[],[8,4],[2,4]][i]); ctx.lineWidth = 2;
    let connected = false;
    historyPoints.forEach((point,index) => {
      const v = point?.[key];
      if (!Number.isFinite(v)) { connected = false; return; }
      const x = (120-historyPoints.length+index)*719/119, y = 71-68*Math.min(1,Math.max(0,v));
      if (connected) ctx.lineTo(x,y); else ctx.moveTo(x,y);
      connected = true;
    });
    ctx.stroke();
  });
}

export function drawPortrait(canvas) {
  const ctx = canvas.getContext("2d"); ctx.clearRect(0,0,600,420);
  for (let j=1;j<88;j++) {
    const angle=j*Math.PI/90, y=Math.cos(angle);
    for(let i=0;i<110;i++) {
      const a=i*Math.PI/109, x=Math.cos(a)*Math.sin(angle)*(y<0?1+.28*y:1);
      const z=Math.sin(a)*Math.sin(angle)+.42*Math.exp(-40*x*x-18*(y+.04)**2)
        -.18*Math.exp(-70*(Math.abs(x)-.36)**2-60*(y-.18)**2);
      const px=295+142*x-48*z, py=194-166*y+8*z;
      ctx.fillStyle="rgba(158,226,203,"+(.14+.58*Math.sin(a)**2)+")";
      ctx.fillRect(px,py,1.2,1.25);
    }
  }
}

