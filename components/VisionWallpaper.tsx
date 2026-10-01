'use client';

/**
 * VisionWallpaper.tsx — Command Center Ambient Live Background
 * ─────────────────────────────────────────────────────────────
 * Executive dark-mode Canvas 2D engine inspired by Palantir Gotham & Linear.
 *
 * Features:
 * - Subtle 2D Spatial Coordinate Grid with slow ambient drift
 * - Interactive Floating Tracking Nodes with cursor repulsion
 * - Occasional Computer Vision Bounding Wireframes [ + ] that dissolve
 * - Tab visibility throttling (10 FPS when document.hidden)
 * - High-DPI (Retina) scaling & clean useEffect unmount cleanup
 * - Zero external dependencies — pure Canvas 2D
 */

import React, { useEffect, useRef } from 'react';

export interface VisionWallpaperProps {
  nodeCount?: number;
  gridColor?: string;     // RGB triple e.g. '30, 41, 59'
  emeraldColor?: string;  // RGB triple e.g. '16, 185, 129'
  cyanColor?: string;     // RGB triple e.g. '6, 182, 212'
  className?: string;
}

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  opacity: number;
}

interface CVTarget {
  id: string;
  x: number;
  y: number;
  size: number;
  opacity: number;
  life: number;
  maxLife: number;
  confidence: number;
}

export default function VisionWallpaper({
  nodeCount = 50,
  gridColor = '30, 41, 59',       // Slate-800
  emeraldColor = '16, 185, 129',  // Emerald-500
  cyanColor = '6, 182, 212',     // Cyan-500
  className = '',
}: VisionWallpaperProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    /* ── Local State ─────────────────────────────────────────────────── */
    let W = 0, H = 0, dpr = 1;
    let nodes: Node[] = [];
    let targets: CVTarget[] = [];
    const mouse = { x: -9999, y: -9999, active: false };
    let gridOffset = { x: 0, y: 0 };
    let rafId = 0;
    let lastTime = 0;
    let resizeTimer = 0;
    let targetSpawnTimer = 0;

    /* ── Canvas Sizing ───────────────────────────────────────────────── */
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

    /* ── Node Initialization ─────────────────────────────────────────── */
    const initNodes = () => {
      const area = W * H;
      const count = Math.max(25, Math.round(nodeCount * Math.sqrt(area / (1920 * 1080))));
      nodes = Array.from({ length: count }, () => {
        const angle = Math.random() * Math.PI * 2;
        const speed = 0.1 + Math.random() * 0.3;
        return {
          x: Math.random() * W,
          y: Math.random() * H,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          r: 1.5 + Math.random() * 1.5,
          opacity: 0.2 + Math.random() * 0.5,
        };
      });
    };

    const setup = () => {
      setDimensions();
      initNodes();
    };

    /* ── Spawn Random CV Bounding Wireframes ─────────────────────────── */
    const spawnTarget = () => {
      const idStr = Math.floor(1000 + Math.random() * 9000).toString();
      targets.push({
        id: `TARGET-#${idStr}`,
        x: 100 + Math.random() * (W - 200),
        y: 100 + Math.random() * (H - 200),
        size: 24 + Math.random() * 16,
        opacity: 0,
        life: 0,
        maxLife: 140 + Math.random() * 80,
        confidence: 94 + Math.random() * 5.8,
      });
    };

    /* ── Render: Ambient Spatial Grid ───────────────────────────────── */
    const drawGrid = () => {
      gridOffset.x = (gridOffset.x + 0.15) % 60;
      gridOffset.y = (gridOffset.y + 0.1) % 60;

      const step = 60;
      ctx.strokeStyle = `rgba(${gridColor}, 0.18)`;
      ctx.lineWidth = 1;

      ctx.beginPath();
      for (let x = (gridOffset.x % step) - step; x < W; x += step) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, H);
      }
      for (let y = (gridOffset.y % step) - step; y < H; y += step) {
        ctx.moveTo(0, y);
        ctx.lineTo(W, y);
      }
      ctx.stroke();

      // Subtle Grid Intersections
      ctx.strokeStyle = `rgba(${gridColor}, 0.45)`;
      ctx.beginPath();
      for (let x = 180; x < W; x += 180) {
        for (let y = 180; y < H; y += 180) {
          ctx.moveTo(x - 3, y); ctx.lineTo(x + 3, y);
          ctx.moveTo(x, y - 3); ctx.lineTo(x, y + 3);
        }
      }
      ctx.stroke();
    };

    /* ── Render: Floating Nodes & Proximity Mesh ─────────────────────── */
    const drawNodesAndMesh = (dt: number) => {
      const factor = dt / 16.67;
      const maxDist = 130;
      const maxDistSq = maxDist * maxDist;

      // Draw Proximity Connections
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dSq = dx * dx + dy * dy;
          if (dSq < maxDistSq) {
            const alpha = (1 - dSq / maxDistSq) * 0.22;
            ctx.strokeStyle = `rgba(${gridColor}, ${alpha})`;
            ctx.lineWidth = 0.8;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      // Physics & Render Nodes
      nodes.forEach((n) => {
        n.x += n.vx * factor;
        n.y += n.vy * factor;

        if (n.x < 0) n.x = W;
        if (n.x > W) n.x = 0;
        if (n.y < 0) n.y = H;
        if (n.y > H) n.y = 0;

        // Gentle Cursor Repulsion
        if (mouse.active) {
          const dx = n.x - mouse.x;
          const dy = n.y - mouse.y;
          const distSq = dx * dx + dy * dy;
          if (distSq < 110 * 110 && distSq > 0) {
            const dist = Math.sqrt(distSq);
            const force = (1 - dist / 110) * 0.8;
            n.x += (dx / dist) * force * factor;
            n.y += (dy / dist) * force * factor;
          }
        }

        ctx.fillStyle = `rgba(${emeraldColor}, ${n.opacity * 0.8})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();
      });
    };

    /* ── Render: Animated CV Bounding Wireframes [ + ] ──────────────── */
    const drawTargets = (dt: number) => {
      const factor = dt / 16.67;

      targets.forEach((t, idx) => {
        t.life += factor;

        // Fade in & Fade out envelope
        if (t.life < 20) {
          t.opacity = t.life / 20;
        } else if (t.life > t.maxLife - 25) {
          t.opacity = (t.maxLife - t.life) / 25;
        } else {
          t.opacity = 1;
        }

        if (t.opacity < 0) t.opacity = 0;

        const size = t.size;
        const x = t.x;
        const y = t.y;

        ctx.strokeStyle = `rgba(${emeraldColor}, ${t.opacity * 0.75})`;
        ctx.lineWidth = 1.2;

        // Bracket Corners [ ┌ ┐ └ ┘ ]
        ctx.beginPath();
        // Top-Left
        ctx.moveTo(x - size, y - size + 6); ctx.lineTo(x - size, y - size); ctx.lineTo(x - size + 6, y - size);
        // Top-Right
        ctx.moveTo(x + size - 6, y - size); ctx.lineTo(x + size, y - size); ctx.lineTo(x + size, y - size + 6);
        // Bottom-Right
        ctx.moveTo(x + size, y + size - 6); ctx.lineTo(x + size, y + size); ctx.lineTo(x + size - 6, y + size);
        // Bottom-Left
        ctx.moveTo(x - size + 6, y + size); ctx.lineTo(x - size, y + size); ctx.lineTo(x - size, y + size - 6);
        ctx.stroke();

        // Center Reticle +
        ctx.strokeStyle = `rgba(${cyanColor}, ${t.opacity * 0.6})`;
        ctx.beginPath();
        ctx.moveTo(x - 3, y); ctx.lineTo(x + 3, y);
        ctx.moveTo(x, y - 3); ctx.lineTo(x, y + 3);
        ctx.stroke();

        // HUD Text Label
        ctx.font = '10px monospace';
        ctx.fillStyle = `rgba(${emeraldColor}, ${t.opacity * 0.85})`;
        ctx.fillText(`[ ${t.id} ]`, x + size + 6, y - size + 8);
        ctx.fillStyle = `rgba(148, 163, 184, ${t.opacity * 0.7})`;
        ctx.fillText(`CONF: ${t.confidence.toFixed(1)}%`, x + size + 6, y - size + 20);
      });

      // Filter out expired targets
      targets = targets.filter((t) => t.life < t.maxLife);
    };

    /* ── Main Loop ───────────────────────────────────────────────────── */
    const render = (time: number) => {
      rafId = requestAnimationFrame(render);

      const targetFPS = document.hidden ? 10 : 60;
      const minInterval = 1000 / targetFPS;
      const dt = time - lastTime;
      if (dt < minInterval) return;
      lastTime = time;

      ctx.fillStyle = '#090D16'; // Deep Obsidian Base
      ctx.fillRect(0, 0, W, H);

      drawGrid();
      drawNodesAndMesh(dt);
      drawTargets(dt);

      // Spawn target wireframes every ~3.5 seconds
      targetSpawnTimer++;
      if (targetSpawnTimer % 210 === 0) {
        if (targets.length < 3) spawnTarget();
      }
    };

    /* ── Event Handlers ──────────────────────────────────────────────── */
    const handleMouseMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
    };

    const handleMouseLeave = () => {
      mouse.active = false;
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
  }, [nodeCount, gridColor, emeraldColor, cyanColor]);

  return (
    <canvas
      ref={canvasRef}
      id="vision-wallpaper"
      aria-hidden="true"
      className={`fixed inset-0 -z-10 pointer-events-none w-full h-full block ${className}`}
    />
  );
}
