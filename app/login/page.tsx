'use client';

/**
 * app/login/page.tsx — Executive Command Center Login & Splash
 * ─────────────────────────────────────────────────────────────
 * Designed for Stafflytics AI (Linear, Vercel & Palantir Gotham style).
 *
 * Features:
 * - Instant logo preloading with explicit dimensions (0ms CLS)
 * - Splash sync loader phase with breathing scale animation & progress bar
 * - Glassmorphism login card with translucent inputs & emerald glow button
 * - Password visibility toggle
 */

import React, { useState, useEffect } from 'react';
import VisionTrackingWallpaper from '@/components/VisionTrackingWallpaper';
import Logo from '@/components/Logo';
import { Eye, EyeOff, ShieldCheck, ArrowRight, Lock, User } from 'lucide-react';

export default function LoginPage() {
  const [showSplash, setShowSplash] = useState<boolean>(true);
  const [syncProgress, setSyncProgress] = useState<number>(0);
  const [showPassword, setShowPassword] = useState<boolean>(false);
  const [username, setUsername] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Simulated AI Models Sync Loader (Splash Screen)
  useEffect(() => {
    if (!showSplash) return;
    const interval = setInterval(() => {
      setSyncProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setTimeout(() => setShowSplash(false), 400);
          return 100;
        }
        return prev + 25;
      });
    }, 300);

    return () => clearInterval(interval);
  }, [showSplash]);

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage('');

    // Simulate authentication check
    setTimeout(() => {
      if (username === 'admin' || username === 'owner_admin' || username === 'minhajasghar' || username === '') {
        window.location.href = '/dashboard';
      } else {
        setErrorMessage('Invalid master security credentials.');
        setIsLoading(false);
      }
    }, 800);
  };

  return (
    <div className="relative min-h-screen bg-[#090D16] text-slate-100 font-sans flex items-center justify-center p-4 overflow-hidden select-none">
      {/* ── Background Vision Wallpaper Layer ──────────────────────────── */}
      <VisionTrackingWallpaper targetCount={8} />

      {/* ── Glowing Ambient Radial Backdrop Gradient ───────────────────── */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-emerald-500/10 rounded-full blur-[140px] pointer-events-none"></div>

      {/* ── SPLASH SCREEN PHASE ────────────────────────────────────────── */}
      {showSplash ? (
        <div className="flex flex-col items-center justify-center text-center space-y-6 z-20 animate-fadeIn">
          {/* Logo with Breathing Pulse */}
          <div className="relative flex items-center justify-center">
            <div className="absolute inset-0 rounded-full bg-emerald-500/20 blur-xl animate-pulse"></div>
            <Logo size={72} showText={false} />
          </div>

          <div className="space-y-1">
            <h1 className="text-2xl font-extrabold tracking-tight text-white">STAFFLYTICS AI</h1>
            <p className="text-xs font-mono text-emerald-400 tracking-widest uppercase">
              ENTERPRISE VISION OPS CENTER
            </p>
          </div>

          {/* Sync Progress Bar */}
          <div className="w-64 space-y-2">
            <div className="w-full bg-slate-950/80 rounded-full h-1.5 overflow-hidden border border-slate-800">
              <div
                className="bg-emerald-500 h-full rounded-full transition-all duration-300 ease-out"
                style={{ width: `${syncProgress}%` }}
              ></div>
            </div>
            <p className="text-[11px] font-mono text-slate-400">
              Synchronizing AI Models & Hardware... ({syncProgress}%)
            </p>
          </div>

          <button
            onClick={() => setShowSplash(false)}
            className="text-xs font-mono text-slate-500 hover:text-slate-300 underline pt-4 transition-colors"
          >
            Skip Initialization
          </button>
        </div>
      ) : (
        /* ── EXECUTIVE LOGIN CARD PHASE ────────────────────────────────── */
        <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-2xl border border-slate-800/80 shadow-2xl rounded-3xl p-8 space-y-6 z-20 transition-all duration-500 animate-slideUp">
          
          {/* Header & Logo */}
          <div className="flex flex-col items-center text-center space-y-3">
            <Logo size={48} showText={false} />
            <div>
              <h2 className="text-xl font-extrabold text-white tracking-tight">Stafflytics Command Center</h2>
              <p className="text-xs font-mono text-emerald-400 tracking-wider mt-0.5">
                SECURE AUTHENTICATION • LEVEL-04
              </p>
            </div>
          </div>

          {/* Login Form */}
          <form onSubmit={handleLoginSubmit} className="space-y-4">
            
            {/* Username Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-mono font-semibold text-slate-400 tracking-wider uppercase">
                Username / Operator ID
              </label>
              <div className="relative">
                <User className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="owner_admin"
                  required
                  className="w-full bg-slate-950/60 border border-slate-800 text-slate-100 placeholder:text-slate-600 rounded-xl pl-10 pr-4 py-3 text-sm font-sans focus:outline-none focus:border-emerald-500/80 focus:ring-1 focus:ring-emerald-500/80 transition-all"
                />
              </div>
            </div>

            {/* Password Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-mono font-semibold text-slate-400 tracking-wider uppercase">
                Master Security Password
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  required
                  className="w-full bg-slate-950/60 border border-slate-800 text-slate-100 placeholder:text-slate-600 rounded-xl pl-10 pr-11 py-3 text-sm font-sans focus:outline-none focus:border-emerald-500/80 focus:ring-1 focus:ring-emerald-500/80 transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Error Message */}
            {errorMessage && (
              <p className="text-xs font-mono text-rose-400 bg-rose-950/60 border border-rose-500/30 p-2.5 rounded-lg text-center">
                {errorMessage}
              </p>
            )}

            {/* Action Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3.5 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-mono font-bold text-sm tracking-wider uppercase shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 transition-all flex items-center justify-center gap-2 group active:scale-[0.99] disabled:opacity-50"
            >
              {isLoading ? (
                <span>AUTHORIZING ACCESS...</span>
              ) : (
                <>
                  <span>AUTHORIZE COMMAND ACCESS</span>
                  <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                </>
              )}
            </button>
          </form>

          {/* Footer Security Badge */}
          <div className="pt-2 border-t border-slate-800/80 text-center">
            <p className="text-[10px] font-mono text-slate-500 flex items-center justify-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>© 2026 STAFFLYTICS ANALYTICS INTELLIGENCE</span>
            </p>
          </div>

        </div>
      )}
    </div>
  );
}
