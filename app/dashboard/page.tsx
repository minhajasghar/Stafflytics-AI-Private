'use client';

/**
 * app/dashboard/page.tsx — Executive Command Center Dashboard
 * ─────────────────────────────────────────────────────────────
 * Designed for Stafflytics AI (Linear, Vercel & Palantir Gotham style).
 *
 * Features:
 * - Unified dark obsidian theme (#090D16 base, glassmorphic slate panels)
 * - Monochrome sidebar navigation with active indicator bar
 * - Top bar breadcrumbs, monospace clock, 24ms latency badge, and pulsing status dot
 * - CCTV Standby Signal State with scanlines & "Re-establish Handshake" button
 * - Floating glass pill controls bar inside camera viewport
 * - Structured Active Tracker Gauge card & clean Today's Roster feed
 * - Embedded VisionWallpaper background
 */

import React, { useState, useEffect } from 'react';
import VisionWallpaper from '@/components/VisionWallpaper';
import Logo from '@/components/Logo';
import {
  Monitor,
  BarChart3,
  Users,
  FileText,
  Zap,
  CalendarCheck,
  Settings,
  Moon,
  LogOut,
  Clock,
  Camera,
  RefreshCw,
  Maximize2,
  SlidersHorizontal,
  WifiOff,
  ChevronUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  UserCheck,
  ShieldAlert,
  Search,
  Bell,
  Plus,
} from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════════════
   Mock Roster & Staff Data
═══════════════════════════════════════════════════════════════════════════ */
interface StaffMember {
  id: string;
  name: string;
  role: string;
  avatar: string;
  status: 'ACTIVE' | 'BREAK' | 'OFFLINE';
  shift: string;
  shiftTime: string;
  efficiency: number;
}

const MOCK_ROSTER: StaffMember[] = [
  {
    id: '#4092',
    name: 'Alex Rivera',
    role: 'Lead Vision Engineer',
    avatar: 'AR',
    status: 'ACTIVE',
    shift: 'Morning',
    shiftTime: '10:00 AM',
    efficiency: 98.4,
  },
  {
    id: '#1804',
    name: 'Sarah Chen',
    role: 'Product Ops Specialist',
    avatar: 'SC',
    status: 'ACTIVE',
    shift: 'Morning',
    shiftTime: '10:00 AM',
    efficiency: 96.1,
  },
  {
    id: '#8821',
    name: 'Marcus Vance',
    role: 'Executive Architect',
    avatar: 'MV',
    status: 'BREAK',
    shift: 'Morning',
    shiftTime: '10:30 AM',
    efficiency: 94.8,
  },
  {
    id: '#3041',
    name: 'Elena Rostova',
    role: 'Data Scientist',
    avatar: 'ER',
    status: 'ACTIVE',
    shift: 'Evening',
    shiftTime: '02:00 PM',
    efficiency: 99.1,
  },
];

export default function DashboardPage() {
  const [timeString, setTimeString] = useState<string>('');
  const [activeTab, setActiveTab] = useState<string>('Monitor');
  const [camSignalOnline, setCamSignalOnline] = useState<boolean>(true);
  const [isConnecting, setIsConnecting] = useState<boolean>(false);
  const [ptzMessage, setPtzMessage] = useState<string | null>(null);

  // Ticking Clock
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeString(
        now.toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        }) + ' UTC+05:00'
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleReconnect = () => {
    setIsConnecting(true);
    setTimeout(() => {
      setIsConnecting(false);
      setCamSignalOnline(true);
    }, 1200);
  };

  const triggerPTZ = (dir: string) => {
    setPtzMessage(`PTZ Vector: ${dir}`);
    setTimeout(() => setPtzMessage(null), 1500);
  };

  return (
    <div className="relative min-h-screen bg-[#090D16] text-slate-100 font-sans antialiased overflow-x-hidden flex">
      {/* ── Background Vision Wallpaper ───────────────────────────── */}
      <VisionWallpaper />

      {/* ── 1. UNIFIED MONOCHROME SIDEBAR NAVIGATION ──────────────────── */}
      <aside className="w-16 lg:w-20 bg-slate-950/80 backdrop-blur-2xl border-r border-slate-800/80 flex flex-col items-center py-5 flex-shrink-0 z-30 justify-between">
        
        {/* Brand Aperture Logo Icon */}
        <div className="w-10 h-10 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-center shadow-lg">
          <Logo size={24} showText={false} />
        </div>

        {/* Sidebar Nav Icons (Monochrome Slate Theme) */}
        <nav className="flex flex-col gap-3 w-full px-2 my-auto">
          {[
            { id: 'Monitor', icon: Monitor, label: 'Live Stream' },
            { id: 'Analytics', icon: BarChart3, label: 'Analytics' },
            { id: 'Staff', icon: Users, label: 'Staff Directory' },
            { id: 'Reporting', icon: FileText, label: 'Reports' },
            { id: 'Performance', icon: Zap, label: 'Performance' },
            { id: 'Shift', icon: CalendarCheck, label: 'Shift Optimizer' },
            { id: 'Settings', icon: Settings, label: 'Settings' },
          ].map((item) => {
            const IconComponent = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                title={item.label}
                className={`relative w-full aspect-square rounded-xl flex items-center justify-center transition-all group ${
                  isActive
                    ? 'bg-slate-800/90 text-emerald-400 border border-slate-700/60 shadow-lg shadow-emerald-950/20'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-900/60 border border-transparent'
                }`}
              >
                {/* Active Left Indicator Bar */}
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-1 bg-emerald-500 rounded-r"></span>
                )}
                <IconComponent className="w-5 h-5" />
              </button>
            );
          })}
        </nav>

        {/* Bottom System Action Icons */}
        <div className="flex flex-col gap-2 w-full px-2">
          <button
            title="Toggle Theme"
            className="w-full aspect-square rounded-xl flex items-center justify-center text-emerald-400 hover:bg-slate-900/60 border border-transparent transition-all"
          >
            <Moon className="w-4 h-4" />
          </button>
          <button
            title="Logout"
            onClick={() => (window.location.href = '/login')}
            className="w-full aspect-square rounded-xl flex items-center justify-center text-rose-400 hover:bg-rose-950/40 border border-transparent transition-all"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </aside>

      {/* ── MAIN SHELL CONTENT ────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen">
        
        {/* ── 2. TOP HEADER BAR ───────────────────────────────────────── */}
        <header className="h-16 bg-slate-950/70 backdrop-blur-xl border-b border-slate-800/80 px-6 flex items-center justify-between gap-4 z-20 sticky top-0">
          
          {/* Left: Breadcrumbs */}
          <div className="flex items-center gap-3">
            <span className="text-sm font-extrabold tracking-tight text-white">Stafflytics</span>
            <span className="text-slate-600 font-mono">/</span>
            <span className="text-xs font-mono font-semibold text-emerald-400 uppercase tracking-wider">
              Intelligence Stream
            </span>
          </div>

          {/* Right Header Status Bar */}
          <div className="flex items-center gap-4">
            
            {/* Live Camera Latency Badge */}
            <div className="hidden sm:flex items-center gap-2 bg-slate-900/80 border border-slate-800 px-3 py-1 rounded-lg text-xs font-mono text-slate-300">
              <span className="text-emerald-400 font-bold">24ms</span>
              <span className="text-slate-700">|</span>
              <span>1080p60 AI</span>
            </div>

            {/* Monospace Live Clock */}
            <div className="hidden md:flex items-center gap-1.5 text-xs font-mono text-slate-400 bg-slate-900/80 border border-slate-800 px-3 py-1 rounded-lg">
              <Clock className="w-3.5 h-3.5 text-cyan-400" />
              <span>{timeString || '15:56:45 UTC+05:00'}</span>
            </div>

            {/* Pulsing System Status Indicator */}
            <div className="flex items-center gap-2 bg-slate-900/80 border border-slate-800/90 px-3 py-1 rounded-full text-xs font-mono">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
              </span>
              <span className="text-emerald-400 font-bold hidden sm:inline">System Live</span>
            </div>

            {/* Operator Avatar */}
            <div className="w-8 h-8 rounded-lg bg-emerald-950 border border-emerald-500/40 flex items-center justify-center font-mono font-bold text-xs text-emerald-400">
              OP
            </div>
          </div>
        </header>

        {/* ── DASHBOARD WORKSPACE BODY ─────────────────────────────────── */}
        <main className="flex-1 p-6 max-w-[1800px] w-full mx-auto grid grid-cols-1 xl:grid-cols-4 gap-6">
          
          {/* ── LEFT 3 COLS: MAIN STREAM & STATS BAR ───────────────────── */}
          <div className="xl:col-span-3 space-y-6">
            
            {/* ── 3. MAIN STREAM VIEWPORT ─────────────────────────────── */}
            <section className="bg-slate-950 border border-slate-800/90 rounded-3xl overflow-hidden shadow-2xl relative aspect-video flex flex-col group">
              
              {/* Viewport Top Info Header */}
              <div className="bg-slate-950/80 backdrop-blur-md px-5 py-3 border-b border-slate-800/80 flex items-center justify-between text-xs font-mono z-10">
                <div className="flex items-center gap-3">
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${
                      camSignalOnline ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500 animate-ping'
                    }`}
                  ></span>
                  <span className="font-bold text-white tracking-wide">CAM 01 — MAIN ENTRANCE</span>
                  <span className="text-slate-700">|</span>
                  <span className="text-slate-400">Building A • Ground Floor</span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCamSignalOnline(!camSignalOnline)}
                    className="text-[11px] font-mono px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-300 hover:text-white transition-all"
                  >
                    Simulate: {camSignalOnline ? 'Offline' : 'Online'}
                  </button>
                </div>
              </div>

              {/* Viewport Content Area */}
              <div className="relative flex-1 flex items-center justify-center overflow-hidden bg-[#060912]">
                
                {camSignalOnline ? (
                  /* Live Camera Stream Simulation */
                  <div className="w-full h-full relative flex items-center justify-center">
                    {/* CCTV Stream Background Grid Noise */}
                    <div className="absolute inset-0 bg-[radial-gradient(#1e293b_1px,transparent_1px)] [background-size:16px_16px] opacity-40"></div>

                    {/* Camera Center Graphic */}
                    <div className="text-center p-6 space-y-2 z-0">
                      <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-slate-900/90 border border-slate-800 text-emerald-400 shadow-xl">
                        <Camera className="w-7 h-7" />
                      </div>
                      <p className="text-xs font-mono text-slate-400">AI STREAM ACTIVE • MODEL: STAFF-NET v4.2</p>
                    </div>

                    {/* AI Bounding Box Wireframe Overlay */}
                    <div className="absolute top-[28%] left-[32%] w-[24%] h-[46%] border-2 border-emerald-400 bg-emerald-500/10 rounded-sm shadow-xl animate-pulse pointer-events-none">
                      <div className="absolute -top-6 left-0 text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/40">
                        [Alex Rivera #4092] • 98.4% CONF
                      </div>
                    </div>

                    {/* PTZ Status Feedback Toast */}
                    {ptzMessage && (
                      <div className="absolute top-4 left-4 bg-emerald-950/90 border border-emerald-500/40 text-emerald-400 px-3 py-1.5 rounded-lg text-xs font-mono shadow-lg animate-fadeIn">
                        {ptzMessage}
                      </div>
                    )}
                  </div>
                ) : (
                  /* CCTV Standby State (Signal Interrupted) */
                  <div className="w-full h-full relative flex flex-col items-center justify-center p-6 text-center z-0 bg-[#070B14]">
                    {/* Animated Subtle Scanlines */}
                    <div className="absolute inset-0 bg-[linear-gradient(to_bottom,transparent_50%,rgba(0,0,0,0.4)_51%)] bg-[length:100%_4px] opacity-60 pointer-events-none"></div>

                    <div className="p-4 rounded-full bg-rose-950/40 border border-rose-500/30 text-rose-400 mb-4 animate-pulse">
                      <WifiOff className="w-8 h-8" />
                    </div>

                    <div className="space-y-1 mb-6">
                      <span className="inline-block px-3 py-1 rounded bg-rose-950/80 border border-rose-500/40 text-xs font-mono font-bold text-rose-300">
                        [ Camera 01 — Signal Interrupted ]
                      </span>
                      <p className="text-xs font-mono text-slate-400 pt-2">
                        RTSP Handshake Timeout • Stream dropped at 15:56:10
                      </p>
                    </div>

                    <button
                      onClick={handleReconnect}
                      disabled={isConnecting}
                      className="px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-mono font-bold text-xs tracking-wider uppercase shadow-lg shadow-emerald-500/20 transition-all flex items-center gap-2"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isConnecting ? 'animate-spin' : ''}`} />
                      <span>{isConnecting ? 'RE-ESTABLISHING...' : 'RE-ESTABLISH HANDSHAKE'}</span>
                    </button>
                  </div>
                )}

                {/* Floating Glass Pill Controls Bar Inside Viewport */}
                <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-slate-950/80 backdrop-blur-md border border-slate-800 rounded-full px-5 py-2 flex items-center gap-4 z-20 shadow-2xl">
                  {/* PTZ Arrows */}
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => triggerPTZ('UP')}
                      title="Pan Up"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-all"
                    >
                      <ChevronUp className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => triggerPTZ('LEFT')}
                      title="Pan Left"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-all"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => triggerPTZ('RIGHT')}
                      title="Pan Right"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-all"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => triggerPTZ('DOWN')}
                      title="Pan Down"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-all"
                    >
                      <ChevronDown className="w-4 h-4" />
                    </button>
                  </div>

                  <span className="text-slate-800">|</span>

                  <button
                    onClick={handleReconnect}
                    title="Refresh Camera"
                    className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-all"
                  >
                    <RefreshCw className="w-4 h-4" />
                  </button>
                  <button
                    title="Edit Zones"
                    className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-all"
                  >
                    <SlidersHorizontal className="w-4 h-4" />
                  </button>
                  <button
                    title="Fullscreen Mode"
                    className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 transition-all"
                  >
                    <Maximize2 className="w-4 h-4" />
                  </button>
                </div>

              </div>
            </section>

            {/* ── STATS BAR BELOW CAMERA ─────────────────────────────── */}
            <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
                <div className="p-3 rounded-xl bg-emerald-950/60 border border-emerald-500/30 text-emerald-400">
                  <Users className="w-5 h-5" />
                </div>
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider">Active Staff</span>
                  <div className="text-2xl font-extrabold font-mono text-white">142 / 150</div>
                </div>
              </div>

              <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
                <div className="p-3 rounded-xl bg-cyan-950/60 border border-cyan-500/30 text-cyan-400">
                  <Clock className="w-5 h-5" />
                </div>
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider">Customer Time</span>
                  <div className="text-xl font-bold font-mono text-white">4.2h avg</div>
                </div>
              </div>

              <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
                <div className="p-3 rounded-xl bg-indigo-950/60 border border-indigo-500/30 text-indigo-400">
                  <TrendingUp className="w-5 h-5" />
                </div>
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider">Corridor Traffic</span>
                  <div className="text-xl font-bold font-mono text-white">1,240 events</div>
                </div>
              </div>

              <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 flex items-center gap-4">
                <div className="p-3 rounded-xl bg-emerald-950/60 border border-emerald-500/30 text-emerald-400">
                  <Zap className="w-5 h-5" />
                </div>
                <div>
                  <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider">Team Efficiency</span>
                  <div className="text-2xl font-extrabold font-mono text-emerald-400">96.4%</div>
                </div>
              </div>
            </section>

          </div>

          {/* ── 4. RIGHT SIDEBAR ("TRACKERS" & "TODAY'S ROSTER") ───────── */}
          <div className="space-y-6">
            
            {/* Structured Active Tracker Gauge Card */}
            <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-5 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-xs font-mono font-bold uppercase text-slate-300 tracking-wider">
                  Active Tracker Gauge
                </h3>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950 text-emerald-400 border border-emerald-500/30">
                  94% INTEGRITY
                </span>
              </div>

              {/* Progress Ring Bar */}
              <div className="flex items-center justify-between gap-4">
                <div className="space-y-1">
                  <span className="text-2xl font-extrabold font-mono text-white">14 Active</span>
                  <p className="text-xs font-mono text-slate-400">Vision Nodes Tracking</p>
                </div>
                <div className="w-12 h-12 rounded-full border-4 border-emerald-500 border-t-slate-800 flex items-center justify-center font-mono font-bold text-xs text-emerald-400">
                  94%
                </div>
              </div>
            </div>

            {/* Refined "Today's Roster" Scrollable Feed */}
            <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-5 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-xs font-mono font-bold uppercase text-slate-300 tracking-wider">
                  Today's Roster
                </h3>
                <button className="p-1.5 rounded-lg bg-emerald-950 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-900/50 transition-colors">
                  <Plus className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Scrollable Roster Members Feed */}
              <div className="space-y-3 max-h-[440px] overflow-y-auto pr-1">
                {MOCK_ROSTER.map((staff) => (
                  <div
                    key={staff.id}
                    className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/80 hover:border-slate-700 transition-all flex items-center justify-between gap-3"
                  >
                    {/* Avatar with Status Dot */}
                    <div className="relative flex-shrink-0">
                      <div className="w-9 h-9 rounded-lg bg-slate-900 border border-slate-700 flex items-center justify-center font-mono font-bold text-xs text-slate-200">
                        {staff.avatar}
                      </div>
                      <span
                        className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-slate-950 ${
                          staff.status === 'ACTIVE'
                            ? 'bg-emerald-400'
                            : staff.status === 'BREAK'
                            ? 'bg-amber-400'
                            : 'bg-slate-500'
                        }`}
                      ></span>
                    </div>

                    {/* Typography: Name, Role, Shift Badge */}
                    <div className="flex-1 min-w-0">
                      <h4 className="text-xs font-medium text-slate-200 truncate">{staff.name}</h4>
                      <p className="text-[11px] font-sans text-slate-400 truncate">{staff.role}</p>
                    </div>

                    <span className="px-2 py-1 rounded text-[10px] font-mono text-emerald-400 bg-emerald-950/80 border border-emerald-500/30 flex-shrink-0">
                      {staff.shift} • {staff.shiftTime}
                    </span>
                  </div>
                ))}
              </div>
            </div>

          </div>

        </main>
      </div>
    </div>
  );
}
