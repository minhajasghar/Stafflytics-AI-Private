let zonePoints = [];
let isEditingZones = false;
const canvas = document.getElementById('zone-canvas');
const ctx = canvas ? canvas.getContext('2d') : null;

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
            loadSynergyMetrics();
            loadEngagementAnalytics();
            loadWellbeingAnalytics();
            loadLoyaltyAnalytics();
        }
        if (targetId === 'section-performance') loadPerformanceRankings();
        if (targetId === 'section-roi') loadSalaryAdmin();
        if (targetId === 'section-optimization') loadShiftOptimization();
        if (targetId === 'section-settings') { 
            try {
                loadEvents(); 
                loadEmailSettings(); 
                loadTelegramSettings(); 
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
            <div style="display:flex; justify-content:space-between; align-items:center; padding:12px; background:#f8fafc; border-radius:12px; border-left:4px solid var(--accent);">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div>
                        <div style="font-weight:800; font-size:0.9rem;">${item.name}</div>
                        <div style="font-size:0.6rem; color:var(--text-muted); font-weight:700;">${item.interactions} ACTIVE INTERACTIONS</div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:800; color:var(--accent); font-size:1.1rem;">${item.engagement_time}h</div>
                    <div style="font-size:0.6rem; font-weight:800; opacity:0.6;">SERVICE</div>
                </div>
            </div>
        `).join('');
    } catch (e) { console.error("Engagement Load Error", e); }
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
            <div style="display:flex; justify-content:space-between; align-items:center; padding:12px; background:#fff1f2; border-radius:12px; border-left:4px solid var(--red);">
                <div>
                    <div style="font-weight:800; font-size:0.9rem;">${item.name}</div>
                    <div style="font-size:0.65rem; color:var(--text-muted); font-weight:700;">${item.hours}h ON CONTINUOUS DUTY</div>
                </div>
                ${item.needs_break ? '<span style="background:var(--red); color:white; font-size:0.6rem; font-weight:900; padding:4px 8px; border-radius:4px;">NEEDS BREAK</span>' : '<span style="color:var(--green); font-size:0.6rem; font-weight:900;">HEALTHY</span>'}
            </div>
        `).join('');
    } catch (e) { console.error("Wellbeing Load Error", e); }
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

        list.innerHTML = data.map(item => `
            <div style="padding:1rem; background:rgba(255, 215, 0, 0.05); border-radius:16px; border:1px solid #fef3c7; border-left:4px solid var(--accent); display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div style="width:35px; height:35px; background:var(--accent); border-radius:50%; display:flex; align-items:center; justify-content:center; color:white; font-size:0.8rem;"><i class="fas fa-crown"></i></div>
                    <div>
                        <div style="font-weight:800; font-size:0.95rem;">${item.name}</div>
                        <div style="font-size:0.65rem; color:var(--text-muted); font-weight:700;">Last Seen: ${item.last_visit}</div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:800; color:var(--accent); font-size:1.2rem; letter-spacing:-0.5px;">${item.visits}</div>
                    <div style="font-size:0.6rem; font-weight:800; text-transform:uppercase; letter-spacing:0.5px;">Visits</div>
                </div>
            </div>
        `).join('');
    } catch (e) { console.error("Loyalty Load Error", e); }
}

// --- CHATBOT LOGIC ---
function toggleChat() {
    const chat = document.querySelector('.chat-container');
    chat.style.display = chat.style.display === 'flex' ? 'none' : 'flex';
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
        box.innerHTML += `<div class="msg ai">${data.response}</div>`;
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

        list.innerHTML = data.map(s => `
            <div class="staff-card" style="display:flex; justify-content:space-between; align-items:center; padding:1.5rem; background:white; border-radius:16px; border:1px solid #e2e8f0; box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);">
                <div style="display:flex; align-items:center; gap:1.5rem;">
                    <div style="width:50px; height:50px; background:var(--primary); color:white; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:1.2rem;">
                        <i class="fas fa-user-tie"></i>
                    </div>
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
        `).join('');
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
        if (urlEl) urlEl.value = data.rtsp_url || 'rtsp://admin:L2DD2594@192.168.50.137:554/cam/realmonitor?channel=1&subtype=0';
        const qualityEl = document.getElementById('cam-quality');
        const qualityVal = document.getElementById('cam-quality-value');
        if (qualityEl) {
            const q = parseInt(data.camera_quality) || 70;
            qualityEl.value = q;
            if (qualityVal) qualityVal.textContent = q + '%';
        }
    } catch (e) { console.error("Error loading camera settings", e); }
}

async function saveCameraSettings() {
    const data = {
        rtsp_url: document.getElementById('cam-rtsp-url').value,
        camera_quality: document.getElementById('cam-quality').value
    };
    try {
        const res = await fetch('/api/settings/emails', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            alert("✅ Camera settings saved! Reconnecting...");
            await refreshCamera();
        }
    } catch (e) { alert("❌ Error saving camera settings."); }
}

// --- PTZ CONTROLS ---
let ptzDir = 'Up';

function ptzStart(direction) {
    ptzDir = direction;
    fetch('/api/camera/ptz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction, action: 'start' })
    }).then(r => r.json()).then(d => {
        if (d.status !== 'success') console.warn('[PTZ]', d.message);
    }).catch(e => console.warn('[PTZ]', e));
}

function ptzStop() {
    fetch('/api/camera/ptz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction: ptzDir, action: 'stop' })
    }).then(r => r.json()).then(d => {
        if (d.status !== 'success') console.warn('[PTZ]', d.message);
    }).catch(e => console.warn('[PTZ]', e));
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
        <div style="padding:10px; border-bottom:1px solid #f1f5f9; display:flex; justify-content:space-between; align-items:center;">
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
    const newRate = prompt("Enter new Rate/Salary (Rs.):", rate);
    const newShift = prompt("Enter Shift Type (Morning/Evening):", shift);
    const newType = prompt("Enter Salary Type (Monthly/Hourly):", salType);
    if (!newRate || !newShift || !newType) return;
    
    await fetch(`/api/staff/update/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, role, shift_time, shift: newShift, rate: parseInt(newRate), salary_type: newType })
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
        if (data.customer_avg && document.getElementById('customer-time')) document.getElementById('customer-time').innerText = `${data.customer_avg} min`;
        
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
    let month = '', year = '';
    if (filter && filter.value) [year, month] = filter.value.split('-');
    const tbody = document.getElementById('attendance-report-body');
    if (!tbody) return;
    
    try {
        const res = await fetch(`/api/reports/attendance?month=${month}&year=${year}`);
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
                            <div style="flex:1; height:6px; background:#f1f5f9; border-radius:10px; overflow:hidden;">
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
                <td><span class="status-badge" style="background:#f1f5f9; color:var(--text); border:none;">${r.salary_type || 'Monthly'}</span></td>
                <td style="font-weight:800; color:var(--accent);">Rs. ${r.rate.toLocaleString()}</td>
                <td><span style="font-size:0.75rem; font-weight:700; color:var(--primary);">${r.shift}</span></td>
            </tr>
        `).join('');
    } catch (e) {
        console.error("Salary Load Error", e);
    }
}

async function loadShiftOptimization() {
    const chart = document.getElementById('optimization-chart');
    const suggest = document.getElementById('optimization-suggestions');
    if (!chart || !suggest) return;
    
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
                if (item.activity < 30) color = '#cbd5e1'; 
                
                return `<div onmouseenter="showTooltip(event, '${item.hour}:00 - ${item.activity}% activity')" onmouseleave="hideTooltip()" 
                             style="flex:1; height:${(item.activity/max)*100}%; background:${color}; border-radius:4px 4px 0 0; transition:0.3s; cursor:pointer;"></div>`;
            }).join('');
        }
        
        // Render Suggestions
        if (data.suggestions.length === 0) {
            renderEmptyState('optimization-suggestions', 'Calculating staff rhythm...', 'fa-wand-magic-sparkles');
        } else {
            suggest.innerHTML = data.suggestions.map(s => `
                <div style="padding:15px; border-radius:16px; background:${s.type==='PEAK TRAFFIC'?'#fff1f2':'#f0fdf4'}; border:1px solid ${s.type==='PEAK TRAFFIC'?'#fecaca':'#bbf7d0'}; border-left:4px solid ${s.type==='PEAK TRAFFIC'?'var(--red)':'var(--green)'};">
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

async function loadTelegramSettings() {
    try {
        const res = await fetch('/api/settings/emails');
        const data = await res.json();
        if (document.getElementById('tg-token')) document.getElementById('tg-token').value = data.telegram_bot_token || '';
        if (document.getElementById('tg-chatid')) document.getElementById('tg-chatid').value = data.telegram_chat_id || '';
    } catch (e) {}
}

async function saveTelegramSettings() {
    const data = {
        telegram_bot_token: document.getElementById('tg-token').value,
        telegram_chat_id: document.getElementById('tg-chatid').value
    };
    try {
        await fetch('/api/settings/emails', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        alert("✅ Telegram alerts enabled!");
    } catch (e) { alert("❌ Error enabling telegram."); }
}

async function saveWellnessSettings() {
    const val = document.getElementById('wellness-threshold').value;
    await fetch('/api/settings/emails', { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify({ wellness_threshold: val }) 
    });
    alert("✅ Wellness policy updated!");
}

// Sales functionality removed as we don't value people through money.

function showRegisterModal() { document.getElementById('modal').style.display = 'block'; document.getElementById('overlay').style.display = 'block'; }
function hideRegisterModal() { document.getElementById('modal').style.display = 'none'; document.getElementById('overlay').style.display = 'none'; }
async function submitRegistration() {
    const btn = document.getElementById('btn-enroll-submit');
    const originalText = btn.innerText;
    
    try {
        const payload = { 
            id: document.getElementById('reg-id').value, 
            name: document.getElementById('reg-name').value, 
            role: document.getElementById('reg-role').value, 
            rate: document.getElementById('reg-rate').value,
            salary_type: document.getElementById('reg-salary-type').value,
            shift: document.getElementById('reg-shift').value,
            shift_time: document.getElementById('reg-shift-time').value
        };
        
        if (!payload.id || !payload.name) {
            alert("ID and Name are mandatory.");
            return;
        }

        btn.innerText = "Processing... Wait";
        btn.disabled = true;

        const v = document.getElementById('video-feed');
        const c = document.createElement('canvas'); 
        c.width = 640; c.height = 480; 
        if (v) c.getContext('2d').drawImage(v, 0, 0, 640, 480);
        payload.image = c.toDataURL('image/jpeg');

        const res = await fetch('/api/register', { 
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify(payload) 
        });
        
        const d = await res.json();
        if (d.status === 'success') {
            alert("Staff Enrolled Successfully!");
            hideRegisterModal();
            loadStaffDirectory();
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
        ctx.fillStyle = "#4f46e5"; ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI*2); ctx.fill();
        if (zonePoints.length === 4) {
            const name = prompt("Zone Name:");
            const unauthorized = prompt("Unauthorized Roles (comma separated, e.g. Waitstaff,Chef) or leave empty:");
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
