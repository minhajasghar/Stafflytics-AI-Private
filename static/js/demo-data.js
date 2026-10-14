/**
 * ╔══════════════════════════════════════════════════════════════════════╗
 * ║         STAFFLYTICS AI – DEMO / PRESENTATION DATA LAYER             ║
 * ║  Intercepts all /api/* fetch calls and returns hardcoded fake data  ║
 * ║  so the dashboard looks fully live for demonstrations.              ║
 * ║  Remove this <script> tag when going back to production.            ║
 * ╚══════════════════════════════════════════════════════════════════════╝
 */

(function () {
    'use strict';

    // ─── Helpers ────────────────────────────────────────────────────────────────
    function today(daysAgo = 0) {
        const d = new Date();
        d.setDate(d.getDate() - daysAgo);
        return d.toISOString().slice(0, 10);
    }
    function fmtDate(daysAgo) {
        return today(daysAgo);
    }
    function rnd(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    }

    // ─── Staff Master List ───────────────────────────────────────────────────────
    const STAFF = [
        { id: 'EMP-001', name: 'Minhaj Asghar',    role: 'Co-Founder / AI Solutions Architect',    shift: 'Morning', shift_time: '09:00', rate: 75000, salary_type: 'Monthly' },
        { id: 'EMP-002', name: 'Asad Younas',       role: 'Co-Founder / Web Solutions Architect',   shift: 'Morning', shift_time: '09:00', rate: 70000, salary_type: 'Monthly' },
        { id: 'EMP-003', name: 'Azhar Iqbal',       role: 'Head of Business Development',           shift: 'Morning', shift_time: '09:30', rate: 65000, salary_type: 'Monthly' },
        { id: 'EMP-004', name: 'Sultan Mahmood',    role: 'Head of Quality Assurance',              shift: 'Evening', shift_time: '14:00', rate: 60000, salary_type: 'Monthly' },
        { id: 'EMP-005', name: 'Zia Younas',        role: 'AI Intern',                              shift: 'Morning', shift_time: '10:00', rate:  1200, salary_type: 'Hourly'  },
        { id: 'EMP-006', name: 'Huzaifa Munir',     role: 'Electronics Engineer',                   shift: 'Evening', shift_time: '13:00', rate: 55000, salary_type: 'Monthly' },
        { id: 'EMP-007', name: 'Muhammad Hussain',  role: 'AI Intern',                              shift: 'Morning', shift_time: '10:00', rate:  1100, salary_type: 'Hourly'  },
    ];

    // Add photo placeholder key (no real photo for demo)
    STAFF.forEach(s => { s.photo = null; });

    // ─── Attendance Records (last 30 days) ───────────────────────────────────────
    const ATTENDANCE = [];
    const statusOptions = ['Completed', 'Completed', 'Completed', 'Late', 'Completed'];

    for (let day = 0; day < 30; day++) {
        STAFF.forEach(s => {
            if (day === 0 && Math.random() > 0.3) return; // some still on shift today
            const inHour  = s.shift === 'Morning' ? 9  : 14;
            const outHour = s.shift === 'Morning' ? 18 : 22;
            const late    = Math.random() < 0.1;
            const actualIn = `${String(inHour + (late ? 1 : 0)).padStart(2,'0')}:${late ? String(rnd(5,30)).padStart(2,'0') : '00'}`;
            const actualOut = `${String(outHour).padStart(2,'0')}:${String(rnd(0,30)).padStart(2,'0')}`;
            const hours   = (outHour - inHour - (late ? 1 : 0)).toFixed(1);
            const eff     = rnd(72, 97);
            ATTENDANCE.push({
                date: fmtDate(day),
                name: s.name,
                role: s.role,
                in:   actualIn,
                out:  actualOut,
                hours,
                efficiency: eff,
                status: late ? 'Late' : (day === 0 ? 'Active' : 'Completed')
            });
        });
    }

    // ─── Visitor / Customer fake data ────────────────────────────────────────────
    const CUSTOMER_HISTORY = [
        { id: 'CUST-041', name: 'Ahmed Raza',      time: `${today()} 11:32`, duration: '18 min', zone: 'Main Hall',   photo: null },
        { id: 'CUST-039', name: 'Sara Noor',        time: `${today()} 10:55`, duration: '25 min', zone: 'Reception',   photo: null },
        { id: 'CUST-037', name: 'Usman Tariq',      time: `${today()} 10:14`, duration: '12 min', zone: 'Main Hall',   photo: null },
        { id: 'CUST-035', name: 'Fatima Ali',       time: `${today()} 09:48`, duration: '31 min', zone: 'Meeting Rm',  photo: null },
        { id: 'CUST-033', name: 'Bilal Khan',       time: `${today()} 09:21`, duration: '9 min',  zone: 'Reception',   photo: null },
        { id: 'CUST-031', name: 'Ayesha Siddiqui',  time: `${today(1)} 16:42`, duration: '44 min', zone: 'Main Hall',  photo: null },
        { id: 'CUST-028', name: 'Hamza Sheikh',     time: `${today(1)} 15:19`, duration: '22 min', zone: 'Main Hall',   photo: null },
        { id: 'CUST-025', name: 'Zainab Malik',     time: `${today(1)} 14:05`, duration: '15 min', zone: 'Reception',   photo: null },
        { id: 'CUST-022', name: 'Faisal Qureshi',   time: `${today(1)} 11:30`, duration: '28 min', zone: 'Meeting Rm',  photo: null },
        { id: 'CUST-019', name: 'Mariam Ansari',    time: `${today(2)} 14:10`, duration: '19 min', zone: 'Main Hall',   photo: null },
        { id: 'CUST-016', name: 'Tariq Mehmood',    time: `${today(2)} 13:00`, duration: '35 min', zone: 'Main Hall',   photo: null },
        { id: 'CUST-013', name: 'Nadia Butt',       time: `${today(3)} 10:22`, duration: '11 min', zone: 'Reception',   photo: null },
        { id: 'CUST-010', name: 'Imran Baig',       time: `${today(3)} 09:44`, duration: '27 min', zone: 'Main Hall',   photo: null },
        { id: 'CUST-007', name: 'Kiran Javed',      time: `${today(4)} 15:15`, duration: '38 min', zone: 'Meeting Rm',  photo: null },
        { id: 'CUST-004', name: 'Sohail Hassan',    time: `${today(5)} 11:05`, duration: '21 min', zone: 'Main Hall',   photo: null },
    ];

    // ─── Loyalty (repeat visitors) ───────────────────────────────────────────────
    const LOYALTY = [
        { id: 'CUST-041', name: 'Ahmed Raza',       visits: 14, last_visit: today(0),  photo: null },
        { id: 'CUST-039', name: 'Sara Noor',         visits: 11, last_visit: today(0),  photo: null },
        { id: 'CUST-037', name: 'Usman Tariq',       visits: 9,  last_visit: today(0),  photo: null },
        { id: 'CUST-016', name: 'Tariq Mehmood',     visits: 8,  last_visit: today(2),  photo: null },
        { id: 'CUST-031', name: 'Ayesha Siddiqui',   visits: 7,  last_visit: today(1),  photo: null },
        { id: 'CUST-028', name: 'Hamza Sheikh',      visits: 6,  last_visit: today(1),  photo: null },
        { id: 'CUST-022', name: 'Faisal Qureshi',    visits: 5,  last_visit: today(1),  photo: null },
        { id: 'CUST-013', name: 'Nadia Butt',        visits: 4,  last_visit: today(3),  photo: null },
        { id: 'CUST-007', name: 'Kiran Javed',       visits: 4,  last_visit: today(4),  photo: null },
        { id: 'CUST-004', name: 'Sohail Hassan',     visits: 3,  last_visit: today(5),  photo: null },
    ];

    // ─── Zones ───────────────────────────────────────────────────────────────────
    const ZONES = [
        { name: 'Main Hall',   points: [[50,50],[590,50],[590,380],[50,380]],   unauthorized: [] },
        { name: 'Reception',   points: [[50,50],[250,50],[250,200],[50,200]],   unauthorized: [] },
        { name: 'Meeting Rm',  points: [[300,200],[590,200],[590,430],[300,430]], unauthorized: ['AI Intern'] },
    ];

    // ─── Optimization hourly data ─────────────────────────────────────────────────
    const HOURLY = Array.from({ length: 24 }, (_, h) => ({
        hour: h,
        activity: h < 8 ? 0 : h < 10 ? rnd(20,45) : h < 13 ? rnd(60,92) : h < 15 ? rnd(40,70) : h < 19 ? rnd(65,95) : h < 22 ? rnd(30,55) : rnd(0,15)
    }));

    const OPT_SUGGESTIONS = [
        { time: '09:00 – 11:00', type: 'PEAK TRAFFIC', advice: 'Add 2 Staff on Floor',   reason: '87% peak activity detected' },
        { time: '13:00 – 14:00', type: 'LOW TRAFFIC',  advice: 'Rotate 1 to Break Room', reason: 'Activity drops below 40%'   },
        { time: '17:00 – 19:30', type: 'PEAK TRAFFIC', advice: 'All-Hands Evening Shift', reason: '93% peak, all staff needed' },
        { time: '21:00 onwards', type: 'LOW TRAFFIC',  advice: 'Wind down to 2 staff',    reason: 'Activity under 30%'          },
    ];

    // ─── Roster (Today's schedule) ────────────────────────────────────────────────
    const ROSTER = STAFF.map(s => ({
        name:    s.name,
        role:    s.role,
        shift:   s.shift,
        time:    s.shift_time,
        on_floor: Math.random() > 0.25,
        is_active: Math.random() > 0.25
    }));

    // ─── /api/status response ─────────────────────────────────────────────────────
    const STATUS_PAYLOAD = {
        initializing: false,
        count: 5,
        avg_efficiency: 84,
        incidents_today: 1,
        monthly_customers: 312,
        repeat_customers: 28,
        today_customers: 17,
        today_customer_minutes: 243,
        passage: { l_to_r: 34, r_to_l: 28 },
        active_list: [
            { name: 'Minhaj Asghar',   zone: 'Main Hall',  time_ago: '2 min ago' },
            { name: 'Asad Younas',     zone: 'Reception',  time_ago: '5 min ago' },
            { name: 'Azhar Iqbal',     zone: 'Main Hall',  time_ago: 'just now'  },
            { name: 'Zia Younas',      zone: 'Meeting Rm', time_ago: '8 min ago' },
            { name: 'Muhammad Hussain',zone: 'Main Hall',  time_ago: '11 min ago'},
        ],
        roster: ROSTER,
        new_alert: false,
        alert_details: null,
    };

    // ─── Synergy metrics ──────────────────────────────────────────────────────────
    const SYNERGY = {
        metrics: [
            { label: 'Avg Efficiency',    value: '84%'  },
            { label: 'Team Synergy',      value: '91%'  },
            { label: 'On-Time Rate',      value: '88%'  },
            { label: 'Engagement Score',  value: '76%'  },
        ]
    };

    // ─── Performance rankings ─────────────────────────────────────────────────────
    const PERFORMANCE = STAFF.map((s, i) => ({
        name: s.name,
        role: s.role,
        score: [92, 87, 83, 79, 76, 72, 68][i]
    }));

    // ─── Engagement ───────────────────────────────────────────────────────────────
    const ENGAGEMENT = STAFF.map((s, i) => ({
        name:           s.name,
        dining_events:  [48, 42, 37, 31, 24, 20, 16][i],
        total_events:   [60, 55, 50, 42, 34, 28, 22][i],
        engagement_pct: [80, 76, 74, 74, 71, 71, 73][i]
    }));

    // ─── Wellbeing ────────────────────────────────────────────────────────────────
    const WELLBEING = STAFF.map((s, i) => ({
        name:        s.name,
        hours:       [3.2, 2.8, 4.1, 3.6, 2.4, 3.9, 2.1][i],
        needs_break: [false, false, true, false, false, true, false][i]
    }));

    // ─── Visitor analytics ────────────────────────────────────────────────────────
    const VISITOR_DAY = {
        total_unique_visitors: 17,
        new_faces: 6,
        returning_customers: 11,
        regular_customers: 8,
        frequency_distribution: { '1': 6, '2': 5, '3': 3, '4': 2, '5+': 1 },
        daily_breakdown: []
    };
    const VISITOR_MONTH = {
        total_unique_visitors: 168,
        new_faces: 54,
        returning_customers: 114,
        regular_customers: 72,
        frequency_distribution: { '1': 54, '2': 42, '3': 31, '4': 22, '5+': 19 },
        daily_breakdown: Array.from({ length: 30 }, (_, i) => ({
            date:            fmtDate(29 - i),
            unique_visitors: rnd(4, 24),
            new_faces:       rnd(1, 8),
            total_events:    rnd(8, 32)
        }))
    };

    // ─── Email / Camera settings ──────────────────────────────────────────────────
    const EMAIL_SETTINGS = {
        owner_email:        'owner@stafflytics.ai',
        sender_email:       'notifications@stafflytics.ai',
        sender_password:    '',
        wellness_threshold: '4',
        late_grace_minutes: '10',
        rtsp_url:           'rtsp://admin:demo1234@192.168.1.108:554/stream',
        camera_preset:      '720p'
    };

    // ─── Fake response builder ────────────────────────────────────────────────────
    function fakeResponse(data, status = 200) {
        return new Response(JSON.stringify(data), {
            status,
            headers: { 'Content-Type': 'application/json' }
        });
    }

    // ─── Intercept fetch ──────────────────────────────────────────────────────────
    const _origFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
        const url = (typeof input === 'string') ? input : (input.url || '');

        // ── /api/status ─────────────────────────────────────────────────────────
        if (url.includes('/api/status')) {
            return fakeResponse(STATUS_PAYLOAD);
        }

        // ── /api/staff/all ───────────────────────────────────────────────────────
        if (url.includes('/api/staff/all')) {
            return fakeResponse(STAFF);
        }

        // ── /api/analytics/performance ───────────────────────────────────────────
        if (url.includes('/api/analytics/performance')) {
            return fakeResponse(PERFORMANCE);
        }

        // ── /api/analytics/synergy ───────────────────────────────────────────────
        if (url.includes('/api/analytics/synergy')) {
            return fakeResponse(SYNERGY);
        }

        // ── /api/analytics/engagement ────────────────────────────────────────────
        if (url.includes('/api/analytics/engagement')) {
            return fakeResponse(ENGAGEMENT);
        }

        // ── /api/analytics/wellbeing ─────────────────────────────────────────────
        if (url.includes('/api/analytics/wellbeing')) {
            return fakeResponse(WELLBEING);
        }

        // ── /api/analytics/loyalty ───────────────────────────────────────────────
        if (url.includes('/api/analytics/loyalty')) {
            return fakeResponse(LOYALTY);
        }

        // ── /api/analytics/visitors ──────────────────────────────────────────────
        if (url.includes('/api/analytics/visitors')) {
            const scope = url.includes('scope=month') ? 'month' : 'day';
            return fakeResponse(scope === 'month' ? VISITOR_MONTH : VISITOR_DAY);
        }

        // ── /api/analytics/customers/history ────────────────────────────────────
        if (url.includes('/api/analytics/customers/history')) {
            return fakeResponse(CUSTOMER_HISTORY);
        }

        // ── /api/analytics/optimization ─────────────────────────────────────────
        if (url.includes('/api/analytics/optimization')) {
            return fakeResponse({ data: HOURLY, suggestions: OPT_SUGGESTIONS });
        }

        // ── /api/reports/attendance ──────────────────────────────────────────────
        if (url.includes('/api/reports/attendance')) {
            // Filter by date param if present
            let records = ATTENDANCE;
            const dateMatch = url.match(/date=(\d{4}-\d{2}-\d{2})/);
            const monthMatch = url.match(/month=(\d+)&year=(\d+)/);
            if (dateMatch) {
                records = ATTENDANCE.filter(r => r.date === dateMatch[1]);
            } else if (monthMatch) {
                const m = parseInt(monthMatch[1]), y = parseInt(monthMatch[2]);
                records = ATTENDANCE.filter(r => {
                    const d = new Date(r.date);
                    return d.getMonth() + 1 === m && d.getFullYear() === y;
                });
            }
            return fakeResponse(records);
        }

        // ── /api/settings/emails ─────────────────────────────────────────────────
        if (url.includes('/api/settings/emails')) {
            if (init && (init.method === 'POST' || init.method === 'post')) {
                return fakeResponse({ status: 'ok' });
            }
            return fakeResponse(EMAIL_SETTINGS);
        }

        // ── /api/settings/account ────────────────────────────────────────────────
        if (url.includes('/api/settings/account')) {
            if (init && (init.method === 'POST' || init.method === 'post')) {
                return fakeResponse({ status: 'success', message: 'Credentials updated.', username: 'admin' });
            }
            return fakeResponse({ username: 'admin' });
        }

        // ── /api/settings/camera ─────────────────────────────────────────────────
        if (url.includes('/api/settings/camera')) {
            return fakeResponse({ status: 'ok' });
        }

        // ── /api/events/all ──────────────────────────────────────────────────────
        if (url.includes('/api/events/all')) {
            return fakeResponse([
                { date: today(2), type: 'Product Launch',  intensity: 'High'      },
                { date: today(7), type: 'Team Workshop',   intensity: 'Very High' },
                { date: today(14),type: 'Investor Meeting',intensity: 'Critical'  },
            ]);
        }

        // ── /api/zones/all ───────────────────────────────────────────────────────
        if (url.includes('/api/zones')) {
            return fakeResponse(ZONES);
        }

        // ── Mutable POST endpoints – just acknowledge ────────────────────────────
        if (init && (init.method === 'POST' || init.method === 'DELETE' || init.method === 'post')) {
            if (url.includes('/api/staff/delete') || url.includes('/api/staff/update') ||
                url.includes('/api/events/add') || url.includes('/api/events/delete') ||
                url.includes('/api/zones/update') || url.includes('/api/camera/') ||
                url.includes('/api/staff/enroll')) {
                return fakeResponse({ status: 'success', message: 'Demo mode: action acknowledged.' });
            }
        }

        // ── /api/stream/status – keep offline so we fall back to MJPEG ──────────
        if (url.includes('/api/stream/status')) {
            return fakeResponse({ mode: 'mjpeg', enabled: false });
        }

        // ── Let non-API calls (video feed, auth, etc.) pass through ─────────────
        return _origFetch(input, init);
    };

    console.log('%c[DEMO MODE] Stafflytics fake data layer active.', 'color:#f59e0b; font-weight:800; font-size:13px;');
})();
