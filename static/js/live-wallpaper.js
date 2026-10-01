/*!
 * Stafflytics Live Wallpaper Engine
 * Particle constellation + aurora glow orbs
 * Vanilla JS — zero dependencies — SSR-safe
 * © 2026 Stafflytics Analytics Intelligence
 */
(function () {
  'use strict';

  /* ─── Configurable Defaults ─────────────────────────────────────────────── */
  const CONFIG = {
    // Particle system
    particleCount       : 80,          // Base count; scaled by viewport area
    particleBaseRadius  : 1.8,         // px (logical)
    particleRadiusRange : 1.2,         // ±range
    particleSpeedMax    : 0.35,        // Logical px / frame
    particleColor       : '130, 140, 248', // RGB of indigo #818cf8
    lineColor           : '130, 140, 248',
    connectionDistance  : 140,         // Logical px
    lineOpacityMax      : 0.18,
    // Cursor repel
    cursorRadius        : 120,         // Logical px field of influence
    cursorStrength      : 0.045,       // 0–1; how hard particles flee
    // Aurora orbs (background blobs)
    orbCount            : 3,
    orbColors           : [
      'rgba(129,140,248,0.07)',   // indigo
      'rgba(251,191,36,0.05)',    // amber
      'rgba(99,102,241,0.06)',    // violet
    ],
    orbSizeMin          : 250,         // Logical px radius
    orbSizeMax          : 420,
    orbSpeedMax         : 0.18,
    // Performance
    targetFPS           : 60,
    hiddenThrottleFPS   : 10,
    resizeDebounceMs    : 200,
  };

  /* ─── State ─────────────────────────────────────────────────────────────── */
  let canvas, ctx, dpr, W, H;
  let particles = [];
  let orbs = [];
  let mouse = { x: -9999, y: -9999 };
  let rafId = null;
  let lastTimestamp = 0;
  let resizeTimer = null;
  let initialized = false;

  /* ─── Utility ───────────────────────────────────────────────────────────── */
  const rand = (min, max) => Math.random() * (max - min) + min;
  const lerp = (a, b, t) => a + (b - a) * t;

  function targetInterval(fps) {
    return 1000 / fps;
  }

  /* ─── Canvas Setup ──────────────────────────────────────────────────────── */
  function initCanvas() {
    canvas = document.getElementById('stafflytics-wallpaper');
    if (!canvas) return false;

    ctx = canvas.getContext('2d');
    dpr = window.devicePixelRatio || 1;
    resize();
    return true;
  }

  function resize() {
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width  = W + 'px';
    canvas.style.height = H + 'px';
    ctx.scale(dpr, dpr);
    buildParticles();
    buildOrbs();
  }

  /* ─── Particle Factory ──────────────────────────────────────────────────── */
  function makeParticle() {
    const r = CONFIG.particleBaseRadius + rand(-CONFIG.particleRadiusRange, CONFIG.particleRadiusRange);
    const angle = rand(0, Math.PI * 2);
    const speed = rand(0.05, CONFIG.particleSpeedMax);
    return {
      x  : rand(0, W),
      y  : rand(0, H),
      ox : 0,   // offset pushed by cursor
      oy : 0,
      vx : Math.cos(angle) * speed,
      vy : Math.sin(angle) * speed,
      r  : Math.max(0.5, r),
      opacity : rand(0.25, 0.75),
    };
  }

  function buildParticles() {
    // Scale count linearly with viewport area vs 1920×1080 reference
    const area   = W * H;
    const refArea = 1920 * 1080;
    const count  = Math.round(CONFIG.particleCount * Math.sqrt(area / refArea));
    particles = [];
    for (let i = 0; i < count; i++) particles.push(makeParticle());
  }

  /* ─── Aurora Orb Factory ────────────────────────────────────────────────── */
  function makeOrb(i) {
    return {
      x     : rand(0, W),
      y     : rand(0, H),
      vx    : rand(-CONFIG.orbSpeedMax, CONFIG.orbSpeedMax),
      vy    : rand(-CONFIG.orbSpeedMax, CONFIG.orbSpeedMax),
      r     : rand(CONFIG.orbSizeMin, CONFIG.orbSizeMax),
      color : CONFIG.orbColors[i % CONFIG.orbColors.length],
      phase : rand(0, Math.PI * 2),
    };
  }

  function buildOrbs() {
    orbs = [];
    for (let i = 0; i < CONFIG.orbCount; i++) orbs.push(makeOrb(i));
  }

  /* ─── Draw Utilities ────────────────────────────────────────────────────── */
  function drawOrbs() {
    orbs.forEach((o) => {
      const gradient = ctx.createRadialGradient(o.x, o.y, 0, o.x, o.y, o.r);
      gradient.addColorStop(0, o.color);
      gradient.addColorStop(1, 'transparent');
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(o.x, o.y, o.r, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function drawParticles() {
    particles.forEach((p) => {
      const px = p.x + p.ox;
      const py = p.y + p.oy;

      ctx.beginPath();
      ctx.arc(px, py, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${CONFIG.particleColor},${p.opacity})`;
      ctx.fill();
    });
  }

  function drawLines() {
    const dist2 = CONFIG.connectionDistance * CONFIG.connectionDistance;
    const max = CONFIG.lineOpacityMax;

    for (let i = 0; i < particles.length; i++) {
      const pi = particles[i];
      const pix = pi.x + pi.ox;
      const piy = pi.y + pi.oy;

      for (let j = i + 1; j < particles.length; j++) {
        const pj = particles[j];
        const pjx = pj.x + pj.ox;
        const pjy = pj.y + pj.oy;
        const dx = pix - pjx;
        const dy = piy - pjy;
        const d2 = dx * dx + dy * dy;

        if (d2 < dist2) {
          const t = 1 - d2 / dist2;
          ctx.beginPath();
          ctx.moveTo(pix, piy);
          ctx.lineTo(pjx, pjy);
          ctx.strokeStyle = `rgba(${CONFIG.lineColor},${t * max})`;
          ctx.lineWidth   = t * 0.8;
          ctx.stroke();
        }
      }
    }
  }

  /* ─── Update Physics ────────────────────────────────────────────────────── */
  function updateOrbs(dt) {
    const factor = dt / 16.67; // Normalize to 60fps tick
    orbs.forEach((o, i) => {
      o.x += o.vx * factor;
      o.y += o.vy * factor;
      // Soft wrap with padding
      const pad = o.r * 0.5;
      if (o.x < -pad)  o.x = W + pad;
      if (o.x > W + pad) o.x = -pad;
      if (o.y < -pad)  o.y = H + pad;
      if (o.y > H + pad) o.y = -pad;
      // Subtle breathing
      o.phase += 0.005 * factor;
      o.r = rand(CONFIG.orbSizeMin, CONFIG.orbSizeMax) *
            (0.92 + 0.08 * Math.sin(o.phase));
    });
  }

  function updateParticles(dt) {
    const factor      = dt / 16.67;
    const cursorR2    = CONFIG.cursorRadius * CONFIG.cursorRadius;
    const strength    = CONFIG.cursorStrength;
    const returnSpeed = 0.08;

    particles.forEach((p) => {
      // Move
      p.x += p.vx * factor;
      p.y += p.vy * factor;

      // Wrap
      if (p.x < 0)  p.x = W;
      if (p.x > W)  p.x = 0;
      if (p.y < 0)  p.y = H;
      if (p.y > H)  p.y = 0;

      // Cursor repel
      const dx = (p.x + p.ox) - mouse.x;
      const dy = (p.y + p.oy) - mouse.y;
      const d2 = dx * dx + dy * dy;

      if (d2 < cursorR2 && d2 > 0) {
        const d    = Math.sqrt(d2);
        const force = (1 - d / CONFIG.cursorRadius) * strength;
        p.ox += (dx / d) * force * CONFIG.cursorRadius * factor;
        p.oy += (dy / d) * force * CONFIG.cursorRadius * factor;
      }

      // Drift offset back to 0
      p.ox = lerp(p.ox, 0, returnSpeed * factor);
      p.oy = lerp(p.oy, 0, returnSpeed * factor);
    });
  }

  /* ─── Main Loop ─────────────────────────────────────────────────────────── */
  function tick(timestamp) {
    rafId = requestAnimationFrame(tick);

    // Throttle when tab is hidden
    const fps    = document.hidden ? CONFIG.hiddenThrottleFPS : CONFIG.targetFPS;
    const minGap = targetInterval(fps);
    const dt     = timestamp - lastTimestamp;
    if (dt < minGap) return;
    lastTimestamp = timestamp;

    ctx.clearRect(0, 0, W, H);

    updateOrbs(dt);
    updateParticles(dt);

    ctx.save();

    drawOrbs();
    drawLines();
    drawParticles();

    ctx.restore();
  }

  /* ─── Event Handlers ────────────────────────────────────────────────────── */
  function onMouseMove(e) {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  }

  function onTouchMove(e) {
    if (e.touches.length > 0) {
      mouse.x = e.touches[0].clientX;
      mouse.y = e.touches[0].clientY;
    }
  }

  function onMouseLeave() {
    mouse.x = -9999;
    mouse.y = -9999;
  }

  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (rafId) cancelAnimationFrame(rafId);
      ctx.setTransform(1, 0, 0, 1, 0, 0); // Reset transform before rescaling
      resize();
      rafId = requestAnimationFrame(tick);
    }, CONFIG.resizeDebounceMs);
  }

  /* ─── Public Init ───────────────────────────────────────────────────────── */
  function init() {
    if (initialized) return;
    if (!initCanvas()) return;
    initialized = true;

    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.addEventListener('touchmove', onTouchMove, { passive: true });
    window.addEventListener('mouseleave', onMouseLeave);
    window.addEventListener('resize', onResize);

    rafId = requestAnimationFrame(tick);
  }

  /* ─── Auto-init on DOMContentLoaded ────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ─── Expose for manual control ─────────────────────────────────────────── */
  window.StafflyticsWallpaper = {
    init,
    destroy: function () {
      if (rafId) cancelAnimationFrame(rafId);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('mouseleave', onMouseLeave);
      window.removeEventListener('resize', onResize);
      initialized = false;
    },
    config: CONFIG,
  };
}());
