let zonePoints = [];
let isEditingZones = false;
const canvas = document.getElementById('zone-canvas');
const ctx = canvas ? canvas.getContext('2d') : null;

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('stafflytics-theme', theme);
    const btns = document.querySelectorAll('[title="Toggle Theme"]');
    btns.forEach(btn => {
        btn.innerHTML = theme === 'dark' ? '<i class="fas fa-sun"></i>' : '<i class="fas fa-moon"></i>';
    });
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    applyTheme(current === 'dark' ? 'light' : 'dark');
}

function toggleMobileMenu() {
    const sheet = document.getElementById('mobile-menu-sheet');
    const overlay = document.getElementById('mobile-menu-overlay');
    if (!sheet || !overlay) return;
    if (sheet.classList.contains('hidden')) {
        sheet.classList.remove('hidden');
        overlay.classList.remove('hidden');
    } else {
        sheet.classList.add('hidden');
        overlay.classList.add('hidden');
    }
}

function loadSavedTheme() {
    const saved = localStorage.getItem('stafflytics-theme');
    if (saved) applyTheme(saved);
}

function renderEmptyState(containerId, message, icon = 'fa-chart-bar') {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = `
        <div class="empty-state">
            <i class="fas ${icon}"></i>
            <p style="font-weight:700; font-size:0.85rem;">${message}</p>
        </div>
    `;
}

function updateClock() {
    const clockElement = document.getElementById('clock');
    if (clockElement) {
        const now = new Date();
        const options = { month: 'long', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };
        clockElement.innerText = now.toLocaleString('en-US', options).replace(',', ' •');
    }
}

function showTooltip(e, text) {
    const tip = document.getElementById('global-tooltip');
    if (!tip) return;
    tip.innerText = text; tip.style.display = 'block';
    tip.style.left = (e.clientX + 10) + 'px'; tip.style.top = (e.clientY + 10) + 'px';
}
function hideTooltip() { 
    const tip = document.getElementById('global-tooltip');
    if (tip) tip.style.display = 'none'; 
}

function handleLogout() {
    window.location.href = '/api/auth/logout';
}

function handleNavClick(element) {
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    element.classList.add('active');
    const title = element.getAttribute('title');
    document.querySelectorAll('.view-section').forEach(s => s.classList.add('hidden'));

    const sectionMap = { 
        'Monitor': 'section-monitor', 
        'Analytics': 'section-analytics', 
        'Staff List': 'section-staff',
        'Reporting': 'section-reporting', 
        'Settings': 'section-settings',
        'Performance': 'section-performance',
        'ROI Analysis': 'section-roi', // Now Salary Admin
        'Shift Optimizer': 'section-optimization'
    };
    const targetId = sectionMap[title];
    if (targetId) {
        document.getElementById(targetId).classList.remove('hidden');
        if (targetId === 'section-staff') loadStaffDirectory();
        if (targetId === 'section-reporting') loadAttendanceReports();
        if (targetId === 'section-analytics') {
            loadVisitorAnalytics('day');
            loadSynergyMetrics();
            loadEngagementAnalytics();
            loadWellbeingAnalytics();
            loadLoyaltyAnalytics();
            loadCustomerVisitHistory();
        }
        if (targetId === 'section-performance') loadPerformanceRankings();
        if (targetId === 'section-roi') loadSalaryAdmin();
        if (targetId === 'section-optimization') renderAnalyzeButton();
        if (targetId === 'section-settings') { 
            try {
                loadEvents(); 
                loadEmailSettings(); 
                loadCameraSettings(); 
            } catch (e) { console.error("Settings load error", e); }
        }
    }
}

async function loadEngagementAnalytics() {
    try {
        const res = await fetch('/api/analytics/engagement');
        const data = await res.json();
        const list = document.getElementById('engagement-list');
        if (!list) return;
        
        if (data.length === 0) {
            renderEmptyState('engagement-list', 'No service activity yet.', 'fa-handshake-angle');
            return;
        }

        list.innerHTML = data.map(item => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:12px; background:var(--nav-hover); border-radius:12px; border-left:4px solid var(--accent);">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div>
                        <div style="font-weight:800; font-size:0.9rem;">${item.name}</div>
                        <div style="font-size:0.6rem; color:var(--text-muted); font-weight:700;">${item.dining_events} DINING EVENTS / ${item.total_events} TOTAL</div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:800; color:var(--accent); font-size:1.1rem;">${item.engagement_pct}%</div>
                    <div style="font-size:0.6rem; font-weight:800; opacity:0.6;">SERVICE ENGAGEMENT</div>
                </div>
            </div>
        `).join('');
    } catch (e) { console.error("Engagement Load Error", e); document.getElementById('engagement-list') && (document.getElementById('engagement-list').innerHTML = '<div class="empty-state"><i class="fas fa-exclamation-triangle" style="color:var(--red);"></i><p style="color:var(--text-muted);">Failed to load engagement data.</p></div>'); }
}

async function loadWellbeingAnalytics() {
    try {
        const res = await fetch('/api/analytics/wellbeing');
        const data = await res.json();
        const list = document.getElementById('wellbeing-list');
        if (!list) return;

        if (data.length === 0) {
            renderEmptyState('wellbeing-list', 'All staff are rested.', 'fa-house-medical');
            return;
        }

        list.innerHTML = data.map(item => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:12px; background:var(--nav-hover); border-radius:12px; border-left:4px solid var(--red);">
                <div>
                    <div style="font-weight:800; font-size:0.9rem;">${item.name}</div>
                    <div style="font-size:0.65rem; color:var(--text-muted); font-weight:700;">${item.hours}h ON CONTINUOUS DUTY</div>
                </div>
                ${item.needs_break ? '<span style="background:var(--red); color:white; font-size:0.6rem; font-weight:900; padding:4px 8px; border-radius:4px;">NEEDS BREAK</span>' : '<span style="color:var(--green); font-size:0.6rem; font-weight:900;">HEALTHY</span>'}
            </div>
        `).join('');
    } catch (e) { console.error("Wellbeing Load Error", e); document.getElementById('wellbeing-list') && (document.getElementById('wellbeing-list').innerHTML = '<div class="empty-state"><i class="fas fa-exclamation-triangle" style="color:var(--red);"></i><p style="color:var(--text-muted);">Failed to load wellbeing data.</p></div>'); }
}

async function loadLoyaltyAnalytics() {
    try {
        const res = await fetch('/api/analytics/loyalty');
        const data = await res.json();
        const list = document.getElementById('loyalty-list');
        if (!list) return;
        
        if (data.length === 0) {
            renderEmptyState('loyalty-list', 'Seeking repeating guests...', 'fa-star');
            return;
        }

        list.innerHTML = data.map(item => {
            const avatar = item.photo
                ? `<img src="${item.photo}" style="width:35px; height:35px; border-radius:50%; object-fit:cover; border:1px solid var(--border);">`
                : `<div style="width:35px; height:35px; background:var(--accent); border-radius:50%; display:flex; align-items:center; justify-content:center; color:white; font-size:0.8rem;"><i class="fas fa-crown"></i></div>`;
            return `
                <div style="padding:1rem; background:var(--nav-hover); border-radius:16px; border:1px solid var(--border); border-left:4px solid var(--accent); display:flex; justify-content:space-between; align-items:center;">
                    <div style="display:flex; align-items:center; gap:12px;">
                        ${avatar}
                        <div>
                            <div style="font-weight:800; font-size:0.95rem;">${item.name} <span style="font-size:0.7rem; opacity:0.6; font-weight:normal;">(ID ${item.id})</span></div>
                            <div style="font-size:0.65rem; color:var(--text-muted); font-weight:700;">Last Seen: ${item.last_visit}</div>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-weight:800; color:var(--accent); font-size:1.2rem; letter-spacing:-0.5px;">${item.visits}</div>
                        <div style="font-size:0.6rem; font-weight:800; text-transform:uppercase; letter-spacing:0.5px;">Visits</div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) { console.error("Loyalty Load Error", e); document.getElementById('loyalty-list') && (document.getElementById('loyalty-list').innerHTML = '<div class="empty-state"><i class="fas fa-exclamation-triangle" style="color:var(--red);"></i><p style="color:var(--text-muted);">Failed to load loyalty data.</p></div>'); }
}

let currentVisitorScope = 'day';

async function loadVisitorAnalytics(scope) {
    currentVisitorScope = scope || 'day';
    try {
        const res = await fetch(`/api/analytics/visitors?scope=${currentVisitorScope}`);
        const data = await res.json();

        document.getElementById('visitor-total').innerText = data.total_unique_visitors || 0;
        document.getElementById('visitor-new').innerText = data.new_faces || 0;
        document.getElementById('visitor-returning').innerText = data.returning_customers || 0;
        document.getElementById('visitor-regular').innerText = data.regular_customers || 0;

        // Frequency chart
        renderFrequencyChart(data.frequency_distribution || {});

        // Daily breakdown (month only)
        const dailyCard = document.getElementById('visitor-daily-card');
        const dailyBody = document.getElementById('visitor-daily-body');
        if (currentVisitorScope === 'month' && data.daily_breakdown && data.daily_breakdown.length > 0) {
            dailyCard.style.display = 'block';
            dailyBody.innerHTML = data.daily_breakdown.map(d => `
                <tr><td>${d.date}</td><td><b>${d.unique_visitors}</b></td><td>${d.new_faces}</td><td>${d.total_events}</td></tr>
            `).join('');
        } else {
            dailyCard.style.display = 'none';
        }
    } catch (e) {
        console.error("Visitor Analytics Load Error", e);
        document.getElementById('visitor-total').innerText = 'ERR';
        document.getElementById('visitor-new').innerText = 'ERR';
        document.getElementById('visitor-returning').innerText = 'ERR';
        document.getElementById('visitor-regular').innerText = 'ERR';
    }
}

function setVisitorScope(scope) {
    document.querySelectorAll('.scope-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('visitor-scope-' + scope).classList.add('active');
    loadVisitorAnalytics(scope);
}

function renderFrequencyChart(freq) {
    const chart = document.getElementById('visitor-frequency-chart');
    const labels = document.getElementById('visitor-frequency-labels');
    if (!chart) return;

    const keys = Object.keys(freq).sort((a, b) => parseInt(a) - parseInt(b));
    if (keys.length === 0) {
        chart.innerHTML = '<div style="width:100%; text-align:center; color:var(--text-muted); font-size:0.75rem; padding:2rem 0;">No frequency data yet</div>';
        if (labels) labels.innerHTML = '';
        return;
    }

    const maxVal = Math.max(...keys.map(k => freq[k]));
    chart.innerHTML = keys.map(k => {
        const pct = (freq[k] / maxVal) * 80;
        const color = parseInt(k) >= 2 ? 'var(--green)' : 'var(--accent)';
        return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; height:100%;">
            <div style="width:80%; background:${color}; border-radius:6px 6px 0 0; height:${pct}%; min-height:4px; transition:0.3s;" title="${freq[k]} visitor(s)"></div>
        </div>`;
    }).join('');

    if (labels) {
        labels.innerHTML = keys.map(k => `<div style="flex:1; text-align:center;">${k}</div>`).join('');
    }
}

// --- CHATBOT LOGIC ---
function toggleChat() {
    const chat = document.querySelector('.chat-container');
    chat.style.display = chat.style.display === 'flex' ? 'none' : 'flex';
}

function formatChatMessage(text) {
    if (!text) return '';
    let formatted = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/(?:^|\n)\s*[\*•-]\s+(.+)/g, '<br>• $1')
        .replace(/\n/g, '<br>');
    if (formatted.startsWith('<br>')) formatted = formatted.substring(4);
    return formatted;
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input-text');
    const box = document.getElementById('chat-box');
    const query = input.value.trim();
    if (!query) return;

    box.innerHTML += `<div class="msg user">${query}</div>`;
    input.value = '';
    box.scrollTop = box.scrollHeight;

    try {
        const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query }) });
        const data = await res.json();
        box.innerHTML += `<div class="msg ai">${formatChatMessage(data.response)}</div>`;
    } catch (e) { box.innerHTML += `<div class="msg ai">Connection error.</div>`; }
    box.scrollTop = box.scrollHeight;
}

async function loadStaffDirectory() {
    const list = document.getElementById('staff-directory-list');
    if (!list) return;
    try {
        const res = await fetch('/api/staff/all');
        const data = await res.json();
        
        if (data.length === 0) {
            renderEmptyState('staff-directory-list', 'No staff registered yet.', 'fa-user-friends');
            return;
        }

        list.innerHTML = data.map(s => {
const avatar = s.photo
    ? `<img src="${s.photo}" style="width:60px; height:70px; border-radius:12px; object-fit:contain; border:2px solid var(--border); background:var(--surface); cursor:pointer;" onclick="window.open('${s.photo}', '_blank')" title="Click to enlarge">`
    : `<div style="width:60px; height:70px; background:var(--primary); color:white; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:1.5rem;"><i class="fas fa-user-tie"></i></div>`;
            return `
            <div class="staff-card" style="display:flex; justify-content:space-between; align-items:center; padding:1.5rem; background:var(--card-bg); border-radius:16px; border:1px solid var(--border); box-shadow:var(--shadow);">
                <div style="display:flex; align-items:center; gap:1.5rem;">
                    ${avatar}
                    <div>
                        <div style="font-weight:800; font-size:1.1rem; color:var(--primary);">${s.name}</div>
                        <div style="font-size:0.75rem; color:var(--text-muted); font-weight:700;">${s.role.toUpperCase()} • ${s.shift.toUpperCase()} SHIFT</div>
                    </div>
                </div>
                <div style="display:flex; gap:10px;">
                    <button class="btn-delete" onclick="deleteStaff('${s.id}')"><i class="fas fa-trash"></i></button>
                    <button class="btn-primary" style="padding:10px 20px; font-size:0.75rem; border-radius:10px;" onclick="editStaff('${s.id}', '${s.name}', '${s.role}', '${s.shift_time}', '${s.shift}', ${s.rate}, '${s.salary_type}')">Manage</button>
                </div>
            </div>
        `}).join('');
    } catch (e) {
        list.innerHTML = `<div class="empty-state"><i class="fas fa-exclamation-triangle"></i><p>Failed to load staff directory. Please refresh.</p></div>`;
    }
}

async function deleteStaff(id) {
    if (!confirm("Remove this staff member? This will stop AI tracking for them.")) return;
    await fetch(`/api/staff/delete/${id}`, { method: 'DELETE' });
    loadStaffDirectory();
}

// --- SETTINGS MANAGEMENT ---
async function loadEmailSettings() {
    try {
        const res = await fetch('/api/settings/emails');
        const data = await res.json();
        if (document.getElementById('owner-email')) document.getElementById('owner-email').value = data.owner_email || '';
        if (document.getElementById('sender-email')) document.getElementById('sender-email').value = data.sender_email || '';
        if (document.getElementById('sender-password')) document.getElementById('sender-password').value = data.sender_password || '';
        if (document.getElementById('wellness-threshold')) document.getElementById('wellness-threshold').value = data.wellness_threshold || '4';
        if (document.getElementById('late-grace-minutes')) document.getElementById('late-grace-minutes').value = data.late_grace_minutes || '10';
    } catch (e) { console.error("Error loading email settings", e); }
}

async function saveEmailSettings() {
    const data = {
        owner_email: document.getElementById('owner-email').value,
        sender_email: document.getElementById('sender-email').value,
        sender_password: document.getElementById('sender-password').value
    };
    try {
        const res = await fetch('/api/settings/emails', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) alert("✅ Email configuration saved successfully!");
    } catch (e) { alert("❌ Error saving email configuration."); }
}

// --- CAMERA SETTINGS ---
async function loadCameraSettings() {
    try {
        const res = await fetch('/api/settings/emails');
        const data = await res.json();
        const urlEl = document.getElementById('cam-rtsp-url');
        if (urlEl) urlEl.value = data.rtsp_url || '';
        if (urlEl && !urlEl.value) urlEl.placeholder = 'rtsp://100.x.x.x:8554/cam (Tailscale IP)';
        const qualityEl = document.getElementById('cam-quality');
        if (qualityEl) {
            qualityEl.value = data.camera_preset || '720p';
        }
    } catch (e) { console.error("Error loading camera settings", e); }
}

async function saveCameraSettings() {
    const url = document.getElementById('cam-rtsp-url').value.trim();
    const preset = document.getElementById('cam-quality').value;
    if (!url) { alert('Please enter a valid RTSP URL before saving.'); return; }
    const btn = event && event.target ? event.target : document.querySelector('[onclick="saveCameraSettings()"]');
    const origText = btn ? btn.innerHTML : '';
    if (btn) { btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...'; btn.disabled = true; }
    const data = { rtsp_url: url, camera_preset: preset };
    try {
        // Use dedicated camera endpoint (not emails) so it also restarts MediaMTX
        const res = await fetch('/api/settings/camera', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            if (btn) { btn.innerHTML = '<i class="fas fa-check"></i> Saved!'; }
            setTimeout(() => { if (btn) { btn.innerHTML = origText; btn.disabled = false; } }, 2500);
            setTimeout(() => refreshCamera(), 3000);
        } else {
            const err = await res.text();
            alert('Error saving: ' + err);
            if (btn) { btn.innerHTML = origText; btn.disabled = false; }
        }
    } catch (e) {
        alert('Network error saving camera settings.');
        if (btn) { btn.innerHTML = origText; btn.disabled = false; }
    }
}

// --- PTZ CONTROLS ---
let ptzDir = 'Up';
let ptzStatusTimer = null;

function ptzStatus(msg) {
    const st = document.getElementById('ptz-status');
    if (!st) return;
    st.textContent = '⚠ PTZ: ' + (msg || 'failed');
    st.style.display = 'block';
    st.style.background = 'rgba(239,68,68,0.9)';
    clearTimeout(ptzStatusTimer);
    ptzStatusTimer = setTimeout(() => { st.style.display = 'none'; }, 5000);
}

function ptzStartTouch(e, direction) {
    if (e && e.preventDefault) e.preventDefault();
    ptzStart(direction);
}

function ptzStart(direction) {
    ptzDir = direction;
    fetch('/api/camera/ptz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction, action: 'start' })
    }).then(r => r.json()).then(d => {
        if (d.status !== 'success') ptzStatus(d.message);
    }).catch(e => { ptzStatus(String(e)); console.warn('[PTZ]', e); });
}

function ptzStop() {
    fetch('/api/camera/ptz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction: ptzDir, action: 'stop' })
    }).then(r => r.json()).then(d => {
        if (d.status !== 'success') ptzStatus(d.message);
    }).catch(e => console.warn('[PTZ]', e));
}

async function diagnosePtz() {
    const st = document.getElementById('ptz-status');
    const show = (txt, color) => { if (st) { st.textContent = txt; st.style.display = 'block'; st.style.background = color; } };
    show('Diagnosing PTZ...', 'rgba(245,158,11,0.9)');
    try {
        const r = await fetch('/api/camera/ptz/diagnose');
        const d = await r.json();
        const lines = d.targets.map(t => {
            const reach = (t.tcp80 || t.tcp8080) ? 'REACHABLE' : 'UNREACHABLE';
            const auth = Object.entries(t.cgi_auth || {}).map(([k, v]) => `${k}: ${v}`).join('  ');
            return `${t.host} (user: ${t.user}) → ${reach}\n   CGI → ${auth}`;
        });
        alert('PTZ Diagnosis (generated ' + d.generated + ')\n\n' +
            lines.join('\n\n') +
            '\n\nREACHABLE = server can open a TCP connection to the camera.\n' +
            'CGI 200 = camera responds to PTZ commands. If the physical camera ' +
            '(192.168.x.x) shows UNREACHABLE, approve the subnet route in the ' +
            'Tailscale admin console and run "tailscale up --accept-routes" on this server.');
        st.style.display = 'none';
    } catch (e) {
        show('PTZ diagnosis failed', 'rgba(239,68,68,0.9)');
        console.warn('[PTZ-diagnose]', e);
    }
}

async function testPtz() {
    const btn = document.getElementById('btn-test-ptz');
    if (btn) { btn.innerHTML = '⏳ Testing...'; btn.disabled = true; }
    try {
        const r = await fetch('/api/camera/ptz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ direction: 'Up', action: 'start' })
        });
        const d = await r.json();
        if (d.status === 'success') {
            setTimeout(() => {
                fetch('/api/camera/ptz', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ direction: 'Up', action: 'stop' })
                });
            }, 1000);
            alert('✅ PTZ working! Camera moved Up.');
        } else {
            alert('❌ PTZ failed: ' + (d.message || 'Unknown error'));
        }
    } catch (e) {
        alert('❌ PTZ error: ' + e.message);
    }
    if (btn) { btn.innerHTML = 'Test PTZ'; btn.disabled = false; }
}

async function testCameraConnection() {
    const url = document.getElementById('cam-rtsp-url').value;
    if (!url) { alert("Enter a camera URL first"); return; }
    const resultEl = document.getElementById('cam-test-result');
    resultEl.innerHTML = '⏳ Testing connection...';
    resultEl.style.color = 'var(--text-muted)';
    try {
        const res = await fetch('/api/camera/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        const data = await res.json();
        if (data.status === 'success') {
            resultEl.innerHTML = '✅ ' + data.message;
            resultEl.style.color = 'var(--green)';
        } else {
            resultEl.innerHTML = '❌ ' + data.message;
            resultEl.style.color = 'var(--red)';
        }
    } catch (e) {
        resultEl.innerHTML = '❌ Connection test failed';
        resultEl.style.color = 'var(--red)';
    }
}

async function loadEvents() {
    const list = document.getElementById('event-list');
    if (!list) return;
    const res = await fetch('/api/events/all');
    const data = await res.json();
    list.innerHTML = data.map(e => `
        <div style="padding:10px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-weight:800; color:var(--red);">🔥 ${e.intensity}</span> 
                <span style="font-weight:600; margin-left:5px;">${e.date}</span>: ${e.type}
            </div>
            <button onclick="deleteEvent('${e.date}')" style="background:none; border:none; color:var(--text-muted); cursor:pointer;"><i class="fas fa-times"></i></button>
        </div>
    `).join('') || '<div style="opacity:0.5; text-align:center; padding:10px;">No peak events scheduled.</div>';
}

async function addNewEvent() {
    const date = document.getElementById('new-event-date').value;
    const type = document.getElementById('new-event-type').value || "Peak Traffic";
    const intensity = document.getElementById('new-event-intensity').value;
    if (!date) return;
    await fetch('/api/events/add', { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify({ date, type, intensity }) 
    });
    loadEvents();
}

async function deleteEvent(date) {
    if(!confirm("Remove this event?")) return;
    await fetch(`/api/events/delete/${date}`, { method: 'DELETE' });
    loadEvents();
}

async function editStaff(id, name, role, shift_time, shift, rate, salType) {
    const newShiftTime = prompt("Enter Shift Start Time (HH:MM, e.g. 09:00):", shift_time);
    const newRate = prompt("Enter new Rate/Salary (Rs.):", rate);
    const newShift = prompt("Enter Shift Type (Morning/Evening):", shift);
    const newType = prompt("Enter Salary Type (Monthly/Hourly):", salType);
    if (!newShiftTime || !newRate || !newShift || !newType) return;
    
    await fetch(`/api/staff/update/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, role, shift_time: newShiftTime, shift: newShift, rate: parseInt(newRate), salary_type: newType })
    });
    loadStaffDirectory();
}

// --- STATUS & PERFORMANCE ---
async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        if (res.status === 401) { window.location.href = '/'; return; }
        const data = await res.json();
        
        const splash = document.getElementById('init-splash');
        const statusText = document.getElementById('init-status-text');
        
        if (data.init_status && statusText) statusText.innerText = data.init_status;
        
        if (data.initializing) {
            // Keep splash
            const skipBtn = document.getElementById('skip-init-btn');
            if (skipBtn && !window.initStartTime) window.initStartTime = Date.now();
            if (skipBtn && Date.now() - window.initStartTime > 10000) skipBtn.style.display = 'block';
        } else {
            if (splash && splash.style.display !== 'none') {
                splash.style.opacity = '0';
                setTimeout(() => splash.style.display = 'none', 500);
            }
        }
        
        // Update stats (Now runs even if initializing=True in backend)
        if (document.getElementById('active-count')) document.getElementById('active-count').innerText = data.count;
        if (document.getElementById('person-count')) document.getElementById('person-count').innerText = `${data.count} ACTIVE`;
        if (document.getElementById('avg-efficiency')) document.getElementById('avg-efficiency').innerText = `${data.avg_efficiency}%`;
        if (document.getElementById('incidents-today')) document.getElementById('incidents-today').innerText = data.incidents_today;
        if (document.getElementById('monthly-customers')) document.getElementById('monthly-customers').innerText = data.monthly_customers;
        if (document.getElementById('repeat-customers')) document.getElementById('repeat-customers').innerText = data.repeat_customers;
        if (data.today_customers !== undefined && document.getElementById('customer-time')) {
            const mins = data.today_customer_minutes || 0;
            const count = data.today_customers || 0;
            document.getElementById('customer-time').innerText = `${count} today · ${mins} min`;
        }
        
        // Update Roster
        if (data.roster) renderShiftRoster(data.roster);

        // Update Active Staff Badges
        const activeList = document.getElementById('active-staff-list');
        if (activeList && data.active_list) {
            activeList.innerHTML = data.active_list.map(s => `
                <div class="staff-badge">
                    <i class="fas fa-circle" style="color:var(--green)"></i>
                    ${s.name} <span style="opacity:0.6; font-size:0.6rem;">(${s.zone})</span>
                </div>
            `).join('');
        }

        if (data.new_alert) triggerSecurityAlert(data.alert_details);
    } catch (e) {}
}

function renderShiftRoster(roster) {
    const list = document.getElementById('shift-roster-list');
    if (!list) return;
    list.innerHTML = roster.map(r => `
        <div class="shift-card shift-${r.shift.toLowerCase()}">
            <div>
                <div style="font-weight:800; font-size:0.85rem;">${r.name}</div>
                <div style="font-size:0.7rem; opacity:0.8;">${r.role}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-weight:800; font-size:0.7rem; color:var(--primary);">${r.shift}</div>
                <div style="font-size:0.65rem; opacity:0.8;">Starts: ${r.time}</div>
            </div>
        </div>
    `).join('');
}

function triggerSecurityAlert(details) {
    const overlay = document.getElementById('security-breach-overlay');
    const audio = document.getElementById('alert-sound');
    const detailsDiv = document.getElementById('breach-details');
    
    if (details && detailsDiv) detailsDiv.innerHTML = `Tracked Item: <b>${details.name}</b><br>Zone: <b>${details.zone}</b>`;
    if (overlay) overlay.classList.remove('hidden');
    if (audio) { audio.currentTime = 0; audio.play().catch(e => console.log("Audio play blocked")); }
    
    speakAlert(details.name, details.zone);
    sendBrowserNotification(details.name, details.zone);
}

function speakAlert(name, zone) {
    if (!window.speechSynthesis) return;
    const msg = new SpeechSynthesisUtterance(`Warning! Unauthorized entry detected in ${zone}. Name identified as ${name}.`);
    msg.rate = 0.9; msg.pitch = 1;
    window.speechSynthesis.speak(msg);
}

function sendBrowserNotification(name, zone) {
    if (Notification.permission === "granted") {
        new Notification("⚠️ SECURITY BREACH", {
            body: `${name} detected in restricted area: ${zone}`,
            icon: "/static/img/alert-icon.png"
        });
    }
}

function acknowledgeAlert() {
    const overlay = document.getElementById('security-breach-overlay');
    const audio = document.getElementById('alert-sound');
    if (overlay) overlay.classList.add('hidden');
    if (audio) audio.pause();
    if (window.speechSynthesis) window.speechSynthesis.cancel();
}

function skipInitialization() {
    const splash = document.getElementById('init-splash');
    if (splash) {
        splash.style.opacity = '0';
        setTimeout(() => splash.style.display = 'none', 500);
    }
}

async function loadAttendanceReports() {
    const filter = document.getElementById('report-filter');
    const dateFilter = document.getElementById('report-date-filter');
    let url = '/api/reports/attendance';
    let tbody = document.getElementById('attendance-report-body');
    if (!tbody) return;

    if (dateFilter && dateFilter.value) {
        url = `/api/reports/attendance?date=${dateFilter.value}`;
    } else if (filter && filter.value) {
        const [year, month] = filter.value.split('-');
        url = `/api/reports/attendance?month=${month}&year=${year}`;
    }
    
    try {
        const res = await fetch(url);
        const data = await res.json();
        
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:4rem; color:var(--text-muted); font-weight:700;">NO ATTENDANCE RECORDS FOUND FOR THIS PERIOD</td></tr>';
            return;
        }

        let totalEff = 0;
        let totalLates = 0;

        tbody.innerHTML = data.map(r => {
            totalEff += parseFloat(r.efficiency);
            if (r.status === 'Late') totalLates++;
            return `<tr><td>${r.date}</td><td><b>${r.name}</b></td><td>${r.role}</td><td>${r.in}</td><td>${r.out}</td><td>${r.hours}h</td><td><b style="color:var(--primary);">${r.efficiency}%</b></td><td><span class="status-badge ${r.status==='Completed'?'status-ontime':(r.status==='Late'?'status-late':'status-active')}">${r.status}</span></td></tr>`;
        }).join('');

        const hEl = document.getElementById('report-total-hours');
        const lEl = document.getElementById('report-total-lates');
        const cEl = document.getElementById('report-total-efficiency');
        const avgEff = (totalEff / (data.length || 1)).toFixed(1);
        if (hEl) hEl.innerText = `${avgEff}% Activity`;
        if (lEl) lEl.innerText = totalLates;
        if (cEl) cEl.innerText = `${avgEff}%`;
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:4rem; color:var(--red);">Unable to synchronize report data.</td></tr>';
    }
}

async function loadSynergyMetrics() {
    const grid = document.getElementById('analytics-grid');
    if (!grid) return;
    try {
        const res = await fetch('/api/analytics/synergy');
        if (!res.ok) {
            grid.innerHTML = '<div class="standard-card">No metric data</div>';
            return;
        }
        const data = await res.json();
        
        if (!data.metrics || data.metrics.length === 0) {
            grid.innerHTML = '<div class="standard-card">No metric data</div>';
            return;
        }

        grid.innerHTML = data.metrics.slice(0, 4).map(m => `
            <div class="standard-card" style="align-items:center; text-align:center;">
                <span style="font-size:0.7rem; font-weight:800; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">${m.label}</span>
                <div style="font-size:2.2rem; font-weight:800; color:var(--primary); margin-top:5px; letter-spacing:-1px;">${m.value}</div>
            </div>
        `).join('');
    } catch (e) {
        console.error("Synergy Metrics Error", e);
        grid.innerHTML = '<div class="standard-card">No metric data</div>';
    }
}

async function loadPerformanceRankings() {
    const tbody = document.getElementById('performance-ranking-body');
    if (!tbody) return;
    try {
        const res = await fetch('/api/analytics/performance');
        const data = await res.json();
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:4rem; color:var(--text-muted); font-weight:700;">NO PERFORMANCE INTELLIGENCE AVAILABLE YET</td></tr>';
            return;
        }
        tbody.innerHTML = data.map((r, i) => {
            let level = 'Exceptional';
            let color = 'var(--green)';
            if (r.score < 40) { level = 'Needs Improvement'; color = 'var(--red)'; }
            else if (r.score < 70) { level = 'Consistent'; color = 'var(--accent)'; }
            
            return `
                <tr>
                    <td><span style="font-weight:800; font-size:1.1rem; color:var(--primary);">#${i+1}</span></td>
                    <td><b>${r.name}</b></td>
                    <td>${r.role}</td>
                    <td>
                        <div style="display:flex; align-items:center; gap:10px;">
                            <div style="flex:1; height:6px; background:var(--nav-hover); border-radius:10px; overflow:hidden;">
                                <div style="width:${r.score}%; height:100%; background:${color};"></div>
                            </div>
                            <span style="font-weight:800; font-size:0.8rem; width:45px;">${r.score}%</span>
                        </div>
                    </td>
                    <td><span class="status-badge" style="background:${color}15; color:${color}; border:1px solid ${color}30;">${level}</span></td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:4rem; color:var(--red);">Performance data synchronization failed.</td></tr>';
    }
}

async function loadSalaryAdmin() {
    const tbody = document.getElementById('salary-admin-body');
    if (!tbody) return;
    try {
        const res = await fetch('/api/staff/all');
        const data = await res.json();
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:4rem; color:var(--text-muted); font-weight:700;">NO STAFF REGISTERED</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(r => `
            <tr>
                <td><b>${r.name}</b></td>
                <td>${r.role}</td>
                <td><span class="status-badge" style="background:var(--nav-hover); color:var(--text); border:none;">${r.salary_type || 'Monthly'}</span></td>
                <td style="font-weight:800; color:var(--accent);">Rs. ${r.rate.toLocaleString()}</td>
                <td><span style="font-size:0.75rem; font-weight:700; color:var(--primary);">${r.shift}</span></td>
            </tr>
        `).join('');
    } catch (e) {
        console.error("Salary Load Error", e);
    }
}

function renderAnalyzeButton() {
    const container = document.getElementById('optimization-suggestions');
    if (!container) return;
    container.innerHTML = `
        <div onclick="loadShiftOptimization()" style="padding:20px; border:2px dashed var(--accent); border-radius:16px; text-align:center; cursor:pointer; transition:0.3s; background:var(--nav-hover);" onmouseover="this.style.background='var(--border)'" onmouseout="this.style.background='var(--nav-hover)'">
            <i class="fas fa-magic" style="font-size:2rem; color:var(--accent); margin-bottom:10px;"></i>
            <p style="font-weight:800; font-size:0.85rem; color:var(--accent); margin:0;">Analyze Now</p>
            <p style="font-size:0.7rem; color:var(--text-muted); margin-top:5px;">Click to get AI-powered shift suggestions</p>
        </div>
    `;
}

async function loadShiftOptimization() {
    const chart = document.getElementById('optimization-chart');
    const suggest = document.getElementById('optimization-suggestions');
    if (!chart || !suggest) return;
    
    suggest.innerHTML = '<div style="text-align:center; padding:2rem; color:var(--text-muted);"><i class="fas fa-spinner fa-spin" style="font-size:1.5rem; margin-bottom:10px;"></i><br>AI is analyzing your staffing patterns...</div>';
    
    try {
        const res = await fetch('/api/analytics/optimization');
        const data = await res.json();
        
        // Render Chart
        if (data.data.every(item => item.activity === 0)) {
            chart.innerHTML = '<div style="width:100%; height:100%; display:flex; align-items:center; justify-content:center; color:var(--text-muted); font-size:0.75rem; font-weight:700; letter-spacing:1px;">WAITING FOR PATTERN DATA</div>';
        } else {
            const max = Math.max(...data.data.map(d => d.activity)) || 1;
            chart.innerHTML = data.data.map(item => {
                let color = 'var(--primary-light)'; 
                if (item.activity > 75) color = 'var(--red)'; 
                if (item.activity < 30) color = 'var(--text-muted)'; 
                
                return `<div onmouseenter="showTooltip(event, '${item.hour}:00 - ${item.activity}% activity')" onmouseleave="hideTooltip()" 
                             style="flex:1; height:${(item.activity/max)*100}%; background:${color}; border-radius:4px 4px 0 0; transition:0.3s; cursor:pointer;"></div>`;
            }).join('');
        }
        
        // Render Suggestions
        if (data.suggestions.length === 0) {
            renderEmptyState('optimization-suggestions', 'AI analyzing shift patterns...', 'fa-magic');
        } else {
            suggest.innerHTML = data.suggestions.map(s => `
                <div style="padding:15px; border-radius:16px; background:var(--nav-hover); border:1px solid var(--border); border-left:4px solid ${s.type==='PEAK TRAFFIC'?'var(--red)':'var(--green)'};">
                    <div style="font-weight:800; font-size:0.7rem; color:var(--text-muted); margin-bottom:5px; text-transform:uppercase;">${s.time}</div>
                    <div style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
                        <span style="font-weight:800; color:${s.type==='PEAK TRAFFIC'?'var(--red)':'var(--green)'}; font-size:0.85rem;">${s.advice}</span>
                        <span style="font-size:0.65rem; color:var(--text-muted); font-weight:700;">${s.reason}</span>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) { console.error("Optimization Load Error", e); }
}

async function saveWellnessSettings() {
    const wellness = document.getElementById('wellness-threshold').value;
    const grace = document.getElementById('late-grace-minutes').value;
    await fetch('/api/settings/emails', { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify({ wellness_threshold: wellness, late_grace_minutes: grace }) 
    });
    alert("✅ Staff policies updated!");
}

// --- FACE ENROLLMENT WIZARD ---
let enrollmentCaptures = [];
const CAPTURE_STEPS = [
    { heading: "Capture 1: Look Straight", instruction: "Look directly at the camera with your face centered", key: "straight" },
    { heading: "Capture 2: Turn Left", instruction: "Turn your head slightly to the left", key: "left" },
    { heading: "Capture 3: Turn Right", instruction: "Turn your head slightly to the right", key: "right" },
    { heading: "Capture 4: Tilt Up", instruction: "Slightly tilt your face upward", key: "up" },
    { heading: "Capture 5: Neutral Smile", instruction: "Look straight with a natural smile", key: "smile" }
];
let currentCaptureStep = 0;

function showEnrollModal() {
    enrollmentCaptures = [];
    currentCaptureStep = 0;
    document.getElementById('enroll-modal').style.display = 'block';
    document.getElementById('overlay').style.display = 'block';
    goToStep(1);
}

function handleImageUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    
    if (files.length < 4) {
        alert("Please upload at least 4 pictures.");
        return;
    }

    enrollmentCaptures = [];
    let loadedCount = 0;

    for (let i = 0; i < files.length; i++) {
        const reader = new FileReader();
        reader.onload = function(e) {
            enrollmentCaptures.push(e.target.result);
            loadedCount++;
            if (loadedCount === files.length) {
                goToStep(3); // skip straight to review
            }
        };
        reader.readAsDataURL(files[i]);
    }
}

function hideEnrollModal() {
    stopCaptureStream();
    document.getElementById('enroll-modal').style.display = 'none';
    document.getElementById('overlay').style.display = 'none';
}

function goToStep(step) {
    // Update step dots
    for (let i = 1; i <= 3; i++) {
        const dot = document.getElementById('step-dot-' + i);
        dot.classList.toggle('active', i === step);
        dot.classList.toggle('done', i < step);
    }
    document.getElementById('enroll-step-1').style.display = step === 1 ? 'block' : 'none';
    document.getElementById('enroll-step-2').style.display = step === 2 ? 'block' : 'none';
    document.getElementById('enroll-step-3').style.display = step === 3 ? 'block' : 'none';

    if (step === 2) {
        startCaptureStream();
        resetCaptureStep();
    } else if (step === 3) {
        stopCaptureStream();
        showReview();
    } else {
        stopCaptureStream();
    }
}

let captureAnimFrame = null;

function startCaptureStream() {
    const canvas = document.getElementById('capture-canvas');
    const img = document.getElementById('video-feed');
    const webrtcVideo = document.getElementById('webrtc-video');
    const hlsVideo = document.getElementById('hls-video');
    if (!canvas || !img) return;
    const ctx = canvas.getContext('2d');
    if (captureAnimFrame) cancelAnimationFrame(captureAnimFrame);

    function getActiveSource() {
        if (hlsVideo && hlsVideo.style.display !== 'none' && hlsVideo.readyState >= 2) {
            return hlsVideo;
        }
        if (webrtcVideo && webrtcVideo.style.display !== 'none' && webrtcVideo.readyState >= 2) {
            return webrtcVideo;
        }
        return img;
    }

    function syncCanvasSize() {
        const src = getActiveSource();
        const w = src.videoWidth || src.naturalWidth || 640;
        const h = src.videoHeight || src.naturalHeight || 480;
        canvas.width = w;
        canvas.height = h;
    }

    function frameLoop() {
        const src = getActiveSource();
        const w = src.videoWidth || src.naturalWidth || 640;
        const h = src.videoHeight || src.naturalHeight || 480;
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w;
            canvas.height = h;
        }
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
        captureAnimFrame = requestAnimationFrame(frameLoop);
    }
    syncCanvasSize();
    frameLoop();
}

function stopCaptureStream() {
    if (captureAnimFrame) {
        cancelAnimationFrame(captureAnimFrame);
        captureAnimFrame = null;
    }
    const canvas = document.getElementById('capture-canvas');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
}

function resetCaptureStep() {
    currentCaptureStep = 0;
    enrollmentCaptures = [];
    renderThumbnails();
    updateCaptureUI();
}

function updateCaptureUI() {
    if (currentCaptureStep >= CAPTURE_STEPS.length) {
        document.getElementById('capture-heading').innerText = 'All Captures Done!';
        document.getElementById('capture-instruction').innerText = 'Review your captures below or proceed.';
        document.getElementById('btn-capture-face').style.display = 'none';
        document.getElementById('btn-capture-done').style.display = 'block';
        document.getElementById('capture-timer').innerText = '';
        return;
    }
    const step = CAPTURE_STEPS[currentCaptureStep];
    document.getElementById('capture-heading').innerText = step.heading;
    document.getElementById('capture-instruction').innerText = step.instruction;
    document.getElementById('btn-capture-face').style.display = 'block';
    document.getElementById('btn-capture-done').style.display = 'none';
    document.getElementById('capture-timer').innerText = `Step ${currentCaptureStep + 1} of ${CAPTURE_STEPS.length}`;
}

function captureFace() {
    if (currentCaptureStep >= CAPTURE_STEPS.length) return;

    const img = document.getElementById('video-feed');
    const webrtcVideo = document.getElementById('webrtc-video');
    const hlsVideo = document.getElementById('hls-video');
    
    let src = img;
    let isVideo = hlsVideo && hlsVideo.style.display !== 'none' && hlsVideo.readyState >= 2;
    if (isVideo) {
        src = hlsVideo;
    } else if (webrtcVideo && webrtcVideo.style.display !== 'none' && webrtcVideo.readyState >= 2) {
        isVideo = true;
        src = webrtcVideo;
    }

    const w = isVideo ? src.videoWidth : src.naturalWidth;
    const h = isVideo ? src.videoHeight : src.naturalHeight;
    if (!src || w === 0 || h === 0) {
        alert('Camera feed not ready. Please wait...');
        return;
    }

    const canvas = document.createElement('canvas');
    const MAX_CAPTURE_DIM = 1920;
    const scale = Math.min(1, MAX_CAPTURE_DIM / Math.max(w, h));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    const ctx = canvas.getContext('2d');
    ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.95);

    // Brief flash feedback
    const badge = document.getElementById('face-status-badge');
    if (badge) {
        badge.style.display = 'inline-block';
        badge.style.color = 'var(--green)';
        badge.innerHTML = '<i class="fas fa-check-circle"></i> Captured!';
        setTimeout(() => {
            badge.style.display = 'none';
        }, 800);
    }

    enrollmentCaptures.push(dataUrl);
    renderThumbnails();
    currentCaptureStep++;
    updateCaptureUI();
}

function renderThumbnails() {
    const container = document.getElementById('capture-thumbnails');
    const total = CAPTURE_STEPS.length;
    let html = '';
    for (let i = 0; i < total; i++) {
        if (i < enrollmentCaptures.length) {
            html += `<img src="${enrollmentCaptures[i]}" class="capture-thumb done" title="Capture ${i+1}">`;
        } else if (i === currentCaptureStep) {
            html += `<div class="capture-thumb pending" style="display:flex; align-items:center; justify-content:center; background:var(--nav-hover); font-size:1.2rem; font-weight:700; color:var(--text-muted);">${i+1}</div>`;
        } else {
            html += `<div class="capture-thumb pending" style="display:flex; align-items:center; justify-content:center; background:var(--nav-hover); font-size:0.8rem; color:var(--text-muted);">${i+1}</div>`;
        }
    }
    container.innerHTML = html;
}

function showReview() {
    const container = document.getElementById('review-captures');
    container.innerHTML = enrollmentCaptures.map((img, i) =>
        `<img src="${img}" class="capture-thumb done" style="width:80px; height:60px;" title="Capture ${i+1}">`
    ).join('');

    document.getElementById('review-name').innerText = document.getElementById('reg-name').value || '—';
    document.getElementById('review-id').innerText = document.getElementById('reg-id').value || '—';
    document.getElementById('review-role').innerText = document.getElementById('reg-role').value;
    document.getElementById('review-shift').innerText = document.getElementById('reg-shift').value;
}

async function submitEnrollment() {
    const btn = document.getElementById('btn-enroll-submit');
    const originalText = btn.innerText;

    const payload = {
        id: document.getElementById('reg-id').value,
        name: document.getElementById('reg-name').value,
        role: document.getElementById('reg-role').value,
        rate: document.getElementById('reg-rate').value,
        salary_type: document.getElementById('reg-salary-type').value,
        shift: document.getElementById('reg-shift').value,
        shift_time: document.getElementById('reg-shift-time').value,
        images: enrollmentCaptures
    };

    if (!payload.id || !payload.name) {
        alert("ID and Name are mandatory.");
        return;
    }
    if (enrollmentCaptures.length < 4) {
        alert("Please capture or upload at least 4 face images.");
        return;
    }

    btn.innerText = "Processing...";
    btn.disabled = true;

    try {
        const res = await fetch('/api/staff/enroll-with-faces', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.status === 'success') {
            alert("Staff Enrolled Successfully!");
            hideEnrollModal();
            loadStaffDirectory();
        } else if (d.message && d.message.includes("No valid face")) {
            const retry = confirm(
                "Face could not be detected in the captures.\n\n" +
                "Tips:\n" +
                "• Ensure the person is standing in front of the camera\n" +
                "• Make sure their face is well-lit and visible\n" +
                "• Remove masks or heavy obstructions\n\n" +
                "Would you like to retake the photos?"
            );
            if (retry) {
                goToStep(2);
            }
        } else {
            alert("Enrollment Failed: " + (d.message || "Unknown error"));
        }
    } catch (e) {
        alert("System Error: Could not connect to backend.");
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
}

async function exportData(format) {
    const filter = document.getElementById('report-filter');
    let month = '', year = '';
    if (filter && filter.value) [year, month] = filter.value.split('-');
    const url = `/api/export/attendance/${format}?month=${month}&year=${year}`;
    window.open(url, '_blank');
}

async function downloadPeriodReport(period, format) {
    const url = `/api/export/custom?period=${period}&format=${format}`;
    window.open(url, '_blank');
}

async function refreshCamera() {
    try {
        const res = await fetch('/api/camera/refresh');
        const data = await res.json();
        if (data.status === 'success') {
            alert("Camera re-synchronization initiated. Please wait a few seconds.");
        }
    } catch (e) {
        alert("Could not contact backend for camera refresh.");
    }
}

function toggleFullscreen() {
    const el = document.getElementById('camera-canvas');
    if (!el) return;
    if (!document.fullscreenElement) {
        el.requestFullscreen().then(() => {
            const icon = document.getElementById('fullscreen-icon');
            if (icon) { icon.classList.remove('fa-expand'); icon.classList.add('fa-compress'); }
        }).catch(() => {});
    } else {
        document.exitFullscreen().then(() => {
            const icon = document.getElementById('fullscreen-icon');
            if (icon) { icon.classList.remove('fa-compress'); icon.classList.add('fa-expand'); }
        });
    }
}

function toggleZoneEditor() {
    isEditingZones = !isEditingZones;
    if (canvas) {
        if (isEditingZones) {
            const wrapper = canvas.parentElement;
            if (wrapper) {
                canvas.width = wrapper.clientWidth;
                canvas.height = wrapper.clientHeight;
            }
            canvas.style.display = 'block';
            zonePoints = [];
            alert("Draw a box by clicking 4 points.");
        } else {
            canvas.style.display = 'none';
        }
    }
}

if (canvas) {
    canvas.addEventListener('mousedown', (e) => {
        if (!isEditingZones) return;
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        const scaleX = 640 / r.width, scaleY = 480 / r.height;
        const mappedX = Math.round(x * scaleX), mappedY = Math.round(y * scaleY);
        zonePoints.push([mappedX, mappedY]);
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || '#4f46e5'; ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI*2); ctx.fill();
        if (zonePoints.length === 4) {
            const name = prompt("Zone Name:");
            const unauthorized = prompt("Unauthorized Roles (comma separated, e.g. AI Intern,Electronics Engineer) or leave empty:");
            if (name) {
                const unauthList = unauthorized ? unauthorized.split(',').map(s => s.trim()) : [];
                fetch('/api/zones/update', { 
                    method: 'POST', 
                    headers: { 'Content-Type': 'application/json' }, 
                    body: JSON.stringify({ name, points: zonePoints, unauthorized: unauthList }) 
                }).then(() => alert("Saved & Monitoring Started!"));
            }
            toggleZoneEditor();
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    updateClock(); setInterval(updateClock, 1000);
    setInterval(fetchStatus, 1500);
    setInterval(loadAttendanceReports, 10000);
    
    // Safety Timeout: Show skip button if initialization takes > 15s regardless of status
    setTimeout(() => {
        const skipBtn = document.getElementById('skip-init-btn');
        if (skipBtn && skipBtn.style.display === 'none') {
            console.log("Initialization taking longer than expected. Enabling skip button.");
            skipBtn.style.display = 'block';
        }
    }, 15000);

    if (Notification.permission !== "granted" && Notification.permission !== "denied") {
        Notification.requestPermission();
    }
});

async function loadCustomerVisitHistory() {
    const tbody = document.getElementById('customer-history-body');
    if (!tbody) return;
    try {
        const res = await fetch('/api/analytics/customers/history');
        if (!res.ok) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:2rem; color:var(--text-muted);">Failed to load history</td></tr>';
            return;
        }
        const data = await res.json();
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:2rem; color:var(--text-muted);">No visit logs recorded yet</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(row => {
            const avatar = row.photo 
                ? `<img src="${row.photo}" style="width:30px; height:30px; border-radius:50%; object-fit:cover; border:1px solid var(--border);">`
                : `<div style="width:30px; height:30px; background:var(--primary); color:white; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:0.6rem;"><i class="fas fa-user"></i></div>`;
            return `<tr>
                <td style="display:flex; align-items:center; gap:8px;">
                    ${avatar}
                    <div>
                        <b>${row.name}</b> <span style="font-size:0.7rem; opacity:0.6;">(ID ${row.id})</span>
                    </div>
                </td>
                <td>${row.time}</td>
                <td>${row.duration || 'N/A'}</td>
                <td><span class="status-badge" style="background:var(--nav-hover); color:var(--text);">${row.zone}</span></td>
            </tr>`;
        }).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:2rem; color:var(--red);">Error loading history</td></tr>';
    }
}
