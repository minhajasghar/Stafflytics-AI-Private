'use client';

/**
 * VisionTrackingWallpaper.tsx — Multi-Agent AI Vision Tracking Engine
 * ───────────────────────────────────────────────────────────────────
 * High-performance HTML5 Canvas 2D background inspired by Linear, Vercel & Palantir Gotham.
 *
 * Features:
 * - 6 to 12 Continuous Staff Tracking Entities drifting with breadcrumb trails
 * - Detection Reticles with 4 Corner Brackets [ ┌ ┐ └ ┘ ] & Center Anchor Dot
 * - Dynamic Telemetry Micro-Text (Staff ID, fluctuating Confidence %, Zone Tag)
 * - Proximity Vector Mesh lines when targets approach within 160px
 * - Mouse cursor magnetic reticle lock
 * - Hi-DPI (Retina) devicePixelRatio scaling & tab visibility throttling
 * - Zero dependencies — pure Canvas 2D engine
 */

import React, { useEffect, useRef } from 'react';

export interface VisionTrackingWallpaperProps {
  /** Target entity count (6 to 12) */
  targetCount?: number;
  /** Primary accent color triple (emerald) */
  emeraldRGB?: string; // e.g. '16, 185, 129'
  /** Secondary accent color triple (cyan) */
  cyanRGB?: string;    // e.g. '6, 182, 212'
  /** Grid tick color triple (slate) */
  gridRGB?: string;    // e.g. '30, 41, 59'
  className?: string;
}

interface StaffTarget {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  baseConfidence: number;
  confidence: number;
  zone: string;
  history: { x: number; y: number }[];
  size: number;
  opacity: number;
  life: number;
  maxLife: number;
  pulsePhase: number;
  isCursorTarget?: boolean;
}

const ZONES = ['[LOBBY]', '[CORRIDOR]', '[WORKSTATION]', '[SERVER ROOM]', '[EXECUTIVE]'];
const HEX_CHARS = '0123456789ABCDEF';

const genHexID = () => {
  let res = 'STAFF #';
  for (let i = 0; i < 4; i++) res += HEX_CHARS[Math.floor(Math.random() * HEX_CHARS.length)];
  return res;
};

export default function VisionTrackingWallpaper({
  targetCount = 8,
  emeraldRGB = '16, 185, 129',
  cyanRGB = '6, 182, 212',
  gridRGB = '30, 41, 59',
  className = '',
}: VisionTrackingWallpaperProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    /* ── Local Mutable State ─────────────────────────────────────────── */
    let W = 0, H = 0, dpr = 1;
    let targets: StaffTarget[] = [];
    const mouse = { x: -9999, y: -9999, active: false };
    let rafId = 0;
    let lastTime = 0;
    let resizeTimer = 0;

    /* ── Canvas Sizing & Retina Resolution ───────────────────────────── */
    const setDimensions = () => {
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

    /* ── Target Factory ──────────────────────────────────────────────── */
    const createTarget = (isCursor = false): StaffTarget => {
      const angle = Math.random() * Math.PI * 2;
      const speed = 0.2 + Math.random() * 0.4;
      const baseConf = 96.0 + Math.random() * 3.8;
      return {
        id: genHexID(),
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
        maxLife: 600 + Math.random() * 400, // 15–20s lifecycle
        pulsePhase: Math.random() * Math.PI * 2,
        isCursorTarget: isCursor,
      };
    };

    const initTargets = () => {
      targets = Array.from({ length: targetCount }, (_, i) => createTarget(i === 0));
    };

    const setup = () => {
      setDimensions();
      initTargets();
    };

    /* ── Render: Coordinate Ticks + Grid Overlay ─────────────────────── */
    const drawGridTicks = () => {
      const step = 100;
      ctx.strokeStyle = `rgba(${gridRGB}, 0.35)`;
      ctx.lineWidth = 1;

      ctx.beginPath();
      for (let x = step; x < W; x += step) {
        for (let y = step; y < H; y += step) {
          ctx.moveTo(x - 3, y); ctx.lineTo(x + 3, y);
          ctx.moveTo(x, y - 3); ctx.lineTo(x, y + 3);
        }
      }
      ctx.stroke();
    };

    /* ── Render: Proximity Mesh Connections ─────────────────────────── */
    const drawMesh = () => {
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
            ctx.strokeStyle = `rgba(${cyanRGB}, ${alpha})`;
            ctx.lineWidth = 0.8;
            ctx.beginPath();
            ctx.moveTo(t1.x, t1.y);
            ctx.lineTo(t2.x, t2.y);
            ctx.stroke();
          }
        }
      }
    };

    /* ── Render: Staff Target Reticles & Micro Telemetry Tags ───────── */
    const updateAndDrawTargets = (dt: number) => {
      const factor = dt / 16.67;

      targets.forEach((t) => {
        // Lifecycle Update
        t.life += factor;
        const fadeInTime = 40;
        const fadeOutTime = 50;

        if (t.life < fadeInTime) {
          t.opacity = t.life / fadeInTime;
        } else if (t.life > t.maxLife - fadeOutTime) {
          t.opacity = Math.max(0, (t.maxLife - t.life) / fadeOutTime);
        } else {
          t.opacity = 1;
        }

        // Re-seed if completed lifecycle
        if (t.life >= t.maxLife) {
          Object.assign(t, createTarget(t.isCursorTarget));
          t.opacity = 0;
        }

        // Motion Update
        if (t.isCursorTarget && mouse.active) {
          // Magnetically glide toward user cursor
          t.x += (mouse.x - t.x) * 0.08 * factor;
          t.y += (mouse.y - t.y) * 0.08 * factor;
        } else {
          t.x += t.vx * factor;
          t.y += t.vy * factor;

          // Screen Wrap with smooth padding
          const pad = 40;
          if (t.x < -pad) t.x = W + pad;
          if (t.x > W + pad) t.x = -pad;
          if (t.y < -pad) t.y = H + pad;
          if (t.y > H + pad) t.y = -pad;
        }

        // Fluctuating Confidence Rating (±0.2%)
        t.confidence = Math.min(99.9, Math.max(96.0, t.baseConfidence + (Math.random() - 0.5) * 0.35));

        // Breadcrumb History Traill
        t.history.push({ x: t.x, y: t.y });
        if (t.history.length > 8) t.history.shift();

        const opacity = t.opacity * 0.85;
        if (opacity <= 0.01) return;

        // 1. Draw Breadcrumb Trail Points
        if (t.history.length > 1) {
          ctx.strokeStyle = `rgba(${emeraldRGB}, ${opacity * 0.2})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(t.history[0].x, t.history[0].y);
          for (let k = 1; k < t.history.length; k++) {
            ctx.lineTo(t.history[k].x, t.history[k].y);
          }
          ctx.stroke();
        }

        // 2. Center Anchor Dot & Pulse Ring
        t.pulsePhase += 0.04 * factor;
        const pulse = 1 + 0.25 * Math.sin(t.pulsePhase);

        ctx.fillStyle = `rgba(${emeraldRGB}, ${opacity})`;
        ctx.beginPath();
        ctx.arc(t.x, t.y, 2, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = `rgba(${emeraldRGB}, ${opacity * 0.35})`;
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.arc(t.x, t.y, 6 * pulse, 0, Math.PI * 2);
        ctx.stroke();

        // 3. Corner Brackets Reticle [ ┌ ┐ └ ┘ ]
        const s = t.size;
        const x = t.x;
        const y = t.y;

        ctx.strokeStyle = `rgba(${emeraldRGB}, ${opacity * 0.9})`;
        ctx.lineWidth = 1.2;

        ctx.beginPath();
        // Top-Left ┌
        ctx.moveTo(x - s, y - s + 5); ctx.lineTo(x - s, y - s); ctx.lineTo(x - s + 5, y - s);
        // Top-Right ┐
        ctx.moveTo(x + s - 5, y - s); ctx.lineTo(x + s, y - s); ctx.lineTo(x + s, y - s + 5);
        // Bottom-Right ┘
        ctx.moveTo(x + s, y + s - 5); ctx.lineTo(x + s, y + s); ctx.lineTo(x + s - 5, y + s);
        // Bottom-Left └
        ctx.moveTo(x - s + 5, y + s); ctx.lineTo(x - s, y + s); ctx.lineTo(x - s, y + s - 5);
        ctx.stroke();

        // 4. Telemetry Micro-Text Tag (Monospace)
        const labelX = x + s + 6;
        const labelY = y - s + 8;

        ctx.font = '10px monospace';
        ctx.fillStyle = `rgba(${emeraldRGB}, ${opacity})`;
        ctx.fillText(t.id, labelX, labelY);

        ctx.fillStyle = `rgba(148, 163, 184, ${opacity * 0.75})`; // Slate-400
        ctx.fillText(`CONF: ${t.confidence.toFixed(1)}%`, labelX, labelY + 11);
        ctx.fillText(t.zone, labelX, labelY + 22);
      });
    };

    /* ── Main Loop ───────────────────────────────────────────────────── */
    const render = (time: number) => {
      rafId = requestAnimationFrame(render);

      const targetFPS = document.hidden ? 10 : 60;
      const minInterval = 1000 / targetFPS;
      const dt = time - lastTime;
      if (dt < minInterval) return;
      lastTime = time;

      ctx.fillStyle = '#090D16'; // Obsidian Command Center Canvas
      ctx.fillRect(0, 0, W, H);

      drawGridTicks();
      drawMesh();
      updateAndDrawTargets(dt);
    };

    /* ── Event Handlers ──────────────────────────────────────────────── */
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

    setup();
    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    window.addEventListener('mouseleave', handleMouseLeave, { passive: true });
    window.addEventListener('touchmove', handleTouchMove, { passive: true });
    window.addEventListener('resize', handleResize);
    rafId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(rafId);
      clearTimeout(resizeTimer);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('resize', handleResize);
    };
  }, [targetCount, emeraldRGB, cyanRGB, gridRGB]);

  return (
    <canvas
      ref={canvasRef}
      id="vision-tracking-wallpaper"
      aria-hidden="true"
      className={`fixed inset-0 -z-10 pointer-events-none w-full h-full block ${className}`}
    />
  );
}
