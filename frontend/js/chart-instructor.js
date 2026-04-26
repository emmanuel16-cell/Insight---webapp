let instructorDonutChart = null;

document.addEventListener('DOMContentLoaded', () => {
    // Initial load
    loadInstructorDashboard();

    // Setup filter listener
    const filterSelect = document.getElementById('attendance-filter');
    if (filterSelect) {
        filterSelect.addEventListener('change', () => {
            const selectedFilter = filterSelect.value;
            loadInstructorDashboard(selectedFilter);
        });
    }
});

/**
 * Fetch and render instructor dashboard data
 * @param {string} filter - 'today', 'weekly', or 'monthly'
 */
async function loadInstructorDashboard(filter = 'today') {
    try {
        console.log(`[Dashboard] Fetching instructor data with filter: ${filter}...`);
        const res = await fetch(`/api/dashboard/instructor?filter=${filter}`, { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to fetch instructor dashboard');
        
        const data = await res.json();
        console.log('[Dashboard] Data received:', data);

        // 1. Update Stat Cards
        updateStatCards(data.statistics);

        // 2. Render Donut Chart
        renderDonutChart(data.donut_data);

        // 3. Render Section Comparison
        renderSectionComparison(data.section_comparison);

        // 4. Render Today's Sessions Table
        renderRecentSessions(data.recent_sessions);

    } catch (err) {
        console.error('[Dashboard] Error loading dashboard:', err);
    }
}

/**
 * Update top 4 statistic cards
 */
function updateStatCards(stats) {
    const avgEl = document.getElementById('stat-avg-attendance');
    const studentsEl = document.getElementById('stat-all-students');
    const sessionsEl = document.getElementById('stat-sessions-done');
    const subjectsEl = document.getElementById('stat-all-subjects');

    if (avgEl) avgEl.textContent = `${stats.avg_attendance}%`;
    if (studentsEl) studentsEl.textContent = stats.total_students;
    if (sessionsEl) sessionsEl.textContent = stats.total_sessions;
    if (subjectsEl) subjectsEl.textContent = stats.total_subjects;
}

/**
 * Render the attendance donut chart
 */
function renderDonutChart(donutData) {
    const canvas = document.getElementById('gateChart');
    if (!canvas) return;

    const total = donutData.present + donutData.late + donutData.absent;
    const totalEl = document.getElementById('stat-donut-total-students');
    if (totalEl) totalEl.textContent = total;

    const ctx = canvas.getContext('2d');
    
    if (instructorDonutChart) {
        instructorDonutChart.destroy();
    }

    instructorDonutChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Present', 'Late', 'Absent'],
            datasets: [{
                data: [donutData.present, donutData.late, donutData.absent],
                backgroundColor: ['#2EC4B6', '#FFB703', '#FB8500'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            cutout: '65%',
            animation: {
                duration: 1000
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.raw || 0;
                            const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * Render section comparison progress bars
 */
function renderSectionComparison(sections) {
    const container = document.getElementById('section-comparison-container');
    if (!container) return;

    container.innerHTML = '';

    if (!sections || sections.length === 0) {
        container.innerHTML = '<div css="text-align:center; padding:20px; color:#64748b;">No section data available</div>';
        return;
    }

    sections.forEach(sec => {
        const pct = sec.attendance_pct;
        const color = pct >= 80 ? '#2EC4B6' : pct >= 60 ? '#FFB703' : '#FB8500';
        
        const barHtml = `
            <div class="bar-container">
                <span>${sec.section || 'Unknown'}</span>
                <div class="row analytics-bar">
                    <div class="progress-bar">
                        <div class="progress-fill" style="width:${pct}%; background:${color};"></div>
                    </div>
                    <span style="color:${color}">${pct}%</span>
                </div>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', barHtml);
    });
}

/**
 * Render recent class sessions table
 */
function renderRecentSessions(sessions) {
    const tbody = document.getElementById('today-sessions-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (!sessions || sessions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" css="text-align:center; padding:20px; color:#64748b;">No recent sessions found</td></tr>';
        return;
    }

    const now = new Date();

    // Helper to parse time from various formats
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
        if (typeof t === 'object' && t !== null) {
            if (typeof t.hours === 'number') return { h: t.hours, m: t.minutes || 0 };
        }
        return { h: 0, m: 0 };
    }

    sessions.forEach(s => {
        const tr = document.createElement('tr');
        
        // Determine session status based on current date/time vs session date/start/end
        const sessDate = new Date(s.date);
        const startParts = parseTimeToHoursMinutes(s.start_time);
        const endParts = parseTimeToHoursMinutes(s.end_time);

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

        // Format time (assuming HH:MM:SS from MySQL)
        const formatTime = (timeStr) => {
            if (!timeStr) return '—';
            try {
                const [h, m] = timeStr.split(':');
                const hour = parseInt(h);
                const ampm = hour >= 12 ? 'PM' : 'AM';
                const hour12 = hour % 12 || 12;
                return `${hour12}:${m} ${ampm}`;
            } catch (e) {
                return timeStr;
            }
        };

        tr.innerHTML = `
            <td>${formatTime(s.start_time)}</td>
            <td>${formatTime(s.end_time)}</td>
            <td>${s.subject_code}</td>
            <td>${s.section || '—'}</td>
            <td>${s.present_count}</td>
            <td>${s.absent_count}</td>
            <td><span class="status ${computedStatusClass}">${computedStatus.charAt(0).toUpperCase() + computedStatus.slice(1).replace('-', ' ')}</span></td>
        `;
        tbody.appendChild(tr);
    });
}
