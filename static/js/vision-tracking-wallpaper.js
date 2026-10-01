/*!
 * Stafflytics AI — Multi-Agent Vision Tracking Engine
 * Vanilla JS — Zero dependencies — Continuous AI Entities & Vector Mesh
 * © 2026 Stafflytics Analytics Intelligence
 */
(function () {
  'use strict';

  const CONFIG = {
    targetCount: 8,
    emeraldRGB: '16, 185, 129',
    cyanRGB: '6, 182, 212',
    gridRGB: '30, 41, 59',
    targetFPS: 60,
    hiddenThrottleFPS: 10,
  };

  const ZONES = ['[LOBBY]', '[CORRIDOR]', '[WORKSTATION]', '[SERVER ROOM]', '[EXECUTIVE]'];
  const HEX = '0123456789ABCDEF';

  let canvas, ctx, dpr, W, H;
  let targets = [];
  let mouse = { x: -9999, y: -9999, active: false };
  let rafId = null;
  let lastTime = 0;
  let resizeTimer = null;

  function genID() {
    let s = 'STAFF #';
    for (let i = 0; i < 4; i++) s += HEX[Math.floor(Math.random() * HEX.length)];
    return s;
  }

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

  function createTarget(isCursor) {
    const angle = Math.random() * Math.PI * 2;
    const speed = 0.2 + Math.random() * 0.4;
    const baseConf = 96.0 + Math.random() * 3.8;
    return {
      id: genID(),
      x: Math.random() * W,
      y: Math.random() * H,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      baseConfidence: baseConf,
      confidence: baseConf,
      zone: ZONES[Math.floor(Math.random() * ZONES.length)],
      history: [],
      size: 18 + Math.random() * 4,
      opacity: 0,
      life: 0,
      maxLife: 600 + Math.random() * 400,
      pulsePhase: Math.random() * Math.PI * 2,
      isCursorTarget: !!isCursor,
    };
  }

  function initTargets() {
    targets = Array.from({ length: CONFIG.targetCount }, (_, i) => createTarget(i === 0));
  }

  function drawGridTicks() {
    const step = 100;
    ctx.strokeStyle = `rgba(${CONFIG.gridRGB}, 0.35)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = step; x < W; x += step) {
      for (let y = step; y < H; y += step) {
        ctx.moveTo(x - 3, y); ctx.lineTo(x + 3, y);
        ctx.moveTo(x, y - 3); ctx.lineTo(x, y + 3);
      }
    }
    ctx.stroke();
  }

  function drawMesh() {
    const maxDist = 160;
    const maxDistSq = maxDist * maxDist;

    for (let i = 0; i < targets.length; i++) {
      const t1 = targets[i];
      if (t1.opacity < 0.1) continue;
      for (let j = i + 1; j < targets.length; j++) {
        const t2 = targets[j];
        if (t2.opacity < 0.1) continue;

        const dx = t1.x - t2.x;
        const dy = t1.y - t2.y;
        const distSq = dx * dx + dy * dy;

        if (distSq < maxDistSq) {
          const alpha = (1 - distSq / maxDistSq) * 0.22 * Math.min(t1.opacity, t2.opacity);
          ctx.strokeStyle = `rgba(${CONFIG.cyanRGB}, ${alpha})`;
          ctx.lineWidth = 0.8;
          ctx.beginPath();
          ctx.moveTo(t1.x, t1.y);
          ctx.lineTo(t2.x, t2.y);
          ctx.stroke();
        }
      }
    }
  }

  function updateAndDraw(dt) {
    const factor = dt / 16.67;

    targets.forEach((t) => {
      t.life += factor;
      const fadeIn = 40, fadeOut = 50;

      if (t.life < fadeIn) {
        t.opacity = t.life / fadeIn;
      } else if (t.life > t.maxLife - fadeOut) {
        t.opacity = Math.max(0, (t.maxLife - t.life) / fadeOut);
      } else {
        t.opacity = 1;
      }

      if (t.life >= t.maxLife) {
        Object.assign(t, createTarget(t.isCursorTarget));
        t.opacity = 0;
      }

      if (t.isCursorTarget && mouse.active) {
        t.x += (mouse.x - t.x) * 0.08 * factor;
        t.y += (mouse.y - t.y) * 0.08 * factor;
      } else {
        t.x += t.vx * factor;
        t.y += t.vy * factor;
        const pad = 40;
        if (t.x < -pad) t.x = W + pad;
        if (t.x > W + pad) t.x = -pad;
        if (t.y < -pad) t.y = H + pad;
        if (t.y > H + pad) t.y = -pad;
      }

      t.confidence = Math.min(99.9, Math.max(96.0, t.baseConfidence + (Math.random() - 0.5) * 0.35));

      t.history.push({ x: t.x, y: t.y });
      if (t.history.length > 8) t.history.shift();

      const opacity = t.opacity * 0.85;
      if (opacity <= 0.01) return;

      // Breadcrumb Trail
      if (t.history.length > 1) {
        ctx.strokeStyle = `rgba(${CONFIG.emeraldRGB}, ${opacity * 0.2})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(t.history[0].x, t.history[0].y);
        for (let k = 1; k < t.history.length; k++) {
          ctx.lineTo(t.history[k].x, t.history[k].y);
        }
        ctx.stroke();
      }

      // Center Anchor Dot & Pulse
      t.pulsePhase += 0.04 * factor;
      const pulse = 1 + 0.25 * Math.sin(t.pulsePhase);

      ctx.fillStyle = `rgba(${CONFIG.emeraldRGB}, ${opacity})`;
      ctx.beginPath();
      ctx.arc(t.x, t.y, 2, 0, Math.PI * 2);
      ctx.fill();

      ctx.strokeStyle = `rgba(${CONFIG.emeraldRGB}, ${opacity * 0.35})`;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.arc(t.x, t.y, 6 * pulse, 0, Math.PI * 2);
      ctx.stroke();

      // Corner Brackets [ ┌ ┐ └ ┘ ]
      const s = t.size, x = t.x, y = t.y;
      ctx.strokeStyle = `rgba(${CONFIG.emeraldRGB}, ${opacity * 0.9})`;
      ctx.lineWidth = 1.2;

      ctx.beginPath();
      ctx.moveTo(x - s, y - s + 5); ctx.lineTo(x - s, y - s); ctx.lineTo(x - s + 5, y - s);
      ctx.moveTo(x + s - 5, y - s); ctx.lineTo(x + s, y - s); ctx.lineTo(x + s, y - s + 5);
      ctx.moveTo(x + s, y + s - 5); ctx.lineTo(x + s, y + s); ctx.lineTo(x + s - 5, y + s);
      ctx.moveTo(x - s + 5, y + s); ctx.lineTo(x - s, y + s); ctx.lineTo(x - s, y + s - 5);
      ctx.stroke();

      // Telemetry Text
      const lx = x + s + 6;
      const ly = y - s + 8;
      ctx.font = '10px monospace';
      ctx.fillStyle = `rgba(${CONFIG.emeraldRGB}, ${opacity})`;
      ctx.fillText(t.id, lx, ly);

      ctx.fillStyle = `rgba(148, 163, 184, ${opacity * 0.75})`;
      ctx.fillText(`CONF: ${t.confidence.toFixed(1)}%`, lx, ly + 11);
      ctx.fillText(t.zone, lx, ly + 22);
    });
  }

  function render(time) {
    rafId = requestAnimationFrame(render);
    const fps = document.hidden ? CONFIG.hiddenThrottleFPS : CONFIG.targetFPS;
    if (time - lastTime < 1000 / fps) return;
    const dt = time - lastTime;
    lastTime = time;

    ctx.fillStyle = '#090D16';
    ctx.fillRect(0, 0, W, H);

    drawGridTicks();
    drawMesh();
    updateAndDraw(dt);
  }

  function init() {
    canvas = document.getElementById('stafflytics-wallpaper') || document.getElementById('vision-tracking-wallpaper');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    setSize();
    initTargets();

    window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; mouse.active = true; }, { passive: true });
    window.addEventListener('mouseleave', () => { mouse.active = false; }, { passive: true });
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (rafId) cancelAnimationFrame(rafId);
        setSize();
        initTargets();
        rafId = requestAnimationFrame(render);
      }, 150);
    });

    rafId = requestAnimationFrame(render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
