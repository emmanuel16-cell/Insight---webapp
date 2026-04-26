
// ══════════════════════════════════════════════════════════
//  page-show.js  –  InSight Admin
//  Handles: sidenav navigation, topbar name, user dropdown,
//           profile page view/edit, camera modal
// ══════════════════════════════════════════════════════════

let currentUser = null;
let attendanceChart = null;

const sectionTitles = {
    '#home':       'Dashboard',
    '#department': 'Departments',
    '#faculty':    'Faculty',
    '#student':    'Student',
    '#visitor':    'Visitor',
    '#profile':    'My Profile',
    '#subject':    'Subjects',
    '#analytic':   'Analytics',
    '#report':     'Reports',
    '#pending-students': 'Approvals',
    '#gate-logs':   'Gate Activity',
    '#logs':   'Biometric',
};

// ── GLOBAL DROPDOWN CLICK LISTENER ────────────────────────
document.addEventListener('click', e => {
// Table Action Dropdowns
    if (e.target.closest('.action-toggle')) {
        const dropdown = e.target.closest('.action-dropdown');
        const wasOpen = dropdown.classList.contains('open');
// Close all others
        document.querySelectorAll('.action-dropdown.open').forEach(el => el.classList.remove('open'));
        if (!wasOpen) dropdown.classList.add('open');
        return;
    }
// Close table dropdowns if clicking outside
    if (!e.target.closest('.action-dropdown')) {
        document.querySelectorAll('.action-dropdown.open').forEach(el => el.classList.remove('open'));
    }
});

// ── DEPARTMENTS ───────────────────────────────────────────
async function loadDepartmentsTable() {
    const tableBody = document.querySelector('#department-table tbody');
    if (!tableBody) return;

    try {
        const res = await fetch('/api/admin/departments', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to load departments');
        const depts = await res.json();

        tableBody.innerHTML = '';
        if (depts.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="3" css="text-align:center; padding:20px; color:#6b7280;">No departments found. Click "Add Department" to create one.</td></tr>';
            return;
        }

        depts.forEach(d => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
<td>${d.code}</td>
<td>${d.name}</td>
<td class="actions">
    <div class="action-dropdown">
        <button class="action-toggle"><i class="fas fa-ellipsis-v"></i></button>
        <div class="action-menu">
            <button class="edit-action" onclick="editDept('${d.code}')"><i class="fas fa-edit"></i> Edit</button>
            <button class="delete-action" onclick="deleteDept('${d.code}')"><i class="fas fa-trash"></i> Delete</button>
        </div>
    </div>
</td>
`;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        console.error('Departments error:', err);
    }
}

// Modal handling
const deptModal = document.getElementById('add-dept-modal');
const openDeptBtn = document.getElementById('add-dept-btn');
const closeDeptBtns =[
    document.getElementById('closeAddDept'),
    document.getElementById('deptCancel'),
    document.getElementById('addDeptOverlay')
];

openDeptBtn?.addEventListener('click', () => {
    if (deptModal) deptModal.style.display = 'block';
});

closeDeptBtns.forEach(btn => {
    btn?.addEventListener('click', (e) => {
        if (e.target === btn || btn.id === 'closeAddDept' || btn.id === 'deptCancel') {
            if (deptModal) deptModal.style.display = 'none';
        }
    });
});

document.getElementById('deptSubmit')?.addEventListener('click', async () => {
    const code = document.getElementById('deptCode').value.trim();
    const name = document.getElementById('deptName').value.trim();
    const msgEl = document.getElementById('deptMessage');

    if (!code || !name) {
        if (msgEl) {
            msgEl.textContent = 'Please fill in all fields.';
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
        return;
    }

    try {
        const res = await fetch('/api/admin/departments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, name }),
            credentials: 'same-origin'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to add department');

        if (msgEl) {
            msgEl.textContent = 'Department added successfully!';
            msgEl.style.display = 'block';
            msgEl.style.color = '#4ade80';
        }

// Reset and close after a delay
        setTimeout(() => {
            if (deptModal) deptModal.style.display = 'none';
            if (msgEl) msgEl.style.display = 'none';
            document.getElementById('deptCode').value = '';
            document.getElementById('deptName').value = '';
            loadDepartmentsTable();
        }, 1500);

    } catch (err) {
        if (msgEl) {
            msgEl.textContent = err.message;
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
    }
});

// ── PENDING STUDENTS APPROVAL ─────────────────────────────
let pendingRefreshInterval = null;

async function loadPendingStudents() {
    console.log('Fetching pending students...');
    const tableBody = document.querySelector('#pending-students-table tbody');
    const countEl = document.getElementById('pending-count');
    if (!tableBody) {
        console.error('Table body for pending students not found!');
        return;
    }

    try {
        const res = await fetch('/api/admin/pending-students', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to load pending students');
        const students = await res.json();
        console.log('Pending students data:', students);

        if (!Array.isArray(students)) {
            console.error('Pending students data is not an array:', students);
            return;
        }

// Only update DOM if there's actually a change or if it's the first load
// For simplicity, we'll clear and redraw, but we could optimize here
        tableBody.innerHTML = '';
        if (countEl) countEl.textContent = `Showing ${students.length} pending entries.`;

// Update timestamp
        const lastRefreshEl = document.getElementById('last-refresh');
        if (lastRefreshEl) {
            lastRefreshEl.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
        }

        if (students.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="6" css="text-align:center; padding:20px; color:#6b7280;">No pending student approvals at the moment.</td></tr>';
            return;
        }

        students.forEach(s => {
            const tr = document.createElement('tr');
            const firstName = s.first_name || '—';
            const lastName  = s.last_name  || '—';
            tr.innerHTML = `
<td>${s.student_id || '—'}</td>
<td>${firstName} ${lastName}</td>
<td>${s.section || '—'}</td>
<td>${s.contact || '—'}</td>
<td>${s.email || '—'}</td>
<td class="actions">
    <div class="action-dropdown">
        <button class="action-toggle"><i class="fas fa-ellipsis-v"></i></button>
        <div class="action-menu">
            <button class="edit-action" onclick="approveStudent(${s.id}, 'approve')"><i class="fas fa-check"></i> Accept</button>
            <button class="delete-action" onclick="approveStudent(${s.id}, 'remove')"><i class="fas fa-times"></i> Remove</button>
        </div>
    </div>
</td>
`;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        console.error('Pending students error:', err);
    }
}

function startPendingRefresh() {
    if (pendingRefreshInterval) clearInterval(pendingRefreshInterval);
    loadPendingStudents(); // initial load
    pendingRefreshInterval = setInterval(loadPendingStudents, 5000); // 5s refresh
}

function stopPendingRefresh() {
    if (pendingRefreshInterval) {
        clearInterval(pendingRefreshInterval);
        pendingRefreshInterval = null;
    }
}

// ── STUDENT BIOMETRIC LOGS (dynamic tables + polling) ─────
let studentGateLogsInterval = null;
const STUDENT_LOGS_POLL_MS = 5000;

async function loadStudentGateLogs() {
    const tbody = document.querySelector('#gateLogsTable table tbody');
    if (!tbody) return;
    try {
        const res = await fetch('/api/gate-logs', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to load gate logs');
        const logs = await res.json();

        tbody.innerHTML = '';
        if (!Array.isArray(logs) || logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" css="text-align:center; padding:20px; color:#6b7280;">No gate logs found.</td></tr>';
            return;
        }

        logs.forEach(l => {
            const dateVal = l.date || l.check_in || l.check_out || null;
            const dateStr = dateVal ? new Date(dateVal).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—';
            const checkIn = l.check_in ? new Date(l.check_in).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
            const checkOut = l.check_out ? new Date(l.check_out).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
            const uniform = l.has_uniform ? 'Yes' : 'No';
            const idcard = l.has_id_card ? 'Yes' : 'No';

            const tr = document.createElement('tr');
            tr.innerHTML = `
<td>${dateStr}</td>
<td>${checkIn}</td>
<td>${checkOut}</td>
<td>${uniform}</td>
<td>${idcard}</td>
`;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('loadStudentGateLogs error', err);
    }
}

function startStudentGateLogsPolling() {
    if (studentGateLogsInterval) return;
    loadStudentGateLogs();
    studentGateLogsInterval = setInterval(loadStudentGateLogs, STUDENT_LOGS_POLL_MS);
}

function stopStudentGateLogsPolling() {
    if (studentGateLogsInterval) {
        clearInterval(studentGateLogsInterval);
        studentGateLogsInterval = null;
    }
}

async function approveStudent(userId, action) {
    if (!confirm(`Are you sure you want to ${action} this student?`)) return;
    try {
        const res = await fetch(`/api/admin/approve-student/${userId}?action=${action}`, {
            method: 'POST',
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Action failed');
        loadPendingStudents();
    } catch (err) {
        alert(err.message);
    }
}

async function approveAllStudents() {
    if (!confirm('Are you sure you want to approve ALL pending students?')) return;
    try {
        const res = await fetch('/api/admin/approve-all-students', {
            method: 'POST',
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Action failed');
        loadPendingStudents();
    } catch (err) {
        alert(err.message);
    }
}

// ── ACCEPTED STUDENTS ─────────────────────────────────────
async function loadAcceptedStudents() {
    const tableBody = document.querySelector('#accepted-students-table tbody');
    if (!tableBody) return;

    try {
        const res = await fetch('/api/admin/users?role=student', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to load students');
        const students = await res.json();

        tableBody.innerHTML = '';
        if (students.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="5" css="text-align:center; padding:20px; color:#6b7280;">No accepted students yet.</td></tr>';
            return;
        }

        students.forEach(s => {
            const tr = document.createElement('tr');
            const statusClass = s.is_verified ? 'active' : 'inactive';
            const statusText  = s.is_verified ? 'verified' : 'unverified';

            tr.innerHTML = `
<td>${s.student_id || '—'}</td>
<td>${s.first_name || ''} ${s.last_name || ''}</td>
<td>${s.section || '—'}</td>
<td><span class="status ${statusClass}">${statusText}</span></td>
<td class="actions">
    <div class="action-dropdown">
        <button class="action-toggle"><i class="fas fa-ellipsis-v"></i></button>
        <div class="action-menu">
            <button class="edit-action"><i class="fas fa-edit"></i> Edit</button>
            <button class="delete-action" onclick="deleteUser(${s.id}, 'student')"><i class="fas fa-trash"></i> Delete</button>
        </div>
    </div>
</td>
`;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        console.error('Accepted students error:', err);
    }
}

async function deleteUser(userId, roleLabel) {
    if (!confirm(`Are you sure you want to delete this ${roleLabel}?`)) return;
    try {
        const res = await fetch(`/api/admin/users/${userId}`, {
            method: 'DELETE',
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Delete failed');
        if (roleLabel === 'student')    loadAcceptedStudents();
        if (roleLabel === 'instructor') loadFacultyTable();
    } catch (err) {
        alert(err.message);
    }
}

// ── FACULTY ──────────────────────────────────────────────
async function loadFacultyTable() {
    const tableBody = document.querySelector('#faculty-table tbody');
    if (!tableBody) return;

    try {
        const res = await fetch('/api/admin/users?role=instructor', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to load instructors');
        const instructors = await res.json();

        tableBody.innerHTML = '';
        if (instructors.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="7" css="text-align:center; padding:20px; color:#6b7280;">No instructors found.</td></tr>';
            return;
        }

        instructors.forEach(inst => {
            const tr = document.createElement('tr');

// Check if profile is "filled up"
// Criteria: has first_name, last_name, and department
            const isProfileComplete = inst.first_name && inst.last_name && inst.department;
            const statusClass = isProfileComplete ? 'active' : 'inactive';
            const statusText  = isProfileComplete ? 'active' : 'inactive';

            tr.innerHTML = `
<td>${inst.student_id || '—'}</td>
<td>${inst.first_name || ''} ${inst.last_name || ''}</td>
<td>${inst.department || '—'}</td>
<td>${inst.contact || '—'}</td>
<td>${inst.email || '—'}</td>
<td><span class="status ${statusClass}">${statusText}</span></td>
<td class="actions">
    <div class="action-dropdown">
        <button class="action-toggle"><i class="fas fa-ellipsis-v"></i></button>
        <div class="action-menu">
            <button class="delete-action" onclick="deleteUser(${inst.id}, 'instructor')"><i class="fas fa-trash"></i> Remove</button>
        </div>
    </div>
</td>
`;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        console.error('Faculty error:', err);
    }
}

// ── VISITORS ──────────────────────────────────────────────
async function loadVisitorsTable() {
    const tbody = document.querySelector('#visitors-table tbody');
    if (!tbody) return;
    try {
        const res = await fetch('/api/admin/visitors', { credentials: 'same-origin' });
        const visitors = await res.json();
        tbody.innerHTML = '';
        if (!visitors.length) {
            tbody.innerHTML = '<tr><td colspan="8" css="text-align:center; padding:20px;">No visitors recorded today.</td></tr>';
            return;
        }
        visitors.forEach(v => {
            const date = new Date(v.date).toLocaleDateString();
            const timeIn = new Date(v.time_in).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
            const timeOut = v.time_out ? new Date(v.time_out).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '—';

            const action = v.time_out ? '—' : `
<div class="action-dropdown">
    <button class="action-toggle"><i class="fas fa-ellipsis-v"></i></button>
    <div class="action-menu">
        <button class="edit-action" onclick="visitorTimeOut(${v.id})"><i class="fas fa-sign-out-alt"></i> Time Out</button>
    </div>
</div>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
<td>${v.first_name}</td>
<td>${v.last_name}</td>
<td>${v.contact || '—'}</td>
<td>${v.purpose || '—'}</td>
<td>${date}</td>
<td>${timeIn}</td>
<td>${timeOut}</td>
<td class="actions">${action}</td>
`;
            tbody.appendChild(tr);
        });
    } catch (err) { console.error('Visitors error:', err); }
}

async function visitorTimeOut(id) {
    try {
        const res = await fetch(`/api/admin/visitors/${id}/time-out`, { method: 'PUT', credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to time out visitor');
        loadVisitorsTable();
    } catch (err) { alert(err.message); }
}

// ── BLACKLIST ─────────────────────────────────────────────
async function loadBlacklistTable() {
    const tbody = document.querySelector('#blacklist-table tbody');
    if (!tbody) return;
    try {
        const res = await fetch('/api/admin/blacklist', { credentials: 'same-origin' });
        const list = await res.json();
        tbody.innerHTML = '';
        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="7" css="text-align:center; padding:20px;">No blacklist entries.</td></tr>';
            return;
        }
        list.forEach(b => {
            const date = new Date(b.created_at).toLocaleDateString();
            const statusClass = b.status === 'active' ? 'status inactive' : 'status active';

            const action = b.status === 'active' ? `
<div class="action-dropdown">
    <button class="action-toggle"><i class="fas fa-ellipsis-v"></i></button>
    <div class="action-menu">
        <button class="edit-action" onclick="resolveBlacklist(${b.id})"><i class="fas fa-check-circle"></i> Resolve</button>
    </div>
</div>` : '—';

            const tr = document.createElement('tr');
            tr.innerHTML = `
<td>${b.first_name} ${b.last_name}</td>
<td>${b.student_id || '—'}</td>
<td>${b.reason}</td>
<td><span class="severity-${b.severity}">${b.severity.toUpperCase()}</span></td>
<td><span class="${statusClass}">${b.status}</span></td>
<td>${date}</td>
<td class="actions">${action}</td>
`;
            tbody.appendChild(tr);
        });
    } catch (err) { console.error('Blacklist error:', err); }
}

async function resolveBlacklist(id) {
    if (!confirm('Mark this blacklist entry as resolved?')) return;
    try {
        const res = await fetch(`/api/admin/blacklist/${id}/resolve`, { method: 'PUT', credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to resolve entry');
        loadBlacklistTable();
    } catch (err) { alert(err.message); }
}

// ── VIOLATIONS ────────────────────────────────────────────
async function loadViolationsTable() {
    const tbody = document.querySelector('#violations-table tbody');
    if (!tbody) return;
    try {
        const res = await fetch('/api/admin/violations', { credentials: 'same-origin' });
        const list = await res.json();
        tbody.innerHTML = '';
        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="6" css="text-align:center; padding:20px;">No violations reported.</td></tr>';
            return;
        }
        list.forEach(v => {
            const date = new Date(v.created_at).toLocaleString();
            const imgHtml = v.image_path ? `<img src="${v.image_path}" style="height:40px; border-radius:4px; cursor:pointer;" onclick="window.open('${v.image_path}')">` : '—';

            const tr = document.createElement('tr');
            tr.innerHTML = `
<td>${v.student_name || 'Unknown'}</td>
<td>${v.student_id || '—'}</td>
<td>${v.violation_type}</td>
<td>${v.description || '—'}</td>
<td>${date}</td>
<td>${imgHtml}</td>
`;
            tbody.appendChild(tr);
        });
    } catch (err) { console.error('Violations error:', err); }
}

// ── SEARCH FILTERS ───────────────────────────────────────────
document.getElementById('visitor-search')?.addEventListener('input', (e) => {
    const val = e.target.value.toLowerCase();
    document.querySelectorAll('#visitors-table tbody tr').forEach(tr => {
        tr.style.display = tr.textContent.toLowerCase().includes(val) ? '' : 'none';
    });
});

document.getElementById('blacklist-search')?.addEventListener('input', (e) => {
    const val = e.target.value.toLowerCase();
    document.querySelectorAll('#blacklist-table tbody tr').forEach(tr => {
        tr.style.display = tr.textContent.toLowerCase().includes(val) ? '' : 'none';
    });
});

document.getElementById('violation-search')?.addEventListener('input', (e) => {
    const val = e.target.value.toLowerCase();
    document.querySelectorAll('#violations-table tbody tr').forEach(tr => {
        tr.style.display = tr.textContent.toLowerCase().includes(val) ? '' : 'none';
    });
});

// ── VISITOR MODAL ───────────────────────────────────────────
const visitorModal = document.getElementById('addVisitorModal');
const openVisitorBtn = document.getElementById('add-visitor-btn');
const closeVisitorBtn = document.getElementById('closeVisitorModal');
const cancelVisitorBtn = document.getElementById('cancelVisitor');

openVisitorBtn?.addEventListener('click', () => {
    if (visitorModal) visitorModal.style.display = 'block';
});

[closeVisitorBtn, cancelVisitorBtn].forEach(btn => {
    btn?.addEventListener('click', () => {
        if (visitorModal) visitorModal.style.display = 'none';
    });
});

document.getElementById('visitorForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        first_name: document.getElementById('v-firstname').value.trim(),
        last_name: document.getElementById('v-lastname').value.trim(),
        contact: document.getElementById('v-contact').value.trim(),
        purpose: document.getElementById('v-purpose').value.trim()
    };
    try {
        const res = await fetch('/api/admin/visitors', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Failed to register visitor');
        if (visitorModal) visitorModal.style.display = 'none';
        e.target.reset();
        loadVisitorsTable();
    } catch (err) { alert(err.message); }
});

// ── BLACKLIST MODAL ─────────────────────────────────────────
const blacklistModal = document.getElementById('addBlacklistModal');
const openBlacklistBtn = document.getElementById('add-blacklist-btn');
const closeBlacklistBtn = document.getElementById('closeBlacklistModal');
const cancelBlacklistBtn = document.getElementById('cancelBlacklist');

openBlacklistBtn?.addEventListener('click', () => {
    if (blacklistModal) blacklistModal.style.display = 'block';
});[closeBlacklistBtn, cancelBlacklistBtn].forEach(btn => {
    btn?.addEventListener('click', () => {
        if (blacklistModal) blacklistModal.style.display = 'none';
    });
});

document.getElementById('blacklistForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        first_name: document.getElementById('b-firstname').value.trim(),
        last_name: document.getElementById('b-lastname').value.trim(),
        student_id: document.getElementById('b-studentid').value.trim() || null,
        reason: document.getElementById('b-reason').value.trim(),
        severity: document.getElementById('b-severity').value
    };
    try {
        const res = await fetch('/api/admin/blacklist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Failed to add to blacklist');
        if (blacklistModal) blacklistModal.style.display = 'none';
        e.target.reset();
        loadBlacklistTable();
    } catch (err) { alert(err.message); }
});

// ── NAVIGATION ────────────────────────────────────────────
const navLinks   = document.querySelectorAll('.nav-links a');
const topbarName = document.getElementById('topbar-name');

function showSection(hash) {
// hide all
    document.querySelectorAll('.page-section').forEach(s => s.style.display = 'none');
// show target
    const target = document.querySelector(hash);
    if (target) target.style.display = 'block';

    if (hash === '#home') {
        if (currentUser?.role === 'student') {
// Delegate to chart-student.js which owns the student dashboard
            if (window.refreshStudentDashboard) window.refreshStudentDashboard();
        }
    }
    if (hash === '#department') loadDepartmentsTable();
    if (hash === '#student')    loadAcceptedStudents();
    if (hash === '#faculty')    loadFacultyTable();
    if (hash === '#visitors')   loadVisitorsTable();
    if (hash === '#blacklist')  loadBlacklistTable();
    if (hash === '#violations') loadViolationsTable();
    if (hash === '#subject' || hash === '#student' || hash === '#analytic') {
        if (currentUser?.role === 'instructor') loadInstructorSubjects(hash);
        else if (currentUser?.role === 'student' && hash === '#subject') loadStudentSubjects();
    }

// Handle auto-refresh for pending students
    if (hash === '#pending-students') {
        startPendingRefresh();
    } else {
        stopPendingRefresh();
    }
    if (hash === '#gate-logs' && typeof loadGateLogs === 'function') {
        try { loadGateLogs(); } catch(e) { console.warn('loadGateLogs failed', e); }
    }
// Student Biometric Logs: start/stop polling when #logs is active
    if (hash === '#logs') {
        try {
            const gateEl = document.getElementById('gateLogsTable');
            const subjEl = document.getElementById('subjectLogsTable');
            const gateBtn = document.getElementById('gateLogsBtn');
            const subjectBtn = document.getElementById('subjectLogsBtn');

// For students, default to Subject Logs so their personal attendance is shown first
            if (currentUser?.role === 'student') {
                subjectBtn?.classList.add('active');
                gateBtn?.classList.remove('active');
                if (subjEl) subjEl.style.display = '';
                if (gateEl) gateEl.style.display = 'none';
                startStudentSubjectLogsPolling();
            } else {
// fallback to whichever tab is marked active
                const activeBtn = document.querySelector('#gateLogsBtn.active, #subjectLogsBtn.active');
                if (activeBtn && activeBtn.id === 'subjectLogsBtn') startStudentSubjectLogsPolling();
                else startStudentGateLogsPolling();
            }
        } catch (e) { console.warn('startStudentLogs failed', e); }
    } else {
// stop any student logs polling when leaving the logs page
        try { stopStudentGateLogsPolling(); stopStudentSubjectLogsPolling(); } catch(e) {}
    }

// update topbar
    if (topbarName) topbarName.textContent = sectionTitles[hash] || 'Dashboard';
// update active link
    navLinks.forEach(l => l.classList.toggle('active', l.getAttribute('href') === hash));
}

// ── INITIALIZATION ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const hash = window.location.hash || '#home';
    showSection(hash);
});

window.addEventListener('hashchange', () => {
    showSection(window.location.hash);
});

// ── INSTRUCTOR MODULES (Subjects, Sessions, Students) ─────
async function loadInstructorSubjects(activeHash = null) {
    const listContainer = document.getElementById('instructor-subject-list');
    const studentContainer = document.getElementById('student-subject-list');
    const analyticContainer = document.getElementById('analytic-subject-list');
    if (!listContainer) return;

// Use passed hash or fallback to window.location.hash or default
    const currentSection = activeHash || window.location.hash || '#subject';

    try {
        const res = await fetch('/api/subjects', { credentials: 'same-origin' });
        const subjects = await res.json();

        const render = (c) => {
            if (!c) return;
            c.innerHTML = '';

            subjects.forEach((s, index) => {
                const card = document.createElement('div');
                card.className = 'subject-card';
                card.innerHTML = `
<div class="subject-header">
    <span class="subject-code">${s.code}</span>
    <span class="subject-title">${s.name}</span>
</div>
<div class="subject-instructor-container">
    <span class="code">code: ${s.join_code}</span>
</div>
`;
                card.onclick = () => {
// Remove active class from all sibling cards in THIS container
                    c.querySelectorAll('.subject-card').forEach(child => child.classList.remove('active'));
                    card.classList.add('active');

// Re-evaluate section in case it changed since initial load
                    const clickSection = window.location.hash || activeHash || '#subject';

// Store selected subject for Student section
                    if (c.id === 'student-subject-list' && typeof setSelectedSubject === 'function') {
                        setSelectedSubject(s.id, s.name, s.code);
                        console.log(`[loadInstructorSubjects] Student section: Selected subject ${s.name} (ID: ${s.id}, Code: ${s.code})`);
                    }

                    if (clickSection === '#subject') {
// In the new gate-security focus, subjects just show student logs
                        loadSubjectStudents(s.id, s.name);
                        const panel = document.getElementById('studentListPanel');
                        if (panel) panel.style.display = 'block';

                        if (typeof setSelectedSubject === 'function') {
                            setSelectedSubject(s.id, s.name, s.code);
                        }
                    }
                    if (clickSection === '#student') {
// Ensure the "Enrolled" tab is active when switching subjects
                        if (typeof showEnrolledStudents === 'function') {
                            showEnrolledStudents();
                        }
                        loadSubjectStudents(s.id, s.name);
                        const panel = document.getElementById('studentListPanel');
                        if (panel) panel.style.display = 'block';
                    }
                    if (clickSection === '#analytic') {
                        loadSubjectAnalytics(s.id, s.name);
                        setSelectedSubject(s.id, s.name, s.code);
                    }
                };
                c.appendChild(card);

// Auto-click the first card to load its content
                if (index === 0) {
                    const containerId = c.id;

// Auto-click conditions for each section
                    const shouldAutoClick = (
                        (currentSection === '#subject' && containerId === 'instructor-subject-list') ||
                        (currentSection === '#student' && containerId === 'student-subject-list') ||
                        (currentSection === '#analytic' && containerId === 'analytic-subject-list')
                    );

                    if (shouldAutoClick) {
                        console.log(`[loadInstructorSubjects] Auto-clicking first card in ${containerId} for section ${currentSection}`);
                        card.click();
                    }
                }
            });
        };

        render(listContainer);
        render(studentContainer);
        render(analyticContainer);
    } catch (err) {
        console.error('Load subjects error:', err);
    }
}

// Accept all students in a subject
document.getElementById('acceptAllBtn')?.addEventListener('click', async () => {
    const subjectId = document.getElementById('acceptAllBtn').dataset.subjectId;
    if (!subjectId) return;

    if (!confirm('Are you sure you want to accept all pending students?')) return;

    try {
        const res = await fetch(`/api/subjects/${subjectId}/students/accept-all`, {
            method: 'POST',
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Failed to accept all students');
        loadSubjectStudents(subjectId, 'Subject');
    } catch (err) {
        alert(err.message);
    }
});

// Modal handling for Subjects
const subjectModal = document.getElementById('add-subject-modal');
const openSubjectBtn = document.getElementById('add-subject-btn');
const closeSubjectBtns =[
    document.getElementById('closeAddSubject'),
    document.getElementById('subjectCancel'),
    document.getElementById('subjectDone'),
    document.getElementById('addSubjectOverlay')
];

openSubjectBtn?.addEventListener('click', () => {
    if (subjectModal) {
        subjectModal.style.display = 'block';
// Reset state
        document.getElementById('generatedCodeContainer').style.display = 'none';
        document.getElementById('subjectSubmit').style.display = 'inline-flex';
        document.getElementById('subjectDone').style.display = 'none';
        document.getElementById('subjectCancel').style.display = 'inline-flex';
        document.getElementById('subjectCode').value = '';
        document.getElementById('subjectName').value = '';
        document.getElementById('subjectMessage').style.display = 'none';
    }
});

closeSubjectBtns.forEach(btn => {
    btn?.addEventListener('click', (e) => {
        if (e.target === btn || btn.id === 'closeAddSubject' || btn.id === 'subjectCancel' || btn.id === 'subjectDone') {
            if (subjectModal) subjectModal.style.display = 'none';
        }
    });
});

document.getElementById('subjectSubmit')?.addEventListener('click', async () => {
    const code = document.getElementById('subjectCode').value.trim();
    const name = document.getElementById('subjectName').value.trim();
    const schedule_start = document.getElementById('subjectScheduleStart').value;
    const schedule_end = document.getElementById('subjectScheduleEnd').value;
    const time_window_min = parseInt(document.getElementById('subjectTimeWindow').value) || 30;
    const msgEl = document.getElementById('subjectMessage');

    if (!code || !name || !schedule_start || !schedule_end) {
        if (msgEl) {
            msgEl.textContent = 'Please fill in all required fields.';
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
        return;
    }

    try {
        const bodyData = {
            code,
            name,
            schedule_start,
            schedule_end,
            time_window_min
        };

        const res = await fetch('/api/subjects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyData),
            credentials: 'same-origin'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to create subject');

// Show generated code
        document.getElementById('displayJoinCode').textContent = data.join_code;
        document.getElementById('generatedCodeContainer').style.display = 'block';

// Update UI
        document.getElementById('subjectSubmit').style.display = 'none';
        document.getElementById('subjectCancel').style.display = 'none';
        document.getElementById('subjectDone').style.display = 'inline-flex';

        if (msgEl) {
            msgEl.textContent = 'Subject created successfully!';
            msgEl.style.display = 'block';
            msgEl.style.color = '#4ade80';
        }

        loadInstructorSubjects();

    } catch (err) {
        if (msgEl) {
            msgEl.textContent = err.message;
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
    }
});

// Modal handling for Sessions
const sessionModal = document.getElementById('add-session-modal');
const openSessionBtn = document.getElementById('add-session-btn');
const closeSessionBtns =[
    document.getElementById('closeAddSession'),
    document.getElementById('sessionCancel'),
    document.getElementById('addSessionOverlay')
];

openSessionBtn?.addEventListener('click', () => {
    if (sessionModal) {
        sessionModal.style.display = 'block';
        document.getElementById('sessionMessage').style.display = 'none';
// Pre-fill date
        document.getElementById('sessionDate').valueAsDate = new Date();
    }
});

closeSessionBtns.forEach(btn => {
    btn?.addEventListener('click', (e) => {
        if (e.target === btn || btn.id === 'closeAddSession' || btn.id === 'sessionCancel') {
            if (sessionModal) sessionModal.style.display = 'none';
        }
    });
});

document.getElementById('sessionSubmit')?.addEventListener('click', async () => {
    const subjectId = openSessionBtn.dataset.subjectId;
    const date = document.getElementById('sessionDate').value;
    const start_time = document.getElementById('sessionStart').value;
    const end_time = document.getElementById('sessionEnd').value;
    const msgEl = document.getElementById('sessionMessage');

// Only date/time are required for sessions
    if (!date || !start_time || !end_time) {
        if (msgEl) {
            msgEl.textContent = 'Please fill in all fields.';
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
        return;
    }

// Build request body (location is set at subject level now)
    const bodyData = { date, start_time, end_time, device: 'face' };

    try {
        const res = await fetch(`/api/subjects/${subjectId}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyData),
            credentials: 'same-origin'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to create session');

        if (msgEl) {
            msgEl.textContent = 'Session added successfully!';
            msgEl.style.display = 'block';
            msgEl.style.color = '#4ade80';
        }

        setTimeout(() => {
            if (sessionModal) sessionModal.style.display = 'none';
// Find subject name for refresh
            const subjectsRes = fetch('/api/subjects', { credentials: 'same-origin' });
            subjectsRes.then(r => r.json()).then(subs => {
                const s = subs.find(item => item.id == subjectId);
                loadSessions(subjectId, s ? s.name : 'Subject');
            });
        }, 1500);

    } catch (err) {
        if (msgEl) {
            msgEl.textContent = err.message;
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
    }
});

async function loadSessions(subjectId, subjectName) {
    const tableBody = document.querySelector('#subject .session-table-container tbody');
    const titleEl = document.querySelector('#subject .session-title h2');
    if (!tableBody) return;

    if (titleEl) titleEl.textContent = `Sessions: ${subjectName}`;

// Helper: format various time representations into `h:mmam` / `h:mmpm`
    function formatTime(t) {
        if (!t && t !== 0) return '—';
// Date object
        if (t instanceof Date) return t.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase().replace(/\s+/g, '');
// String like "HH:MM:SS" or "HH:MM"
        if (typeof t === 'string') {
            const s = t.trim();
            if (s.includes(':')) {
                const parts = s.split(':');
                const hh = parseInt(parts[0], 10) || 0;
                const mm = parts[1] ? parts[1].padStart(2, '0') : '00';
                const dt = new Date(); dt.setHours(hh, parseInt(mm, 10), 0, 0);
                return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase().replace(/\s+/g, '');
            }
// Digits-only like 800, 0800, 140000
            const digits = s.replace(/\D/g, '');
            if (digits.length === 3 || digits.length === 4) {
                const hh = parseInt(digits.slice(0, digits.length - 2), 10);
                const mm = parseInt(digits.slice(-2), 10);
                const dt = new Date(); dt.setHours(hh, mm, 0, 0);
                return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase().replace(/\s+/g, '');
            }
            if (digits.length === 6) {
                const hh = parseInt(digits.slice(0, 2), 10);
                const mm = parseInt(digits.slice(2, 4), 10);
                const dt = new Date(); dt.setHours(hh, mm, 0, 0);
                return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase().replace(/\s+/g, '');
            }
            return s;
        }
// Number (possibly seconds since midnight or HHMM)
        if (typeof t === 'number') {
            const digits = String(Math.floor(t));
            if (digits.length === 3 || digits.length === 4) {
                const hh = parseInt(digits.slice(0, digits.length - 2), 10);
                const mm = parseInt(digits.slice(-2), 10);
                const dt = new Date(); dt.setHours(hh, mm, 0, 0);
                return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase().replace(/\s+/g, '');
            }
            if (t <= 86400) {
                const hh = Math.floor(t / 3600);
                const mm = Math.floor((t % 3600) / 60);
                const dt = new Date(); dt.setHours(hh, mm, 0, 0);
                return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase().replace(/\s+/g, '');
            }
// fallback to Date parse
            const dt = new Date(t);
            if (!isNaN(dt.getTime())) return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase().replace(/\s+/g, '');
            return String(t);
        }
    }

    try {
        const res = await fetch(`/api/subjects/${subjectId}/sessions`, { credentials: 'same-origin' });
        const sessions = await res.json();

        tableBody.innerHTML = '';
        if (sessions.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="7" css="text-align:center; padding:20px;">No sessions found. Click "+ New Session" to create one.</td></tr>';
            return;
        }

        sessions.forEach(sess => {
            const tr = document.createElement('tr');
            const dateStr = new Date(sess.date).toLocaleDateString();
            const startTimeStr = formatTime(sess.start_time);
            const endTimeStr = formatTime(sess.end_time);

// Determine session status based on current date/time vs session date/start/end
            const now = new Date();
            const sessDate = new Date(sess.date);

// Helper to parse time from various formats (string "HH:MM:SS", "HH:MM", timedelta, number)
            function parseTimeToHoursMinutes(t) {
                if (t == null) return { h: 0, m: 0 };
                if (typeof t === 'string') {
                    const parts = t.split(':');
                    return { h: parseInt(parts[0], 10) || 0, m: parseInt(parts[1], 10) || 0 };
                }
                if (typeof t === 'number') {
                    const h = Math.floor(t / 3600);
                    const m = Math.floor((t % 3600) / 60);
                    return { h, m };
                }
// Handle timedelta-like objects (e.g., from MySQL)
                if (typeof t === 'object' && t !== null) {
                    if (typeof t.hours === 'number') return { h: t.hours, m: t.minutes || 0 };
                    if (typeof t.seconds === 'number') {
                        const totalSec = t.hours * 3600 + t.minutes * 60 + t.seconds;
                        return { h: Math.floor(totalSec / 3600), m: Math.floor((totalSec % 3600) / 60) };
                    }
                }
                return { h: 0, m: 0 };
            }

            const startParts = parseTimeToHoursMinutes(sess.start_time);
            const endParts = parseTimeToHoursMinutes(sess.end_time);
            const sessStart = new Date(sessDate);
            sessStart.setHours(startParts.h, startParts.m, 0, 0);
            const sessEnd = new Date(sessDate);
            sessEnd.setHours(endParts.h, endParts.m, 0, 0);

            let computedStatus = 'scheduled';
            let computedStatusClass = 'scheduled';
            if (now >= sessEnd) {
                computedStatus = 'completed';
                computedStatusClass = 'completed';
            } else if (now >= sessStart) {
                computedStatus = 'in-progress';
                computedStatusClass = 'in-progress';
            }

// Capitalize status display
            const statusDisplay = computedStatus.charAt(0).toUpperCase() + computedStatus.slice(1);

            tr.innerHTML = `
<td>${dateStr}</td>
<td>${startTimeStr}</td>
<td>${endTimeStr}</td>
<td>${sess.section || '—'}</td>
<td>${sess.present_count}/${sess.total_count}</td>
<td class="table-center"><span class="status ${computedStatusClass}">${statusDisplay}</span></td>
<td class="actions">
    <div class="action-dropdown">
        <button class="action-toggle"><i class="fas fa-ellipsis-v"></i></button>
        <div class="action-menu">
            <a href="#view-session" class="edit-action" onclick="viewSessionAttendance(${sess.id}, ${subjectId}, '${subjectName}')"><i class="fas fa-eye"></i> View</a>
        </div>
    </div>
</td>
`;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        console.error('Load sessions error:', err);
    }
}

async function viewSessionAttendance(sessionId, subjectId, subjectName) {
    const tableBody = document.querySelector('#view-session tbody');
    const titleEl = document.querySelector('#view-session .session-title h2');
    if (!tableBody) return;

    try {
        const res = await fetch(`/api/sessions/${sessionId}/attendance`, { credentials: 'same-origin' });
        const data = await res.json();

// Get session info for title
        if (titleEl) titleEl.textContent = `${subjectName} — Session Details`;

        tableBody.innerHTML = '';
        data.forEach(r => {
            const tr = document.createElement('tr');
            const timeStr = r.scanned_at ? new Date(r.scanned_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', hour12: true}).toLowerCase().replace(/\s+/g, '') : '—';

// Map location_status to display class
// verified -> completed (green), out_of_range -> in-progress (orange), not_verified -> absent (red)
            let locClass = 'absent'; // default red
            if (r.location_status === 'verified') locClass = 'completed'; // green
            else if (r.location_status === 'out_of_range') locClass = 'in-progress'; // orange

// Map attendance status to display class
// present -> completed (green), late -> in-progress (yellow), absent -> absent (red)
            let statusClass = 'absent'; // default red
            const statusLower = (r.status || 'absent').toLowerCase();
            if (statusLower === 'present') statusClass = 'completed'; // green
            else if (statusLower === 'late') statusClass = 'in-progress'; // orange/yellow
            else if (statusLower === 'out_of_range') statusClass = 'in-progress'; // orange

// Format display text for readability
            const locDisplay = r.location_status ? r.location_status.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : 'Not Verified';
            const statusDisplay = r.status ? r.status.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : 'Absent';

            tr.innerHTML = `
<td>${timeStr}</td>
<td>${r.student_code}</td>
<td>${r.first_name} ${r.last_name}</td>
<td class="table-center"><span class="status ${locClass}">${locDisplay}</span></td>
<td class="table-center"><span class="status ${statusClass}">${statusDisplay}</span></td>
`;
            tableBody.appendChild(tr);
        });

        showSection('#view-session');
    } catch (err) {
        console.error('View session error:', err);
    }
}

async function loadSubjectStudents(subjectId, subjectName) {
    const enrolledBody = document.querySelector('#enrolledTable tbody');
    const newStudentBody = document.querySelector('#newStudentTable tbody');
    if (!enrolledBody || !newStudentBody) {
        console.error('[loadSubjectStudents] Table bodies not found');
        return;
    }

    console.log(`[loadSubjectStudents] Loading students for subject ID: ${subjectId}, Name: ${subjectName}`);

// Set dataset for Accept All
    const acceptAllBtn = document.getElementById('acceptAllBtn');
    if (acceptAllBtn) {
        acceptAllBtn.dataset.subjectId = subjectId;
        console.log(`[loadSubjectStudents] Set acceptAllBtn.dataset.subjectId = ${subjectId}`);
    }

// Reset bodies
    enrolledBody.innerHTML = '<tr><td colspan="5" css="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin"></i> Loading enrolled students...</td></tr>';
    newStudentBody.innerHTML = '<tr><td colspan="6" css="text-align:center; padding:20px;"><i class="fas fa-spinner fa-spin"></i> Loading pending students...</td></tr>';

    try {
// Fetch enrolled students (default status)
        console.log(`[loadSubjectStudents] Fetching enrolled students from: /api/subjects/${subjectId}/students`);
        const res = await fetch(`/api/subjects/${subjectId}/students`, { credentials: 'same-origin' });
        if (!res.ok) {
            const errorText = await res.text();
            console.error(`[loadSubjectStudents] Enrolled students fetch failed: ${res.status}`, errorText);
            throw new Error(`Enrolled students fetch failed: ${res.status}`);
        }
        const enrolled = await res.json();
        console.log(`[loadSubjectStudents] Enrolled students response:`, enrolled);

// Fetch pending students
        console.log(`[loadSubjectStudents] Fetching pending students from: /api/subjects/${subjectId}/students?status=pending`);
        const resPending = await fetch(`/api/subjects/${subjectId}/students?status=pending`, { credentials: 'same-origin' });
        if (!resPending.ok) {
            const errorText = await resPending.text();
            console.error(`[loadSubjectStudents] Pending students fetch failed: ${resPending.status}`, errorText);
            throw new Error(`Pending students fetch failed: ${resPending.status}`);
        }
        const pending = await resPending.json();
        console.log(`[loadSubjectStudents] Pending students response:`, pending);

// Use separated render functions from instructor.js
        if (typeof renderEnrolledStudents === 'function') {
            console.log('[loadSubjectStudents] Using renderEnrolledStudents from instructor.js');
            renderEnrolledStudents(subjectId, enrolled);
        } else {
            console.warn('[loadSubjectStudents] renderEnrolledStudents not available, using fallback');
// Render Enrolled (fallback)
            enrolledBody.innerHTML = '';
            if (enrolled.length === 0) {
                enrolledBody.innerHTML = '<tr><td colspan="5" css="text-align:center; padding:20px; color:#64748b;">No enrolled students found.</td></tr>';
            } else {
                enrolled.forEach(s => {
                    const tr = document.createElement('tr');
                    const name = (s.first_name || s.last_name) ? `${s.first_name || ''} ${s.last_name || ''}`.trim() : s.email;
                    tr.innerHTML = `
<td>${s.student_id || '—'}</td>
<td>${name}</td>
<td>${s.section || '—'}</td>
<td><span class="status completed">${s.attendance_pct}%</span></td>
<td class="actions">
    ${s.user_id ? `<button class="delete" onclick="removeStudent(${subjectId}, ${s.user_id})">Remove</button>` : ''}
</td>
`;
                    enrolledBody.appendChild(tr);
                });
            }
        }

// Use separated render functions from instructor.js
        if (typeof renderNewStudents === 'function') {
            console.log('[loadSubjectStudents] Using renderNewStudents from instructor.js');
            renderNewStudents(subjectId, pending);
        } else {
            console.warn('[loadSubjectStudents] renderNewStudents not available, using fallback');
// Render Pending (New Student) (fallback)
            newStudentBody.innerHTML = '';
            if (pending.length === 0) {
                newStudentBody.innerHTML = '<tr><td colspan="6" css="text-align:center; padding:20px; color:#64748b;">No pending applications for this subject.</td></tr>';
            } else {
                pending.forEach(s => {
                    const tr = document.createElement('tr');
                    const appliedAt = s.enrolled_at ? new Date(s.enrolled_at).toLocaleString() : '—';
                    const name = `${s.first_name || ''} ${s.last_name || ''}`.trim() || '—';

// Use student_id for display (ID No.) and user_id for actions
                    const displayId = s.student_id || '—';
                    const section = s.section || '—';
                    const enrollmentStatus = s.status || 'pending';
                    const internalUserId = s.user_id;

                    tr.innerHTML = `
<td>${displayId}</td>
<td>${section}</td>
<td>${name}</td>
<td>${appliedAt}</td>
<td><span class="status pending">${enrollmentStatus}</span></td>
<td class="actions">
    ${internalUserId ? `<button class="edit" onclick="acceptStudent(${subjectId}, ${internalUserId}, 'accept')">Accept</button>
    <button class="delete" onclick="acceptStudent(${subjectId}, ${internalUserId}, 'reject')">Remove</button>` : '<span css="color:#64748b">No actions</span>'}
</td>
`;
                    newStudentBody.appendChild(tr);
                });
            }
        }
    } catch (err) {
        console.error('Load subject students error:', err);
        enrolledBody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#ef4444;">Error: ${err.message}</td></tr>`;
        newStudentBody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:#ef4444;">Error: ${err.message}</td></tr>`;
    }
}

async function loadSubjectAnalytics(subjectId, subjectName, filter = null) {
    const analyticSection = document.getElementById('analytic');
    if (!analyticSection) return;

    if (!filter) {
        const filterEl = document.getElementById('analytics-filter');
        filter = filterEl ? filterEl.value : 'all';
    }

    try {
        console.log(`[loadSubjectAnalytics] Fetching analytics for subject ${subjectId} with filter ${filter}`);
        const res = await fetch(`/api/subjects/${subjectId}/analytics?filter=${filter}`, { credentials: 'same-origin' });
        if (!res.ok) throw new Error(`Analytics fetch failed: ${res.status}`);
        const data = await res.json();

// Update title
        const titleEl = analyticSection.querySelector('.analytics-title h2');
        if (titleEl) titleEl.textContent = `Attendance Distribution: ${subjectName}`;

// Update bars
        const updateBar = (label, pct, color) => {
            const bar = Array.from(analyticSection.querySelectorAll('.bar-container'))
                .find(el => {
                    const span = el.querySelector('span');
                    return span && span.textContent.trim().toLowerCase() === label.toLowerCase();
                });
            if (bar) {
                const fill = bar.querySelector('.progress-fill');
                const text = bar.querySelector('.analytics-bar span');
                if (fill) {
                    fill.style.width = `${pct}%`;
                    fill.style.background = color;
                }
                if (text) {
                    text.textContent = `${pct}%`;
                    text.style.color = color;
                }
            }
        };

        updateBar('Present', data.distribution.present || 0, '#2EC4B6');
        updateBar('Late',    data.distribution.late || 0,    '#FFB703');
        updateBar('Absent',  data.distribution.absent || 0,  '#FB8500');

// Update high/low tables
        const renderTable = (containerSelector, students) => {
            const container = analyticSection.querySelector(containerSelector);
            if (!container) return;
            const tableBody = container.querySelector('tbody');
            if (tableBody) {
                tableBody.innerHTML = '';
                if (!students || students.length === 0) {
                    tableBody.innerHTML = '<tr><td colspan="3" css="text-align:center; padding:10px; color:#64748b;">No data in this period.</td></tr>';
                } else {
                    students.forEach(s => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
<td>${s.name}</td>
<td>${s.section}</td>
<td>${s.attendance_pct}%</td>
`;
                        tableBody.appendChild(tr);
                    });
                }
            }
        };

        renderTable('.analytics-attendance-container:first-of-type', data.high_attendance);
        renderTable('.analytics-attendance-container:last-of-type',  data.low_attendance);

    } catch (err) {
        console.error('[loadSubjectAnalytics] Error:', err);
    }
}

async function acceptStudent(subjectId, studentId, action) {
    try {
        const res = await fetch(`/api/subjects/${subjectId}/students/${studentId}?action=${action}`, {
            method: 'POST',
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Action failed');
        loadSubjectStudents(subjectId, 'Subject');
    } catch (err) {
        alert(err.message);
    }
}

async function removeStudent(subjectId, studentId) {
    if (!confirm('Are you sure you want to remove this student from the enrolled list? They will be moved back to the application list.')) return;
    try {
// Use the new 'revert' action: change status from 'enrolled' -> 'pending'
        const res = await fetch(`/api/subjects/${subjectId}/students/${studentId}?action=revert`, {
            method: 'POST',
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('Action failed');
        loadSubjectStudents(subjectId, 'Subject');
    } catch (err) {
        alert(err.message);
    }
}

// ── STUDENT SUBJECT MODULE ──────────────────────────────────
async function loadStudentSubjects() {
    const container = document.getElementById('student-subject-list');
    if (!container) return;

    try {
        const res = await fetch('/api/student/subjects', { credentials: 'same-origin' });
        const subjects = await res.json();

        container.innerHTML = '';
        if (subjects.length === 0) {
            container.innerHTML = '<div css="width:100%; text-align:center; padding:40px; color:#64748b;">You are not enrolled in any subjects. Click "+ Enroll Subject" to join one.</div>';
            return;
        }

        subjects.forEach(s => {
            const card = document.createElement('div');
            card.className = 'subject-card';

// Set border color based on attendance
            let color = '#2EC4B6'; // default green
            let statusIcon = '<i class="fas fa-calendar-check"></i>';
            let statusText = 'Perfect Attendance';

            if (s.attendance_pct < 80) {
                color = '#FB8500'; // orange
                statusIcon = '<i class="fas fa-exclamation-triangle"></i>';
                statusText = 'Warning: Low Attendance';
            } else if (s.attendance_pct < 90) {
                color = '#219EBC'; // blue
                statusIcon = '<i class="fas fa-chart-line"></i>';
                statusText = 'Good Progress';
            }

            card.style.borderColor = color;

            card.innerHTML = `
<div class="subject-header">
    <span class="subject-status" style="color:${color}">${statusIcon} ${statusText}</span>
    <h2>${s.name}</h2>
    <span class="instructor-name">Instructor: ${s.instructor_name}</span>
</div>
<div class="progress-bar-container">
    <div class="progress-bar-header"><span>${s.present_count}/${s.total_sessions} Classes</span></div>
    <div class="row bar">
        <div class="progress-bar"><div class="progress-fill" style="width:${s.attendance_pct}%; background:${color};"></div></div>
        <span style="color:${color}">${s.attendance_pct}%</span>
    </div>
</div>
<div class="subject-attendance">
    <div class="row">
        <div class="column column-center"><span>Present</span><span style="color:#16A34A">${s.present_count}</span></div>
        <div class="column column-center"><span>Absent</span><span style="color:#DC262B">${s.absent_count}</span></div>
        <div class="column column-center"><span>Required</span><span>80%</span></div>
    </div>
</div>
`;
            container.appendChild(card);
        });
    } catch (err) {
        console.error('Load student subjects error:', err);
    }
}

// Student Enrollment Modal
const enrollModal = document.getElementById('enroll-subject-modal');
const openEnrollBtn = document.getElementById('openEnrollModalBtn');
const closeEnrollBtns =[
    document.getElementById('closeEnrollModal'),
    document.getElementById('enrollCancel'),
    document.getElementById('enrollOverlay')
];

openEnrollBtn?.addEventListener('click', () => {
    if (enrollModal) {
        enrollModal.style.display = 'block';
        document.getElementById('enrollCode').value = '';
        document.getElementById('enrollMessage').style.display = 'none';
    }
});

closeEnrollBtns.forEach(btn => {
    btn?.addEventListener('click', (e) => {
        if (e.target === btn || btn.id === 'closeEnrollModal' || btn.id === 'enrollCancel') {
            if (enrollModal) enrollModal.style.display = 'none';
        }
    });
});

document.getElementById('enrollSubmit')?.addEventListener('click', async () => {
    const code = document.getElementById('enrollCode').value.trim();
    const msgEl = document.getElementById('enrollMessage');

    if (!code) {
        if (msgEl) {
            msgEl.textContent = 'Please enter an enrollment code.';
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
        return;
    }

    try {
        const res = await fetch('/api/student/subjects/enroll', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ join_code: code }),
            credentials: 'same-origin'
        });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || 'Enrollment failed');

        if (msgEl) {
            msgEl.textContent = 'Application sent! Please wait for instructor approval.';
            msgEl.style.display = 'block';
            msgEl.style.color = '#4ade80';
        }

        setTimeout(() => {
            if (enrollModal) enrollModal.style.display = 'none';
            loadStudentSubjects();
        }, 2000);

    } catch (err) {
        if (msgEl) {
            msgEl.textContent = err.message;
            msgEl.style.display = 'block';
            msgEl.style.color = '#ef4444';
        }
    }
});

document.getElementById('enrolledBtn')?.addEventListener('click', () => {
    document.getElementById('enrolledBtn').classList.add('active');
    document.getElementById('newStudentBtn').classList.remove('active');
    document.getElementById('enrolledTable').style.display = 'block';
    document.getElementById('newStudentTable').style.display = 'none';
});

document.getElementById('newStudentBtn')?.addEventListener('click', () => {
    document.getElementById('newStudentBtn').classList.add('active');
    document.getElementById('enrolledBtn').classList.remove('active');
    document.getElementById('enrolledTable').style.display = 'none';
    document.getElementById('newStudentTable').style.display = 'block';
});

window.addEventListener('DOMContentLoaded', () => {
    const initialHash = window.location.hash;
    if (initialHash && sectionTitles[initialHash]) {
        showSection(initialHash);
    } else {
        showSection('#home');
    }

    navLinks.forEach(link => {
        link.addEventListener('click', e => {
// Let the global dropdown listener handle these
            if (link.classList.contains('dropdown-toggle')) {
                e.preventDefault();
                link.closest('.has-dropdown').classList.toggle('open');
                return;
            }
            e.preventDefault();
            const hash = link.getAttribute('href');
            window.location.hash = hash;
            showSection(hash);
        });
    });

// ── Global in-page anchor links (e.g. table "View" buttons → #view-session) ──
    document.addEventListener('click', e => {
        const anchor = e.target.closest('a[href^="#"]');
        if (!anchor) return;
// Skip nav-links (already handled above), dropdowns, and user-dropdown links
        if (anchor.closest('.nav-links') || anchor.closest('.user-dropdown') || anchor.classList.contains('dropdown-toggle') || anchor.classList.contains('edit-action')) return;
        const hash = anchor.getAttribute('href');
        if (hash && hash.length > 1 && document.querySelector(hash)) {
            e.preventDefault();
            showSection(hash);
        }
    });

// Ensure analytics filter change handler is attached after DOM is ready
    const af = document.getElementById('analytics-filter');
    if (af) {
        af.addEventListener('change', () => {
            const activeCard = document.querySelector('#analytic-subject-list .subject-card.active');
            if (activeCard) activeCard.click();
        });
    }

// Topbar "Profile" link in dropdown
    document.querySelectorAll('.nav-to-profile').forEach(el => {
        el.addEventListener('click', e => {
            e.preventDefault();
            showSection('#profile');
            closeUserDropdown();
        });
    });
});

// ── USER DROPDOWN ─────────────────────────────────────────
const userEl       = document.querySelector('.user');
const userToggleEl = document.getElementById('userToggle');
const arrowIcon    = document.getElementById('arrowIcon');

function closeUserDropdown() {
    userEl?.classList.remove('active');
    if (arrowIcon) arrowIcon.style.transform = '';
}

userToggleEl?.addEventListener('click', e => {
    e.stopPropagation();
    const isOpen = userEl.classList.toggle('active');
    if (arrowIcon) arrowIcon.style.transform = isOpen ? 'rotate(180deg)' : '';
});

document.addEventListener('click', e => {
    if (!e.target.closest('.user')) closeUserDropdown();
});

// ── PROFILE VIEW / EDIT TOGGLE ────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const viewCard = document.getElementById('view-profile-card');
    const editCard = document.getElementById('edit-profile-card');

    document.getElementById('editBtn')?.addEventListener('click', () => {
        viewCard.style.display = 'none';
        editCard.style.display = 'block';
    });

    document.getElementById('cancelBtn')?.addEventListener('click', () => {
        editCard.style.display = 'none';
        viewCard.style.display = 'block';
    });

// Avatar file preview
    document.getElementById('imgInput')?.addEventListener('change', function () {
        const file = this.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = e => {
            document.getElementById('edit-avatar-preview').src = e.target.result;
        };
        reader.readAsDataURL(file);
    });

// Save profile
    document.getElementById('saveBtn')?.addEventListener('click', async () => {
        let section = document.getElementById('year-section')?.value.trim() || '';
        const course = document.getElementById('depart').value;

// If it's a student, we combine course and year/section (e.g., BSCS + 3B -> BSCS-3B)
        if (currentUser?.role === 'student' && course && section) {
// Check if section already contains the course prefix to avoid duplication
            if (!section.toUpperCase().startsWith(course.toUpperCase())) {
                section = `${course}-${section.toUpperCase()}`;
            }
        }

        const body = {
            first_name: document.getElementById('firstname').value.trim(),
            last_name:  document.getElementById('lastname').value.trim(),
            gender:     document.getElementById('gender').value,
            department: course,
            section:    section || null,
            contact:    document.getElementById('contact').value.trim(),
        };
        try {
// 1. Update text profile info
            const res = await fetch('/api/user/profile', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(body),
            });
            if (!res.ok) throw new Error((await res.json()).detail);

// 2. If a new image was selected AND user is a student, upload it for facial feature extraction
            const imgInput = document.getElementById('imgInput');
            if (imgInput && imgInput.files.length > 0) {
                const file = imgInput.files[0];

// Client-side face detection for students
                if (currentUser?.role === 'student' && window.validateFaceInImage) {
                    const hasFace = await window.validateFaceInImage(file);
                    if (!hasFace) {
                        alert("No face detected in the image. Please upload a clear photo of your face.");
                        return;
                    }
                }

                const formData = new FormData();

                formData.append('file', file);

                let uploadUrl = '/api/facial/upload-profile-photo';
                if (currentUser?.role !== 'student') {
                    uploadUrl = '/api/user/profile/upload-avatar';
                }

                const faceRes = await fetch(uploadUrl, {
                    method: 'POST',
                    body: formData,
                    credentials: 'same-origin'
                });
                if (!faceRes.ok) {
                    const errData = await faceRes.json();
                    alert('Profile updated, but avatar upload failed: ' + errData.detail);
                } else {
                    alert('Profile updated successfully!');
                }
            } else {
                alert('Profile updated successfully!');
            }

            await loadProfile();
            editCard.style.display = 'none';
            viewCard.style.display = 'block';
        } catch (err) {
            alert('Save failed: ' + err.message);
        }
    });

    // Change password
    document.getElementById('saveAccBtn')?.addEventListener('click', async () => {
        const newPass  = document.getElementById('edit-password').value;
        const confPass = document.getElementById('edit-password-confirm').value;
        if (!newPass) return;
        if (newPass !== confPass) { alert('Passwords do not match'); return; }
        try {
            const res = await fetch('/api/user/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ new_password: newPass, confirm_password: confPass }),
            });
            if (!res.ok) throw new Error((await res.json()).detail);
            alert('Password updated!');
            document.getElementById('edit-password').value = '';
            document.getElementById('edit-password-confirm').value = '';
        } catch (err) {
            alert('Failed: ' + err.message);
        }
    });

    document.getElementById('approve-all-btn')?.addEventListener('click', approveAllStudents);

    // ── PASSWORD UPDATE ───────────────────────────────────────
    const pwdModal = document.getElementById('password-modal');
    const closePwdBtns =[
        document.getElementById('closePasswordModal'),
        document.getElementById('passwordCancel'),
        document.getElementById('passwordOverlay')
    ];

    document.getElementById('update-password-btn')?.addEventListener('click', () => {
        if (pwdModal) pwdModal.style.display = 'block';
    });

    closePwdBtns.forEach(btn => {
        btn?.addEventListener('click', (e) => {
            if (e.target === btn || btn.id === 'closePasswordModal' || btn.id === 'passwordCancel') {
                if (pwdModal) pwdModal.style.display = 'none';
            }
        });
    });

    document.getElementById('passwordSubmit')?.addEventListener('click', async () => {
        const current_password = document.getElementById('current-password').value;
        const new_password     = document.getElementById('new-password').value;
        const confirm_password = document.getElementById('confirm-new-password').value;
        const msgEl = document.getElementById('passwordMessage');

        if (!current_password || !new_password || !confirm_password) {
            if (msgEl) {
                msgEl.textContent = 'All fields are required.';
                msgEl.style.display = 'block';
                msgEl.style.color = '#ef4444';
            }
            return;
        }

        if (new_password !== confirm_password) {
            if (msgEl) {
                msgEl.textContent = 'Passwords do not match.';
                msgEl.style.display = 'block';
                msgEl.style.color = '#ef4444';
            }
            return;
        }

        try {
            const res = await fetch('/api/user/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_password, new_password, confirm_password }),
                credentials: 'same-origin'
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Update failed');

            if (msgEl) {
                msgEl.textContent = 'Password updated successfully!';
                msgEl.style.display = 'block';
                msgEl.style.color = '#4ade80';
            }

            setTimeout(() => {
                if (pwdModal) pwdModal.style.display = 'none';
                document.getElementById('current-password').value = '';
                document.getElementById('new-password').value = '';
                document.getElementById('confirm-new-password').value = '';
                if (msgEl) msgEl.style.display = 'none';
            }, 1500);

        } catch (err) {
            if (msgEl) {
                msgEl.textContent = err.message;
                msgEl.style.display = 'block';
                msgEl.style.color = '#ef4444';
            }
        }
    });

    loadProfile();
});

// ── LOAD PROFILE DATA ─────────────────────────────────────
async function loadProfile() {
    try {
        const res = await fetch('/api/user/profile', { credentials: 'same-origin' });
        if (!res.ok) return;
        const d = await res.json();
        currentUser = d; // Store globally

        if (d.role === 'student' && window.refreshStudentDashboard) {
            window.refreshStudentDashboard();
        }

        const prefix = d.gender === 'Male' ? 'Mr.' : d.gender === 'Female' ? 'Ms.' : '';
        const fullName = `${prefix} ${d.first_name || ''} ${d.last_name || ''}`.trim();

        setText('view-fullname', fullName || '—');
        setText('view-course',   (d.role ).toUpperCase() + " — " + d.department || '—');
        setText('view-stdid',    d.student_id || '—');
        setText('view-depart',   d.department || '—');
        setText('view-section',  d.section || '—');
        setText('view-gender',   d.gender  || '—');
        setText('view-contact',  d.contact || '—');
        setText('view-email',    d.email   || '—');
        setText('view-role',     (d.role || '').toUpperCase());

        if (d.avatar_url) {
            document.getElementById('view-avatar').src = d.avatar_url;
            const topbarAvatar = document.getElementById('topbar-avatar');
            if (topbarAvatar) topbarAvatar.src = d.avatar_url;
        }

        // Pre-fill edit fields
        setVal('firstname', d.first_name || '');
        setVal('lastname',  d.last_name  || '');
        setVal('contact',   d.contact    || '');
        setVal('email',     d.email      || '');
        setVal('gender',    d.gender     || '');
        setVal('depart',    d.department || '');

        // Handle year-section input field
        const yearSectionInput = document.getElementById('year-section');
        if (yearSectionInput) {
            let sectionVal = d.section || '';
            // If it's a student and section starts with department, strip the prefix for editing
            if (d.role === 'student' && d.department && sectionVal.toUpperCase().startsWith(d.department.toUpperCase())) {
                sectionVal = sectionVal.substring(d.department.length).replace(/^-/, '');
            }
            yearSectionInput.value = sectionVal;
        }
        // If profile loaded while on the logs page, re-evaluate section
        // so student users will default to Subject Logs and start polling.
        if (window.location.hash === '#logs') {
            try { showSection('#logs'); } catch (e) { console.warn('Re-show logs failed', e); }
        }

    } catch (err) {
        console.warn('Profile load failed:', err);
    }
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}
function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
}

// ── CAMERA MODAL ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const cameraModal   = document.querySelector('.camera-modal');
    const openCameraBtn = document.getElementById('openCameraModal');
    const closeCameraBtn = document.getElementById('closeCameraModal');

    openCameraBtn?.addEventListener('click', e => {
        e.preventDefault();
        cameraModal.style.display = 'block';
    });

    closeCameraBtn?.addEventListener('click', () => {
        cameraModal.style.display = 'none';
    });

    cameraModal?.addEventListener('click', e => {
        if (e.target === cameraModal) cameraModal.style.display = 'none';
    });

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') cameraModal.style.display = 'none';
    });
});

// ── QR CODE MANAGEMENT (Temporary ID) ───────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const qrModal = document.getElementById('qr-modal');
    const qrImg = document.getElementById('student-qr-img');
    const openQRBtn = document.getElementById('openQRModalBtn');
    const profileQRChip = document.getElementById('profile-qr-chip');
    const closeQRBtn = document.getElementById('closeQRModal');
    const regenerateBtn = document.getElementById('regenerateQRBtn');

    async function loadQRCode() {
        try {
            const res = await fetch('/api/qr/my-qrcode', { credentials: 'same-origin' });
            if (!res.ok) throw new Error('Failed to load QR code');
            const data = await res.json();
            if (data && data.qr_image_base64) {
                qrImg.src = `data:image/png;base64,${data.qr_image_base64}`;
            }
        } catch (err) {
            console.error('QR load error:', err);
        }
    }

    const openModal = () => {
        if (qrModal) {
            qrModal.style.display = 'block';
            loadQRCode();
        }
    };

    openQRBtn?.addEventListener('click', openModal);
    profileQRChip?.addEventListener('click', openModal);

    closeQRBtn?.addEventListener('click', () => {
        if (qrModal) qrModal.style.display = 'none';
    });

    regenerateBtn?.addEventListener('click', async () => {
        if (!confirm('Regenerating your QR code will invalidate your previous one. Continue?')) return;
        try {
            regenerateBtn.disabled = true;
            regenerateBtn.textContent = 'Regenerating...';
            const res = await fetch('/api/qr/regenerate', { method: 'POST', credentials: 'same-origin' });
            if (!res.ok) throw new Error('Failed to regenerate QR code');
            const data = await res.json();
            if (data.qr && data.qr.qr_image_base64) {
                qrImg.src = `data:image/png;base64,${data.qr.qr_image_base64}`;
                alert('QR code regenerated successfully!');
            }
        } catch (err) {
            alert('Regeneration failed: ' + err.message);
        } finally {
            regenerateBtn.disabled = false;
            regenerateBtn.textContent = 'Regenerate QR Code';
        }
    });

    // Close on outside click
    window.addEventListener('click', (e) => {
        if (e.target === qrModal) qrModal.style.display = 'none';
    });
});