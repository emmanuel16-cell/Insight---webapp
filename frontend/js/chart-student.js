/* ════════════════════════════════════════════════════════════
   chart-student.js  –  InSight Student charts
   Loads real data from /api/dashboard/student and renders charts.
   ════════════════════════════════════════════════════════════ */

let attendanceChartInstance = null;

async function loadStudentChartData() {
    try {
        const res = await fetch('/api/dashboard/student', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to load student dashboard');
        const data = await res.json();

        // 1. Update Stat Cards
        const avgEl = document.getElementById('stat-avg-attendance');
        const heldEl = document.getElementById('stat-classes-held');
        const attEl = document.getElementById('stat-classes-attended');
        const missEl = document.getElementById('stat-classes-missed');
        if (avgEl) avgEl.textContent = `${data.statistics.overall_attendance_percentage}%`;
        if (heldEl) heldEl.textContent = data.statistics.total_sessions_held;
        if (attEl) attEl.textContent = data.statistics.total_sessions_attended;
        if (missEl) missEl.textContent = data.statistics.total_sessions_missed;

        // 2. Render Attendance Line Chart
        renderAttendanceLineChart(data.chart_data);

        // 3. Render Subject Comparison Bars
        renderSubjectComparison(data.enrolled_courses);

        // 4. Render Recent Biometric Logs Table
        renderRecentBiometricLogs(data.recent_logs);

    } catch (err) {
        console.error('[loadStudentChartData] error:', err);
    }
}

function renderAttendanceLineChart(chartData) {
    const canvasEl = document.getElementById('attendance-Chart');
    if (!canvasEl) return;

    const ctx = canvasEl.getContext('2d');

    if (attendanceChartInstance) {
        attendanceChartInstance.destroy();
        attendanceChartInstance = null;
    }

    let labels = [];
    let meData = [];

    if (chartData && chartData.length > 0) {
        labels = chartData.map(d => {
            const date = new Date(d.date);
            return date.toLocaleDateString('en-US', { weekday: 'short' });
        });
        meData = chartData.map(d => d.me_rate || 0);
    } else {
        // No data - show empty placeholder with days of week
        labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        meData = [0, 0, 0, 0, 0, 0, 0];
    }

    attendanceChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'My Attendance',
                data: meData,
                borderColor: '#2EC4B6',
                backgroundColor: 'rgba(46,196,182,0.15)',
                fill: true,
                tension: 0.3,
                pointRadius: 5,
                pointBackgroundColor: '#2EC4B6',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    labels: {
                        color: '#023047',
                        boxWidth: 12,
                        boxHeight: 12,
                        font: { size: 13, weight: '600' }
                    }
                }
            },
            scales: {
                y: {
                    min: 0,
                    max: 100,
                    ticks: {
                        color: '#023047',
                        stepSize: 20,
                        callback: v => v + '%',
                        font: { size: 13 }
                    },
                    grid: { color: '#e5e7eb' }
                },
                x: {
                    grid: { display: false },
                    ticks: {
                        color: '#023047',
                        font: { size: 13, weight: '600' }
                    }
                }
            }
        }
    });
}

function renderSubjectComparison(enrolledCourses) {
    const container = document.getElementById('subject-comparison-container');
    if (!container) return;

    container.innerHTML = '';

    if (!enrolledCourses || enrolledCourses.length === 0) {
        container.innerHTML = '<p css="text-align:center; color:#6b7280; padding:15px;">No enrolled subjects found.</p>';
        return;
    }

    enrolledCourses.forEach(course => {
        const total = course.total_sessions || 0;
        const present = course.present_count || 0;
        const pct = total > 0 ? Math.round(present / total * 100) : 0;
        const barColor = pct >= 80 ? '#2EC4B6' : (pct >= 60 ? '#FFB703' : '#FB8500');

        const barHtml = `
            <div class="bar-container">
                <span>${course.course_code}</span>
                <div class="row analytics-bar">
                    <div class="progress-bar"><div class="progress-fill" style="width:${pct}%; background:${barColor};"></div></div>
                    <span style="color:${barColor}">${pct}%</span>
                </div>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', barHtml);
    });
}

function renderRecentBiometricLogs(logs) {
    const tbody = document.querySelector('#recent-logs-table tbody');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (!logs || logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" css="text-align:center; padding:15px; color:#6b7280;">No recent biometric logs.</td></tr>';
        return;
    }

    logs.forEach(log => {
        const dateStr = log.date ? new Date(log.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—';
        const timeStr = log.time ? new Date(log.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
        
        let statusText = log.status || '—';
        if (statusText !== 'Entry' && statusText !== 'Exit') {
            statusText = statusText.charAt(0).toUpperCase() + statusText.slice(1).replaceAll('_', ' ');
        }

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${log.type}</td>
            <td>${dateStr}</td>
            <td>${timeStr}</td>
            <td>${statusText}</td>
        `;
        tbody.appendChild(tr);
    });
}

// Auto-load when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    loadStudentChartData();
});

// Allow manual refresh
window.refreshStudentDashboard = loadStudentChartData;