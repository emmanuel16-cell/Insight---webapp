document.addEventListener('DOMContentLoaded', async () => {
    // ── 1. SUMMARY STATS (Top Cards) ──────────────────────────
    async function updateSummaryStats() {
        try {
            const res = await fetch('/api/dashboard/admin/summary-stats');
            const data = await res.json();
            if (document.getElementById('stat-students')) document.getElementById('stat-students').textContent = data.students || 0;
            if (document.getElementById('stat-instructors')) document.getElementById('stat-instructors').textContent = data.instructors || 0;
            if (document.getElementById('stat-departments')) document.getElementById('stat-departments').textContent = data.departments || 0;
            if (document.getElementById('stat-cameras')) document.getElementById('stat-cameras').textContent = data.cameras || 0;
        } catch (err) {
            console.error('Failed to fetch summary stats:', err);
        }
    }
    updateSummaryStats();

// ── 2. ATTENDANCE BAR CHART ───────────────────────────────
    const attendanceCanvas = document.getElementById('attendanceChart');
    if (attendanceCanvas) {
        const attendanceChart = new Chart(attendanceCanvas, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [
                    {label: 'Present', data: [], backgroundColor: '#219EBC', borderRadius: 3, barThickness: 14},
                    {label: 'Late', data: [], backgroundColor: '#ffb703', borderRadius: 3, barThickness: 14},
                    {label: 'Absent', data: [], backgroundColor: '#ff7f00', borderRadius: 3, barThickness: 14}
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {display: false},
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ${ctx.raw}%`
                        }
                    }
                },
                scales: {
                    x: {grid: {display: false}, ticks: {color: '#000', font: {size: 12, weight: '600'}}},
                    y: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            color: '#000',
                            font: {size: 12},
                            stepSize: 20,
                            callback: v => v + '%'
                        },
                        grid: {color: '#eee'}
                    },
                    y1: {
                        position: 'right',
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            color: '#000',
                            font: {size: 12},
                            stepSize: 20,
                            callback: v => v + '%'
                        },
                        grid: {display: false}
                    }
                }
            }
        });
    }

    // ── 3. GATE ACTIVITY DONUT CHART ──────────────────────────
    const gateCanvas = document.getElementById('gateChart');
    if (gateCanvas) {
        const gateChart = new Chart(gateCanvas, {
            type: 'doughnut',
            data: {
                labels: ['Enter', 'Exit', 'Outside'],
                datasets: [{
                    data: [0, 0, 0],
                    backgroundColor: ['#219EBC', '#ffb703', '#ff7f00'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                cutout: '65%',
                animation: false,
                plugins: { legend: { display: false } }
            }
        });

        async function updateGateChart() {
            try {
                const res = await fetch('/api/dashboard/analytics/gate-activity-donut');
                const data = await res.json(); // [entries, exits, never_showed]
                gateChart.data.datasets[0].data = data;
                gateChart.update();
                
                // Update the total students in the center if needed
                const total = data.reduce((a, b) => a + b, 0);
                const centerText = document.querySelector('.chart-center h2');
                if (centerText) centerText.textContent = total;
            } catch (err) {
                console.error('Failed to fetch gate activity:', err);
            }
        }
        updateGateChart();
    }

});

// ── 4. DEPARTMENT ATTENDANCE LINE CHART ───────────────────
const deptCanvas = document.getElementById('department-attendance-Chart');
if (deptCanvas) {
    const colors = { 1: '#54c9ff', 2: '#ffb703', 3: '#ff7f00', 4: '#6a4cff' };
    let dynamicAttendanceData = {};

    const deptChart = new Chart(deptCanvas.getContext('2d'), {
        type: 'line',
        data: { labels: ['A', 'B', 'C', 'D'], datasets: [] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: { color: '#000', boxWidth: 12, boxHeight: 12, font: { size: 14, weight: '600' } }
                }
            },
            scales: {
                y: {
                    min: 0,
                    max: 100,
                    ticks: {
                        color: '#000',
                        font: { size: 12 },
                        stepSize: 20,
                        callback: v => v + '%'
                    },
                    grid: { drawBorder: false }
                },
                y1: {
                    position: 'right',
                    min: 0,
                    max: 100,
                    ticks: {
                        color: '#000',
                        font: { size: 12 },
                        stepSize: 20,
                        callback: v => v + '%'
                    },
                    grid: { display: false }
                },
                x: { grid: { display: false }, ticks: { color: '#000', font: { size: 12, weight: '600' } } }
            }
        }
    });

    function createDatasets(source) {
        return Object.keys(source.years).map(year => ({
            label: `Year ${year}`,
            data: source.years[year],
            borderColor: colors[year],
            backgroundColor: colors[year] + '33',
            fill: true,
            tension: 0.3,
            pointRadius: 4
        }));
    }

    function getAverageForAll(data) {
        const years = { 1: [0,0,0,0], 2: [0,0,0,0], 3: [0,0,0,0], 4: [0,0,0,0] };
        const depts = Object.values(data);
        if (depts.length === 0) return { years };

        [1,2,3,4].forEach(y => {
            for (let i=0; i<4; i++) {
                let sum = 0;
                depts.forEach(d => { sum += d.years[y][i]; });
                years[y][i] = Math.round(sum / depts.length);
            }
        });
        return { years };
    }

    async function updateDeptChart() {
        try {
            const res = await fetch('/api/dashboard/analytics/dept-attendance');
            dynamicAttendanceData = await res.json();

            const roleSelect = document.getElementById('role');
            const currentDept = roleSelect ? roleSelect.value : 'All';

            let source = currentDept === 'All' ? getAverageForAll(dynamicAttendanceData) : dynamicAttendanceData[currentDept];

            // If the selected department has no data, show zeros
            if (!source) {
                source = { years: { 1: [0,0,0,0], 2: [0,0,0,0], 3: [0,0,0,0], 4: [0,0,0,0] } };
            }

            deptChart.data.datasets = createDatasets(source);
            deptChart.update();
        } catch (err) {
            console.error('Failed to fetch department attendance:', err);
        }
    }
    updateDeptChart();

    document.getElementById('role')?.addEventListener('change', (e) => {
        const dept = e.target.value;
        let source = dept === 'All' ? getAverageForAll(dynamicAttendanceData) : dynamicAttendanceData[dept];

        if (!source) {
            source = { years: { 1: [0,0,0,0], 2: [0,0,0,0], 3: [0,0,0,0], 4: [0,0,0,0] } };
        }

        deptChart.data.datasets = createDatasets(source);
        deptChart.update();
    });
}
