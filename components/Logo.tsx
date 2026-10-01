'use client';

/**
 * Logo.tsx — Enterprise Stafflytics AI Vision Brand Mark
 * ──────────────────────────────────────────────────────
 * Solution for Instant First Paint:
 * 1. Converted to a lightweight inline SVG React Component.
 * 2. Zero network waterfall request required (0ms load time).
 * 3. Explicit viewBox, width, and height eliminate Cumulative Layout Shift (CLS: 0).
 * 4. Includes glowing radar lens + vector typography matching Palantir/Verkada design.
 */

import React from 'react';

export interface LogoProps {
  className?: string;
  size?: number; // Icon box size in px
  showText?: boolean;
}

export default function Logo({ className = '', size = 36, showText = true }: LogoProps) {
  return (
    <div className={`inline-flex items-center gap-3 select-none ${className}`}>
      {/* ── High-Tech Radar Lens SVG Icon ───────────────────────────── */}
      <svg
        width={size}
        height={size}
        viewBox="0 0 40 40"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="flex-shrink-0 transform transition-transform duration-300 hover:scale-105"
        aria-label="Stafflytics AI Vision Logo"
      >
        {/* Outer Hex Shield / Ring */}
        <path
          d="M20 3L35 11.66V28.34L20 37L5 28.34V11.66L20 3Z"
          stroke="#1E293B"
          strokeWidth="2"
          fill="#0B0F17"
        />
        
        {/* Glowing Radar Concentric Circle */}
        <circle cx="20" cy="20" r="11" stroke="#06B6D4" strokeWidth="1.5" strokeOpacity="0.6" />
        <circle cx="20" cy="20" r="6" stroke="#10B981" strokeWidth="1.5" strokeDasharray="3 3" />
        
        {/* Center Vision Aperture Dot */}
        <circle cx="20" cy="20" r="2.5" fill="#10B981" />

        {/* Crosshair Target Reticle Lines */}
        <line x1="20" y1="5" x2="20" y2="10" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="20" y1="30" x2="20" y2="35" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="5" y1="20" x2="10" y2="20" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="30" y1="20" x2="35" y2="20" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
      </svg>

      {/* ── Brand Typography ────────────────────────────────────────── */}
      {showText && (
        <div className="flex flex-col leading-none">
          <div className="flex items-center gap-1.5">
            <span className="font-extrabold tracking-tight text-white text-base font-sans">
              STAFFLYTICS
            </span>
            <span className="px-1.5 py-0.5 text-[10px] font-mono font-bold tracking-widest text-emerald-400 bg-emerald-950/70 border border-emerald-500/30 rounded">
              VISION
            </span>
          </div>
          <span className="text-[10px] font-mono tracking-widest text-slate-400 uppercase mt-0.5">
            AI Operations Console
          </span>
        </div>
      )}
    </div>
  );
}
