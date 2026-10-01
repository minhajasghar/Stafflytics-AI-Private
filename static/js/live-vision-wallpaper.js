/*!
 * Stafflytics AI — Live Vision Operations Center Wallpaper Engine
 * Vanilla JS — Zero dependencies — Spatial Radar Grid & Target Reticles
 * © 2026 Stafflytics Analytics Intelligence
 */
(function () {
  'use strict';

  const CONFIG = {
    nodeCount: 45,
    accentRGB: '16, 185, 129',   // Emerald
    highlightRGB: '6, 182, 212', // Cyan
    gridRGB: '30, 41, 59',      // Slate
    targetFPS: 60,
    hiddenThrottleFPS: 10,
    resizeDebounceMs: 150,
  };

  let canvas, ctx, dpr, W, H;
  let nodes = [];
  let mouse = { x: -9999, y: -9999, active: false };
  let scanY = 0;
  let rafId = null;
  let lastTime = 0;
  let resizeTimer = null;
  let autoLockTimer = 0;

  const randID = () => {
    const chars = '0123456789ABCDEF';
    let res = 'STAFF-#';
    for (let i = 0; i < 4; i++) res += chars[Math.floor(Math.random() * chars.length)];
    return res;
  };

  function setSize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }

  function initNodes() {
    const count = Math.max(20, Math.round(CONFIG.nodeCount * Math.sqrt((W * H) / (1920 * 1080))));
    nodes = Array.from({ length: count }, () => ({
      id: randID(),
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.45,
      vy: (Math.random() - 0.5) * 0.45,
      r: 2 + Math.random() * 1.5,
      confidence: 88 + Math.random() * 11.5,
      isLocked: false,
      lockTimer: 0,
      pulsePhase: Math.random() * Math.PI * 2,
    }));
  }

  function drawGrid() {
    const step = 60;
    ctx.strokeStyle = `rgba(${CONFIG.gridRGB}, 0.25)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x < W; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (let y = 0; y < H; y += step) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();

    ctx.strokeStyle = `rgba(${CONFIG.gridRGB}, 0.55)`;
    ctx.beginPath();
    for (let x = 180; x < W; x += 180) {
      for (let y = 180; y < H; y += 180) {
        ctx.moveTo(x - 4, y); ctx.lineTo(x + 4, y);
        ctx.moveTo(x, y - 4); ctx.lineTo(x, y + 4);
      }
    }
    ctx.stroke();
  }

  function drawScanline() {
    scanY += 1.2;
    if (scanY > H + 60) scanY = -60;
    const gradient = ctx.createLinearGradient(0, scanY - 40, 0, scanY);
    gradient.addColorStop(0, 'rgba(16, 185, 129, 0)');
    gradient.addColorStop(1, 'rgba(6, 182, 212, 0.12)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, scanY - 40, W, 40);

    ctx.strokeStyle = `rgba(${CONFIG.highlightRGB}, 0.25)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, scanY);
    ctx.lineTo(W, scanY);
    ctx.stroke();
  }

  function drawMeshAndNodes(dt) {
    const factor = dt / 16.67;
    const maxDist = 135;
    const maxDistSq = maxDist * maxDist;

    for (let i = 0; i < nodes.length; i++) {
      const n1 = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const n2 = nodes[j];
        const dx = n1.x - n2.x;
        const dy = n1.y - n2.y;
        const dSq = dx * dx + dy * dy;
        if (dSq < maxDistSq) {
          const alpha = (1 - dSq / maxDistSq) * 0.35;
          const isHighPriority = n1.isLocked || n2.isLocked;
          ctx.strokeStyle = isHighPriority
            ? `rgba(${CONFIG.accentRGB}, ${alpha * 1.5})`
            : `rgba(${CONFIG.gridRGB}, ${alpha})`;
          ctx.lineWidth = isHighPriority ? 1.2 : 0.8;
          ctx.beginPath();
          ctx.moveTo(n1.x, n1.y);
          ctx.lineTo(n2.x, n2.y);
          ctx.stroke();
        }
      }
    }

    nodes.forEach((n) => {
      n.x += n.vx * factor; n.y += n.vy * factor;
      if (n.x < 0) n.x = W; if (n.x > W) n.x = 0;
      if (n.y < 0) n.y = H; if (n.y > H) n.y = 0;

      const dxM = n.x - mouse.x;
      const dyM = n.y - mouse.y;
      const distM = Math.sqrt(dxM * dxM + dyM * dyM);

      if (mouse.active && distM < 120) {
        n.isLocked = true;
        n.lockTimer = 60;
      } else if (n.lockTimer > 0) {
        n.lockTimer -= 1 * factor;
        if (n.lockTimer <= 0) n.isLocked = false;
      }

      ctx.fillStyle = n.isLocked
        ? `rgba(${CONFIG.accentRGB}, 0.95)`
        : `rgba(${CONFIG.highlightRGB}, 0.65)`;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * (n.isLocked ? 1.5 : 1), 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function drawTargetHUDs() {
    nodes.forEach((n) => {
      if (!n.isLocked) return;
      const size = 18;
      ctx.strokeStyle = `rgba(${CONFIG.accentRGB}, 0.85)`;
      ctx.lineWidth = 1.2;

      ctx.beginPath();
      ctx.moveTo(n.x - size, n.y - size + 6); ctx.lineTo(n.x - size, n.y - size); ctx.lineTo(n.x - size + 6, n.y - size);
      ctx.moveTo(n.x + size - 6, n.y - size); ctx.lineTo(n.x + size, n.y - size); ctx.lineTo(n.x + size, n.y - size + 6);
      ctx.moveTo(n.x + size, n.y + size - 6); ctx.lineTo(n.x + size, n.y + size); ctx.lineTo(n.x + size - 6, n.y + size);
      ctx.moveTo(n.x - size + 6, n.y + size); ctx.lineTo(n.x - size, n.y + size); ctx.lineTo(n.x - size, n.y + size - 6);
      ctx.stroke();

      ctx.font = '10px monospace';
      ctx.fillStyle = `rgba(${CONFIG.accentRGB}, 0.9)`;
      ctx.fillText(`[ ${n.id} ]`, n.x + size + 6, n.y - size + 8);
      ctx.fillStyle = 'rgba(148, 163, 184, 0.75)';
      ctx.fillText(`CONF: ${n.confidence.toFixed(1)}%`, n.x + size + 6, n.y - size + 20);
    });
  }

  function render(time) {
    rafId = requestAnimationFrame(render);
    const fps = document.hidden ? CONFIG.hiddenThrottleFPS : CONFIG.targetFPS;
    const minInterval = 1000 / fps;
    const dt = time - lastTime;
    if (dt < minInterval) return;
    lastTime = time;

    ctx.fillStyle = '#060913';
    ctx.fillRect(0, 0, W, H);
    drawGrid();
    drawScanline();
    drawMeshAndNodes(dt);
    drawTargetHUDs();

    autoLockTimer++;
    if (autoLockTimer % 180 === 0) {
      const idx = Math.floor(Math.random() * nodes.length);
      nodes.forEach((n, i) => { if (i === idx) { n.isLocked = true; n.lockTimer = 120; } });
    }
  }

  function init() {
    canvas = document.getElementById('stafflytics-wallpaper') || document.getElementById('live-vision-wallpaper');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    setSize();
    initNodes();

    window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; mouse.active = true; }, { passive: true });
    window.addEventListener('mouseleave', () => { mouse.active = false; }, { passive: true });
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (rafId) cancelAnimationFrame(rafId);
        setSize();
        initNodes();
        rafId = requestAnimationFrame(render);
      }, CONFIG.resizeDebounceMs);
    });

    rafId = requestAnimationFrame(render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
