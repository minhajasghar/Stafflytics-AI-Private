'use client';

/**
 * LiveVisionWallpaper.tsx — Enterprise Vision Operations Center
 * ─────────────────────────────────────────────────────────────
 * High-performance HTML5 Canvas 2D live wallpaper.
 * Inspired by Palantir / Verkada computer vision & surveillance consoles.
 *
 * Features:
 * - Spatial Radar Grid overlay with subtle coordinate crosshairs
 * - Dynamic Tracking Nodes (Staff/Camera vectors) with proximity mesh lines
 * - Target Lock Wireframes [ + ] with AI Confidence & ID HUD tags
 * - Smooth vertical Radar Scanline sweep
 * - Mouse & Touch cursor tracking with magnetic target lock
 * - High-DPI (Retina) devicePixelRatio support & debounced resize
 * - Tab visibility throttling (document.hidden -> 10 FPS) for CPU/battery savings
 * - Full useEffect cleanup (prevents memory leaks on route changes)
 * - 100% SSR-safe & Next.js App Router compatible
 */

import React, { useEffect, useRef } from 'react';

export interface LiveVisionWallpaperProps {
  /** Base count of tracking nodes for a 1920x1080 screen (scales with viewport) */
  nodeCount?: number;
  /** Primary accent color triple for active tracking markers (emerald) */
  accentRGB?: string; // e.g. '16, 185, 129'
  /** Secondary highlight color triple (cyan) */
  highlightRGB?: string; // e.g. '6, 182, 212'
  /** Slate grid color triple */
  gridRGB?: string; // e.g. '30, 41, 59'
  /** Enable or disable target lock HUD boxes */
  enableHUDBoxes?: boolean;
  /** Custom className for the canvas container */
  className?: string;
}

interface Node {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  confidence: number;
  isLocked: boolean;
  lockTimer: number;
  pulsePhase: number;
}

const RAND_ID_CHARS = '0123456789ABCDEF';
const genNodeID = () => {
  let res = 'STAFF-#';
  for (let i = 0; i < 4; i++) res += RAND_ID_CHARS[Math.floor(Math.random() * RAND_ID_CHARS.length)];
  return res;
};

export default function LiveVisionWallpaper({
  nodeCount = 45,
  accentRGB = '16, 185, 129',   // Emerald-500
  highlightRGB = '6, 182, 212', // Cyan-500
  gridRGB = '30, 41, 59',      // Slate-800
  enableHUDBoxes = true,
  className = '',
}: LiveVisionWallpaperProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    /* ── Local Mutable State ───────────────────────────────────────── */
    let W = 0;
    let H = 0;
    let dpr = 1;
    let nodes: Node[] = [];
    const mouse = { x: -9999, y: -9999, active: false };
    let scanY = 0;
    const scanSpeed = 1.2;
    let rafId = 0;
    let lastTime = 0;
    let resizeTimer = 0;
    let autoLockTimer = 0;

    /* ── Screen Resize & DPI Scaling ───────────────────────────────── */
    const setCanvasDimensions = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    };

    /* ── Node Generator ────────────────────────────────────────────── */
    const initNodes = () => {
      const area = W * H;
      const refArea = 1920 * 1080;
      const count = Math.max(20, Math.round(nodeCount * Math.sqrt(area / refArea)));
      
      nodes = Array.from({ length: count }, () => ({
        id: genNodeID(),
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
    };

    /* ── Full Initialization ────────────────────────────────────────── */
    const setup = () => {
      setCanvasDimensions();
      initNodes();
    };

    /* ── Render: Spatial Grid & Radar Crosshairs ───────────────────── */
    const drawGrid = () => {
      const step = 60;
      ctx.strokeStyle = `rgba(${gridRGB}, 0.25)`;
      ctx.lineWidth = 1;

      // Vertical & Horizontal Grid Lines
      ctx.beginPath();
      for (let x = 0; x < W; x += step) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, H);
      }
      for (let y = 0; y < H; y += step) {
        ctx.moveTo(0, y);
        ctx.lineTo(W, y);
      }
      ctx.stroke();

      // Crosshair Markers at Grid Intersections (every 180px)
      const crossStep = 180;
      ctx.strokeStyle = `rgba(${gridRGB}, 0.55)`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = crossStep; x < W; x += crossStep) {
        for (let y = crossStep; y < H; y += crossStep) {
          ctx.moveTo(x - 4, y); ctx.lineTo(x + 4, y);
          ctx.moveTo(x, y - 4); ctx.lineTo(x, y + 4);
        }
      }
      ctx.stroke();
    };

    /* ── Render: Horizontal Radar Scanline Sweep ───────────────────── */
    const drawScanline = () => {
      scanY += scanSpeed;
      if (scanY > H + 60) scanY = -60;

      const gradient = ctx.createLinearGradient(0, scanY - 40, 0, scanY);
      gradient.addColorStop(0, 'rgba(16, 185, 129, 0)');
      gradient.addColorStop(0.85, 'rgba(16, 185, 129, 0.03)');
      gradient.addColorStop(1, 'rgba(6, 182, 212, 0.12)');

      ctx.fillStyle = gradient;
      ctx.fillRect(0, scanY - 40, W, 40);

      // Leading beam edge
      ctx.strokeStyle = `rgba(${highlightRGB}, 0.25)`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, scanY);
      ctx.lineTo(W, scanY);
      ctx.stroke();
    };

    /* ── Render: Node Mesh & Tracking Vectors ─────────────────────── */
    const drawMeshAndNodes = (dt: number) => {
      const maxDist = 135;
      const maxDistSq = maxDist * maxDist;

      // 1. Draw Mesh Connections
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
              ? `rgba(${accentRGB}, ${alpha * 1.5})`
              : `rgba(${gridRGB}, ${alpha})`;
            ctx.lineWidth = isHighPriority ? 1.2 : 0.8;
            ctx.beginPath();
            ctx.moveTo(n1.x, n1.y);
            ctx.lineTo(n2.x, n2.y);
            ctx.stroke();
          }
        }
      }

      // 2. Physics & Node Render
      const factor = dt / 16.67;
      nodes.forEach((n) => {
        // Position update
        n.x += n.vx * factor;
        n.y += n.vy * factor;

        // Screen wrap
        if (n.x < 0) n.x = W;
        if (n.x > W) n.x = 0;
        if (n.y < 0) n.y = H;
        if (n.y > H) n.y = 0;

        // Pulse animation
        n.pulsePhase += 0.03 * factor;
        const pulse = 1 + 0.3 * Math.sin(n.pulsePhase);

        // Check Cursor Lock (within 120px)
        const dxM = n.x - mouse.x;
        const dyM = n.y - mouse.y;
        const distM = Math.sqrt(dxM * dxM + dyM * dyM);
        const mouseLocked = mouse.active && distM < 120;

        if (mouseLocked) {
          n.isLocked = true;
          n.lockTimer = 60; // Keep locked briefly
        } else if (n.lockTimer > 0) {
          n.lockTimer -= 1 * factor;
          if (n.lockTimer <= 0) n.isLocked = false;
        }

        // Draw Node Point
        ctx.fillStyle = n.isLocked
          ? `rgba(${accentRGB}, 0.95)`
          : `rgba(${highlightRGB}, 0.65)`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * (n.isLocked ? 1.5 : 1), 0, Math.PI * 2);
        ctx.fill();

        // Pulsing Ring
        if (n.isLocked) {
          ctx.strokeStyle = `rgba(${accentRGB}, 0.4)`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r * 2.8 * pulse, 0, Math.PI * 2);
          ctx.stroke();
        }
      });
    };

    /* ── Render: Computer Vision Target Lock Wireframes [ + ] ──────── */
    const drawTargetHUDs = () => {
      if (!enableHUDBoxes) return;

      nodes.forEach((n) => {
        if (!n.isLocked) return;

        const size = 18;
        const x = n.x;
        const y = n.y;

        ctx.strokeStyle = `rgba(${accentRGB}, 0.85)`;
        ctx.lineWidth = 1.2;

        // Bracket Corners [ ┌ ┐ └ ┘ ]
        // Top-Left
        ctx.beginPath();
        ctx.moveTo(x - size, y - size + 6); ctx.lineTo(x - size, y - size); ctx.lineTo(x - size + 6, y - size);
        // Top-Right
        ctx.moveTo(x + size - 6, y - size); ctx.lineTo(x + size, y - size); ctx.lineTo(x + size, y - size + 6);
        // Bottom-Right
        ctx.moveTo(x + size, y + size - 6); ctx.lineTo(x + size, y + size); ctx.lineTo(x + size - 6, y + size);
        // Bottom-Left
        ctx.moveTo(x - size + 6, y + size); ctx.lineTo(x - size, y + size); ctx.lineTo(x - size, y + size - 6);
        ctx.stroke();

        // Center Crosshair +
        ctx.strokeStyle = `rgba(${highlightRGB}, 0.6)`;
        ctx.beginPath();
        ctx.moveTo(x - 3, y); ctx.lineTo(x + 3, y);
        ctx.moveTo(x, y - 3); ctx.lineTo(x, y + 3);
        ctx.stroke();

        // Data Label HUD Box
        ctx.font = '10px monospace';
        ctx.fillStyle = `rgba(${accentRGB}, 0.9)`;
        ctx.fillText(`[ ${n.id} ]`, x + size + 6, y - size + 8);
        
        ctx.fillStyle = 'rgba(148, 163, 184, 0.75)'; // Slate-400
        ctx.fillText(`CONF: ${n.confidence.toFixed(1)}%`, x + size + 6, y - size + 20);
      });

      // Draw vector line to cursor if mouse active
      if (mouse.active) {
        const lockedNode = nodes.find((n) => n.isLocked);
        if (lockedNode) {
          ctx.strokeStyle = `rgba(${highlightRGB}, 0.35)`;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(mouse.x, mouse.y);
          ctx.lineTo(lockedNode.x, lockedNode.y);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    };

    /* ── Periodic Auto Target Switch ───────────────────────────────── */
    const updateAutoLock = () => {
      autoLockTimer++;
      if (autoLockTimer % 180 === 0) { // Every ~3 seconds
        const randomIdx = Math.floor(Math.random() * nodes.length);
        nodes.forEach((n, idx) => {
          if (idx === randomIdx) {
            n.isLocked = true;
            n.lockTimer = 120;
          }
        });
      }
    };

    /* ── Main Animation Loop ───────────────────────────────────────── */
    const render = (time: number) => {
      rafId = requestAnimationFrame(render);

      // Tab Visibility Throttling (10 FPS when hidden)
      const targetFPS = document.hidden ? 10 : 60;
      const minInterval = 1000 / targetFPS;
      const dt = time - lastTime;
      if (dt < minInterval) return;
      lastTime = time;

      ctx.fillStyle = '#060913'; // Deep Surveillance Navy
      ctx.fillRect(0, 0, W, H);

      drawGrid();
      drawScanline();
      drawMeshAndNodes(dt);
      drawTargetHUDs();
      updateAutoLock();
    };

    /* ── Event Listeners (Passive & Cleaned Up) ────────────────────── */
    const handleMouseMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
    };

    const handleMouseLeave = () => {
      mouse.active = false;
      mouse.x = -9999;
      mouse.y = -9999;
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (e.touches.length > 0) {
        mouse.x = e.touches[0].clientX;
        mouse.y = e.touches[0].clientY;
        mouse.active = true;
      }
    };

    const handleResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        cancelAnimationFrame(rafId);
        setup();
        rafId = requestAnimationFrame(render);
      }, 150);
    };

    // Bootstrap
    setup();
    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    window.addEventListener('mouseleave', handleMouseLeave, { passive: true });
    window.addEventListener('touchmove', handleTouchMove, { passive: true });
    window.addEventListener('resize', handleResize);
    rafId = requestAnimationFrame(render);

    /* ── Cleanup Function (Prevent Memory Leaks) ───────────────────── */
    return () => {
      cancelAnimationFrame(rafId);
      clearTimeout(resizeTimer);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('resize', handleResize);
    };
  }, [nodeCount, accentRGB, highlightRGB, gridRGB, enableHUDBoxes]);

  return (
    <canvas
      ref={canvasRef}
      id="live-vision-wallpaper"
      aria-hidden="true"
      className={`fixed inset-0 -z-10 pointer-events-none w-full h-full block ${className}`}
    />
  );
}
