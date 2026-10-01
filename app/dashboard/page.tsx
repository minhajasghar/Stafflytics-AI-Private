'use client';

/**
 * app/dashboard/page.tsx — Palantir/Verkada-style Vision Operations Center
 * ────────────────────────────────────────────────────────────────────────
 * High-end enterprise dashboard for staff tracking, activity monitoring,
 * and AI vision analytics.
 *
 * Features:
 * - Glassmorphism surface design (bg-slate-900/60 backdrop-blur-xl border-slate-800/80)
 * - Live ticking system clock & pulsing radar camera health status badge
 * - 4 Metric Overview Cards (Staff On Premises, Attendance, Feeds, Alerts)
 * - Multi-Camera AI Vision Feed grid with live bounding box wireframes & confidence scores
 * - Real-time Chronological Activity & Attendance log feed with category filtering
 * - Full Tailwind CSS + Lucide Icons integration
 */

import React, { useState, useEffect } from 'react';
import LiveVisionWallpaper from '@/components/LiveVisionWallpaper';
import Logo from '@/components/Logo';
import {
  Camera,
  Users,
  AlertTriangle,
  Clock,
  Activity,
  CheckCircle2,
  Search,
  Maximize2,
  Bell,
  Eye,
  ChevronRight,
  TrendingUp,
  UserCheck,
  RefreshCw,
} from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════════════
   Mock Data & Interfaces
═══════════════════════════════════════════════════════════════════════════ */
interface CameraFeed {
  id: string;
  name: string;
  location: string;
  status: 'ONLINE' | 'OFFLINE' | 'ALERT';
  fps: number;
  aiConfidence: number;
  detectedCount: number;
  detectedStaff: { id: string; name: string; conf: number; box: { x: number; y: number; w: number; h: number } }[];
  accent: string;
}

interface ActivityLog {
  id: string;
  staffName: string;
  staffId: string;
  department: string;
  avatar: string;
  event: string;
  eventType: 'CHECK_IN' | 'TRANSITION' | 'ANOMALY' | 'BREAK';
  location: string;
  timestamp: string;
  confidence: number;
  status: 'VERIFIED' | 'REVIEW_NEEDED' | 'FLAGGED';
}

const MOCK_FEEDS: CameraFeed[] = [
  {
    id: 'CAM-01',
    name: 'Main Gate Entrance',
    location: 'Building A • Ground Floor',
    status: 'ONLINE',
    fps: 60,
    aiConfidence: 99.4,
    detectedCount: 3,
    detectedStaff: [
      { id: '#4092', name: 'Alex Rivera', conf: 99.4, box: { x: 18, y: 24, w: 26, h: 48 } },
      { id: '#1804', name: 'Sarah Chen', conf: 98.1, box: { x: 58, y: 30, w: 24, h: 45 } },
    ],
    accent: 'emerald',
  },
  {
    id: 'CAM-02',
    name: 'Executive Floor A',
    location: 'Building A • Floor 4',
    status: 'ONLINE',
    fps: 60,
    aiConfidence: 97.8,
    detectedCount: 2,
    detectedStaff: [
      { id: '#8821', name: 'Marcus Vance', conf: 97.8, box: { x: 35, y: 20, w: 28, h: 52 } },
    ],
    accent: 'cyan',
  },
  {
    id: 'CAM-03',
    name: 'Cafeteria & Lounge',
    location: 'Building B • Floor 1',
    status: 'ONLINE',
    fps: 58,
    aiConfidence: 96.5,
    detectedCount: 14,
    detectedStaff: [
      { id: '#3041', name: 'Elena Rostova', conf: 96.5, box: { x: 42, y: 28, w: 25, h: 46 } },
    ],
    accent: 'indigo',
  },
  {
    id: 'CAM-04',
    name: 'Server Room Corridor',
    location: 'Building C • Basement (Restricted)',
    status: 'ALERT',
    fps: 60,
    aiConfidence: 91.2,
    detectedCount: 1,
    detectedStaff: [
      { id: '#UNKNOWN', name: 'Unidentified Motion', conf: 91.2, box: { x: 62, y: 32, w: 22, h: 42 } },
    ],
    accent: 'amber',
  },
];

const INITIAL_LOGS: ActivityLog[] = [
  {
    id: 'LOG-1092',
    staffName: 'Alex Rivera',
    staffId: '#4092',
    department: 'Engineering',
    avatar: 'AR',
    event: 'Gate Check-In (Access Granted)',
    eventType: 'CHECK_IN',
    location: 'Main Entrance • CAM-01',
    timestamp: '15:42:10',
    confidence: 99.4,
    status: 'VERIFIED',
  },
  {
    id: 'LOG-1091',
    staffName: 'Unidentified Motion',
    staffId: '#UNKNOWN',
    department: 'Perimeter Alert',
    avatar: '??',
    event: 'Restricted Zone Motion Detected',
    eventType: 'ANOMALY',
    location: 'Server Room • CAM-04',
    timestamp: '15:41:45',
    confidence: 91.2,
    status: 'FLAGGED',
  },
  {
    id: 'LOG-1090',
    staffName: 'Sarah Chen',
    staffId: '#1804',
    department: 'Product Ops',
    avatar: 'SC',
    event: 'Zone Transition (Lobby -> Workstation)',
    eventType: 'TRANSITION',
    location: 'Main Entrance • CAM-01',
    timestamp: '15:40:02',
    confidence: 98.1,
    status: 'VERIFIED',
  },
  {
    id: 'LOG-1089',
    staffName: 'Marcus Vance',
    staffId: '#8821',
    department: 'Executive',
    avatar: 'MV',
    event: 'Break Started (Lounge)',
    eventType: 'BREAK',
    location: 'Executive Floor • CAM-02',
    timestamp: '15:38:12',
    confidence: 97.8,
    status: 'VERIFIED',
  },
  {
    id: 'LOG-1088',
    staffName: 'Elena Rostova',
    staffId: '#3041',
    department: 'Data Science',
    avatar: 'ER',
    event: 'Zone Transition (Cafeteria)',
    eventType: 'TRANSITION',
    location: 'Cafeteria • CAM-03',
    timestamp: '15:35:50',
    confidence: 96.5,
    status: 'VERIFIED',
  },
];

/* ═══════════════════════════════════════════════════════════════════════════
   Main Dashboard Component
═══════════════════════════════════════════════════════════════════════════ */
export default function DashboardPage() {
  const [timeString, setTimeString] = useState<string>('');
  const [selectedLogFilter, setSelectedLogFilter] = useState<'ALL' | 'CHECK_IN' | 'ANOMALY'>('ALL');
  const [aiBoxesVisible, setAiBoxesVisible] = useState<boolean>(true);
  const [activeCamGrid, setActiveCamGrid] = useState<'2x2' | '1x1'>('2x2');
  const [activeSingleCam] = useState<string>('CAM-01');

  // Live Ticking Clock Effect
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

  const filteredLogs = INITIAL_LOGS.filter((log) => {
    if (selectedLogFilter === 'ALL') return true;
    return log.eventType === selectedLogFilter;
  });

  return (
    <div className="relative min-h-screen bg-[#060913] text-slate-100 font-sans antialiased overflow-x-hidden">
      {/* ── Background Live Vision Wallpaper ───────────────────────────── */}
      <LiveVisionWallpaper nodeCount={40} enableHUDBoxes={true} />

      {/* ── TOP SHELL NAVBAR ───────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 w-full bg-slate-950/70 backdrop-blur-xl border-b border-slate-800/80 px-4 lg:px-8 py-3 transition-all">
        <div className="max-w-[1800px] mx-auto flex items-center justify-between gap-4">
          
          {/* Left: Brand Logo & System Breadcrumb */}
          <div className="flex items-center gap-6">
            <Logo size={34} showText={true} />
            <div className="hidden md:flex items-center gap-2 text-xs font-mono text-slate-400 border-l border-slate-800 pl-6">
              <span className="text-slate-500">SYSTEM</span>
              <ChevronRight className="w-3.5 h-3.5 text-slate-600" />
              <span className="text-slate-300 font-semibold">VISION OPS CENTER</span>
              <ChevronRight className="w-3.5 h-3.5 text-slate-600" />
              <span className="text-emerald-400">LIVE FEED</span>
            </div>
          </div>

          {/* Center: Live Radar Camera Status & System Clock */}
          <div className="hidden xl:flex items-center gap-4 bg-slate-900/80 px-4 py-1.5 rounded-full border border-slate-800/90 text-xs font-mono">
            {/* Pulsing Radar Green Dot */}
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
              </span>
              <span className="text-emerald-400 font-bold tracking-wide">8/8 CAMERAS ONLINE</span>
            </div>
            <span className="text-slate-700">|</span>
            <div className="flex items-center gap-1.5 text-slate-300">
              <Clock className="w-3.5 h-3.5 text-cyan-400" />
              <span>{timeString || '15:42:00 UTC+05:00'}</span>
            </div>
          </div>

          {/* Right: Quick Search & Profile Avatar */}
          <div className="flex items-center gap-3">
            <div className="relative hidden sm:block">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                placeholder="Search staff, ID, or zone... (Cmd+K)"
                className="bg-slate-900/90 border border-slate-800 rounded-lg pl-9 pr-4 py-1.5 text-xs font-sans text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500/60 w-56 transition-all"
              />
            </div>
            
            <button className="p-2 rounded-lg bg-slate-900/90 border border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700 transition-all relative">
              <Bell className="w-4 h-4" />
              <span className="absolute top-1 right-1 w-2 h-2 bg-amber-500 rounded-full animate-pulse"></span>
            </button>

            {/* Operator Avatar */}
            <div className="flex items-center gap-2.5 border-l border-slate-800 pl-3 ml-1">
              <div className="w-8 h-8 rounded-lg bg-emerald-950 border border-emerald-500/40 flex items-center justify-center font-mono font-bold text-xs text-emerald-400 shadow-lg shadow-emerald-950/50">
                OP
              </div>
              <div className="hidden sm:flex flex-col">
                <span className="text-xs font-semibold text-slate-200 leading-tight">Cmdr. Vance</span>
                <span className="text-[10px] font-mono text-emerald-400">OPERATOR #4092</span>
              </div>
            </div>

          </div>
        </div>
      </header>

      {/* ── MAIN DASHBOARD CONTAINER ───────────────────────────────────── */}
      <main className="max-w-[1800px] mx-auto px-4 lg:px-8 py-6 space-y-6">

        {/* ── TOP METRIC OVERVIEW CARDS (4 ROW) ────────────────────────── */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          
          {/* Card 1: Staff On Premises */}
          <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 shadow-xl flex flex-col justify-between hover:border-slate-700/80 transition-all group">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-semibold tracking-wider text-slate-400 uppercase">
                Staff On Premises
              </span>
              <div className="p-2 rounded-xl bg-emerald-950/60 border border-emerald-500/30 text-emerald-400 group-hover:scale-110 transition-transform">
                <Users className="w-4 h-4" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <div>
                <span className="text-2xl lg:text-3xl font-extrabold text-white font-mono">142</span>
                <span className="text-xs font-mono text-slate-500 ml-1.5">/ 150 Total</span>
              </div>
              <span className="text-xs font-mono font-semibold text-emerald-400 flex items-center gap-0.5 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-500/30">
                <TrendingUp className="w-3 h-3" /> +12%
              </span>
            </div>
            {/* Capacity Progress Bar */}
            <div className="w-full bg-slate-950 rounded-full h-1.5 mt-3 overflow-hidden border border-slate-800">
              <div className="bg-emerald-500 h-full rounded-full w-[94.6%] transition-all duration-500"></div>
            </div>
          </div>

          {/* Card 2: On-Time Attendance Rate */}
          <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 shadow-xl flex flex-col justify-between hover:border-slate-700/80 transition-all group">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-semibold tracking-wider text-slate-400 uppercase">
                Attendance Rate
              </span>
              <div className="p-2 rounded-xl bg-cyan-950/60 border border-cyan-500/30 text-cyan-400 group-hover:scale-110 transition-transform">
                <UserCheck className="w-4 h-4" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-2xl lg:text-3xl font-extrabold text-white font-mono">96.4%</span>
              <span className="text-xs font-mono font-semibold text-cyan-400 flex items-center gap-0.5 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-500/30">
                <CheckCircle2 className="w-3 h-3" /> Nom. 95%
              </span>
            </div>
            <div className="w-full bg-slate-950 rounded-full h-1.5 mt-3 overflow-hidden border border-slate-800">
              <div className="bg-cyan-400 h-full rounded-full w-[96.4%] transition-all duration-500"></div>
            </div>
          </div>

          {/* Card 3: Active Vision Feeds */}
          <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 shadow-xl flex flex-col justify-between hover:border-slate-700/80 transition-all group">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-semibold tracking-wider text-slate-400 uppercase">
                Active Vision Streams
              </span>
              <div className="p-2 rounded-xl bg-indigo-950/60 border border-indigo-500/30 text-indigo-400 group-hover:scale-110 transition-transform">
                <Camera className="w-4 h-4" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-2xl lg:text-3xl font-extrabold text-white font-mono">8 / 8</span>
              <span className="text-xs font-mono text-indigo-400 bg-indigo-950/80 px-2 py-0.5 rounded border border-indigo-500/30">
                1080p60 AI
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 mt-3">
              <span>Latency: <strong className="text-slate-200">12ms</strong></span>
              <span>Inference: <strong className="text-emerald-400">98.9%</strong></span>
            </div>
          </div>

          {/* Card 4: Anomalies & Security Alerts */}
          <div className="bg-slate-900/60 backdrop-blur-xl border border-amber-900/40 rounded-2xl p-4 shadow-xl flex flex-col justify-between hover:border-amber-700/60 transition-all group">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-semibold tracking-wider text-slate-400 uppercase">
                Active Security Alerts
              </span>
              <div className="p-2 rounded-xl bg-amber-950/60 border border-amber-500/40 text-amber-400 group-hover:scale-110 transition-transform">
                <AlertTriangle className="w-4 h-4 animate-pulse" />
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-2xl lg:text-3xl font-extrabold text-amber-400 font-mono">1</span>
              <span className="text-xs font-mono font-semibold text-amber-400 bg-amber-950/80 px-2 py-0.5 rounded border border-amber-500/40 animate-pulse">
                UNRESOLVED
              </span>
            </div>
            <p className="text-[11px] font-mono text-slate-400 truncate mt-3">
              CAM-04: Restricted Server Room Motion
            </p>
          </div>

        </section>

        {/* ── CENTRAL SECTION: AI CAMERA GRID + REAL-TIME LOG FEED ───────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* ── LEFT 2 COLS: MULTI-CAMERA VISION FEED ──────────────────── */}
          <div className="lg:col-span-2 space-y-4">
            
            {/* Feed Section Controls Bar */}
            <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-emerald-950/60 border border-emerald-500/30 text-emerald-400">
                  <Eye className="w-4 h-4" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-white tracking-wide">SURVEILLANCE AI MATRIX</h2>
                  <p className="text-[11px] font-mono text-slate-400">Real-time pose estimation & face vector tracking</p>
                </div>
              </div>

              {/* Grid Toggle Buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setAiBoxesVisible(!aiBoxesVisible)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono border transition-all ${
                    aiBoxesVisible
                      ? 'bg-emerald-950/80 border-emerald-500/40 text-emerald-400'
                      : 'bg-slate-900 border-slate-800 text-slate-400'
                  }`}
                >
                  AI WIREFRAMES: {aiBoxesVisible ? 'ON' : 'OFF'}
                </button>

                <div className="flex items-center bg-slate-950 rounded-lg border border-slate-800 p-0.5">
                  <button
                    onClick={() => setActiveCamGrid('2x2')}
                    className={`px-2.5 py-1 rounded text-xs font-mono transition-all ${
                      activeCamGrid === '2x2' ? 'bg-slate-800 text-white font-bold' : 'text-slate-500'
                    }`}
                  >
                    2x2 GRID
                  </button>
                  <button
                    onClick={() => setActiveCamGrid('1x1')}
                    className={`px-2.5 py-1 rounded text-xs font-mono transition-all ${
                      activeCamGrid === '1x1' ? 'bg-slate-800 text-white font-bold' : 'text-slate-500'
                    }`}
                  >
                    SOLO
                  </button>
                </div>
              </div>
            </div>

            {/* Camera Feed Cards Grid */}
            <div
              className={`grid gap-4 ${
                activeCamGrid === '2x2' ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1'
              }`}
            >
              {MOCK_FEEDS.filter((f) => activeCamGrid === '2x2' || f.id === activeSingleCam).map((feed) => (
                <div
                  key={feed.id}
                  className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/90 rounded-2xl overflow-hidden shadow-2xl relative group"
                >
                  {/* Camera Header Overlay */}
                  <div className="bg-slate-950/80 backdrop-blur-md px-3.5 py-2.5 border-b border-slate-800/80 flex items-center justify-between text-xs font-mono">
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          feed.status === 'ONLINE' ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400 animate-ping'
                        }`}
                      ></span>
                      <span className="font-bold text-slate-200">{feed.id}</span>
                      <span className="text-slate-600">|</span>
                      <span className="text-slate-400 truncate max-w-[140px]">{feed.name}</span>
                    </div>

                    <div className="flex items-center gap-2 text-[10px]">
                      <span className="bg-slate-900 border border-slate-800 px-1.5 py-0.5 rounded text-emerald-400 font-semibold">
                        REC • 60FPS
                      </span>
                      <button className="text-slate-500 hover:text-slate-300">
                        <Maximize2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Simulated Vision Camera Frame Container */}
                  <div className="relative aspect-video bg-slate-950 flex items-center justify-center overflow-hidden">
                    {/* Simulated Background Camera Feed Noise Grid */}
                    <div className="absolute inset-0 bg-[radial-gradient(#1e293b_1px,transparent_1px)] [background-size:16px_16px] opacity-40"></div>

                    {/* Camera Video Simulation Graphics */}
                    <div className="text-center p-6 space-y-2 z-0">
                      <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-slate-900/80 border border-slate-800 text-slate-600">
                        <Camera className="w-6 h-6" />
                      </div>
                      <p className="text-xs font-mono text-slate-500">{feed.location}</p>
                      <span className="inline-block text-[10px] font-mono text-emerald-400/80 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-500/20">
                        AI MODEL: STAFF-NET v4.2 ACTIVE
                      </span>
                    </div>

                    {/* Simulated AI Detection Wireframe Bounding Box Overlays */}
                    {aiBoxesVisible &&
                      feed.detectedStaff.map((staff, idx) => (
                        <div
                          key={idx}
                          style={{
                            left: `${staff.box.x}%`,
                            top: `${staff.box.y}%`,
                            width: `${staff.box.w}%`,
                            height: `${staff.box.h}%`,
                          }}
                          className={`absolute border-2 ${
                            feed.status === 'ALERT'
                              ? 'border-amber-400 bg-amber-500/10'
                              : 'border-emerald-400 bg-emerald-500/10'
                          } rounded-sm shadow-lg pointer-events-none transition-all duration-700 animate-pulse`}
                        >
                          {/* Corner Brackets */}
                          <div className="absolute -top-1 -left-1 w-2 h-2 border-t-2 border-l-2 border-white"></div>
                          <div className="absolute -top-1 -right-1 w-2 h-2 border-t-2 border-r-2 border-white"></div>
                          <div className="absolute -bottom-1 -left-1 w-2 h-2 border-b-2 border-l-2 border-white"></div>
                          <div className="absolute -bottom-1 -right-1 w-2 h-2 border-b-2 border-r-2 border-white"></div>

                          {/* AI Detection Label Tag */}
                          <div
                            className={`absolute -top-6 left-0 text-[10px] font-mono px-1.5 py-0.5 rounded whitespace-nowrap shadow-md ${
                              feed.status === 'ALERT'
                                ? 'bg-amber-950 text-amber-300 border border-amber-500/40'
                                : 'bg-emerald-950 text-emerald-300 border border-emerald-500/40'
                            }`}
                          >
                            [{staff.name} {staff.id}] • {staff.conf}%
                          </div>
                        </div>
                      ))}

                    {/* Live Timestamp & Crosshair Overlay */}
                    <div className="absolute bottom-2 left-2.5 text-[10px] font-mono text-slate-400 bg-slate-950/80 px-2 py-0.5 rounded border border-slate-800">
                      LIVE • {timeString.split(' ')[0]}
                    </div>
                    <div className="absolute bottom-2 right-2.5 text-[10px] font-mono text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-500/30">
                      NODES DETECTED: {feed.detectedCount}
                    </div>
                  </div>
                </div>
              ))}
            </div>

          </div>

          {/* ── RIGHT 1 COL: REAL-TIME ACTIVITY & ATTENDANCE LOG FEED ───── */}
          <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-4 lg:p-5 shadow-2xl flex flex-col justify-between space-y-4">
            
            {/* Header & Filter Tabs */}
            <div>
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <div className="flex items-center gap-2.5">
                  <div className="p-1.5 rounded-lg bg-cyan-950/60 border border-cyan-500/30 text-cyan-400">
                    <Activity className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white tracking-wide">LIVE ATTENDANCE LOG</h3>
                    <p className="text-[10px] font-mono text-slate-400">Verified biometric & camera stream logs</p>
                  </div>
                </div>
                <button className="text-slate-500 hover:text-slate-300 transition-colors">
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Filter Buttons */}
              <div className="flex items-center gap-1.5 mt-3">
                <button
                  onClick={() => setSelectedLogFilter('ALL')}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-mono transition-all ${
                    selectedLogFilter === 'ALL'
                      ? 'bg-slate-800 text-white font-bold border border-slate-700'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  ALL LOGS
                </button>
                <button
                  onClick={() => setSelectedLogFilter('CHECK_IN')}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-mono transition-all ${
                    selectedLogFilter === 'CHECK_IN'
                      ? 'bg-emerald-950 text-emerald-400 border border-emerald-500/30 font-bold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  CHECK-INS
                </button>
                <button
                  onClick={() => setSelectedLogFilter('ANOMALY')}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-mono transition-all ${
                    selectedLogFilter === 'ANOMALY'
                      ? 'bg-amber-950 text-amber-400 border border-amber-500/30 font-bold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  ALERTS
                </button>
              </div>
            </div>

            {/* Scrollable Chronological Log Stream */}
            <div className="space-y-3 overflow-y-auto max-h-[520px] pr-1 scrollbar-thin scrollbar-thumb-slate-800">
              {filteredLogs.map((log) => (
                <div
                  key={log.id}
                  className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/80 hover:border-slate-700 transition-all flex items-start gap-3 group"
                >
                  {/* Staff Initials Avatar */}
                  <div
                    className={`w-9 h-9 rounded-lg flex items-center justify-center font-mono font-bold text-xs flex-shrink-0 border ${
                      log.eventType === 'ANOMALY'
                        ? 'bg-amber-950/80 border-amber-500/40 text-amber-400'
                        : 'bg-slate-900 border-slate-700 text-slate-300'
                    }`}
                  >
                    {log.avatar}
                  </div>

                  {/* Event Metadata Details */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs font-semibold text-slate-200 truncate group-hover:text-emerald-400 transition-colors">
                        {log.staffName}
                      </span>
                      <span className="text-[10px] font-mono text-slate-500 flex-shrink-0">
                        {log.timestamp}
                      </span>
                    </div>

                    <p className="text-[11px] font-sans text-slate-400 mt-0.5 truncate">{log.event}</p>

                    <div className="flex items-center justify-between gap-2 mt-2 text-[10px] font-mono">
                      <span className="text-slate-500 truncate">{log.location}</span>
                      <span
                        className={`px-1.5 py-0.5 rounded font-bold ${
                          log.status === 'VERIFIED'
                            ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-500/30'
                            : 'bg-amber-950/80 text-amber-400 border border-amber-500/30'
                        }`}
                      >
                        {log.confidence}% MATCH
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Bottom Footer Action */}
            <div className="pt-2 border-t border-slate-800">
              <button className="w-full py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs font-mono font-semibold text-slate-300 flex items-center justify-center gap-2 transition-all">
                <span>VIEW FULL AUDIT TRAIL</span>
                <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
              </button>
            </div>

          </div>

        </div>

      </main>
    </div>
  );
}
