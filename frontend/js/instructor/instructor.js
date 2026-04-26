/* ═══════════════════════════════════════════════════════════════════════════════════
   INSTRUCTOR.JS - Student Section Tab Management & Controls for Instructor Dashboard
   ═══════════════════════════════════════════════════════════════════════════════════ */

// Store the currently selected subject ID for the Student section
let currentSelectedSubjectId = null;
let currentSelectedSubjectName = null;
let currentSelectedSubjectCode = null;

/**
 * Set the currently selected subject (called from subject card clicks)
 */
function setSelectedSubject(subjectId, subjectName, subjectCode) {
    currentSelectedSubjectId = subjectId;
    currentSelectedSubjectName = subjectName;
    currentSelectedSubjectCode = subjectCode || '—';
    console.log(`[instructor.js] Selected subject: ${subjectName} (ID: ${subjectId}, Code: ${subjectCode})`);
}

/**
 * Get the currently selected subject ID
 */
function getSelectedSubjectId() {
    return currentSelectedSubjectId;
}

/* ─── ENROLLED STUDENTS TAB ────────────────────────────────────────────────────── */

/**
 * Show enrolled students tab
 * Displays currently enrolled students in the subject
 */
function showEnrolledStudents() {
    console.log('[showEnrolledStudents] Switching to enrolled students tab');
    
    const enrolledBtn = document.getElementById('enrolledBtn');
    const newStudentBtn = document.getElementById('newStudentBtn');
    const enrolledTable = document.getElementById('enrolledTable');
    const newStudentTable = document.getElementById('newStudentTable');

    if (!enrolledBtn || !newStudentBtn || !enrolledTable || !newStudentTable) {
        console.error('[showEnrolledStudents] Required DOM elements not found');
        return;
    }

    // Update button states
    enrolledBtn.classList.add('active');
    newStudentBtn.classList.remove('active');

    // Show enrolled, hide new student
    enrolledTable.style.display = 'block';
    newStudentTable.style.display = 'none';

    console.log('[showEnrolledStudents] Enrolled students tab is now visible');
}

/**
 * Render enrolled students list
 * @param {number} subjectId - Subject ID
 * @param {Array} enrolledStudents - Array of enrolled student objects
 */
function renderEnrolledStudents(subjectId, enrolledStudents) {
    const enrolledBody = document.querySelector('#enrolledTable tbody');
    
    if (!enrolledBody) {
        console.error('[renderEnrolledStudents] Enrolled table body not found');
        return;
    }

    console.log(`[renderEnrolledStudents] Rendering ${enrolledStudents.length} enrolled students`);
    
    enrolledBody.innerHTML = '';

    if (enrolledStudents.length === 0) {
        enrolledBody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align:center; padding:20px; color:#64748b;">
                    <i class="fas fa-inbox"></i> No enrolled students found.
                </td>
            </tr>
        `;
        return;
    }

    enrolledStudents.forEach(student => {
        const tr = document.createElement('tr');
        const studentName = (student.first_name || student.last_name)
            ? `${student.first_name || ''} ${student.last_name || ''}`.trim()
            : (student.email || '—');
        const attendance = student.attendance_pct || 0;
        const attendanceClass = attendance >= 80 ? 'completed' : attendance >= 60 ? 'in-progress' : 'scheduled';

        tr.innerHTML = `
            <td>${student.student_id || '—'}</td>
            <td>${studentName}</td>
            <td>${student.section || '—'}</td>
            <td><span class="status ${attendanceClass}">${attendance}%</span></td>
            <td class="actions">
                ${student.user_id ? `<button class="delete" onclick="removeStudent(${subjectId}, ${student.user_id})">Remove</button>` : ''}
            </td>
        `;
        enrolledBody.appendChild(tr);
    });

    console.log('[renderEnrolledStudents] Enrolled students rendered successfully');
}

/* ─── NEW STUDENTS (PENDING) TAB ──────────────────────────────────────────────── */

/**
 * Show new students (pending applications) tab
 * Displays students who have applied but not yet been accepted
 */
function showNewStudents() {
    console.log('[showNewStudents] Switching to new students tab');
    
    const enrolledBtn = document.getElementById('enrolledBtn');
    const newStudentBtn = document.getElementById('newStudentBtn');
    const enrolledTable = document.getElementById('enrolledTable');
    const newStudentTable = document.getElementById('newStudentTable');

    if (!enrolledBtn || !newStudentBtn || !enrolledTable || !newStudentTable) {
        console.error('[showNewStudents] Required DOM elements not found');
        return;
    }

    // Update button states
    newStudentBtn.classList.add('active');
    enrolledBtn.classList.remove('active');

    // Show new student, hide enrolled
    enrolledTable.style.display = 'none';
    newStudentTable.style.display = 'block';

    console.log('[showNewStudents] New students tab is now visible');
}

/**
 * Render pending students list
 * @param {number} subjectId - Subject ID
 * @param {Array} pendingStudents - Array of pending student objects
 */
function renderNewStudents(subjectId, pendingStudents) {
    const newStudentBody = document.querySelector('#newStudentTable tbody');
    
    if (!newStudentBody) {
        console.error('[renderNewStudents] New student table body not found');
        return;
    }

    console.log(`[renderNewStudents] Rendering ${pendingStudents.length} pending students`);
    
    newStudentBody.innerHTML = '';

    if (pendingStudents.length === 0) {
        newStudentBody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align:center; padding:20px; color:#64748b;">
                    <i class="fas fa-check-circle"></i> No pending applications for this subject.
                </td>
            </tr>
        `;
        return;
    }

    pendingStudents.forEach(student => {
        const tr = document.createElement('tr');
        const appliedAt = student.enrolled_at
            ? new Date(student.enrolled_at).toLocaleString()
            : '—';
        const studentName = `${student.first_name || ''} ${student.last_name || ''}`.trim() || '—';
        const displayId = student.student_id || '—';
        const section = student.section || '—';
        const status = student.status || 'pending';
        const internalUserId = student.user_id;

        tr.innerHTML = `
            <td>${displayId}</td>
            <td>${section}</td>
            <td>${studentName}</td>
            <td>${appliedAt}</td>
            <td><span class="status pending">${status}</span></td>
            <td class="actions">
                ${internalUserId ? `<button class="edit" onclick="acceptStudent(${subjectId}, ${internalUserId}, 'accept')">Accept</button>
                <button class="delete" onclick="acceptStudent(${subjectId}, ${internalUserId}, 'reject')">Reject</button>` : '<span css="color:#64748b">No actions</span>'}
            </td>
        `;
        newStudentBody.appendChild(tr);
    });

    console.log('[renderNewStudents] Pending students rendered successfully');
}

/**
 * Accept all pending students for a subject
 */
async function acceptAllStudents() {
    // Try to get subject ID from button dataset first, then from stored value
    const acceptAllBtn = document.getElementById('acceptAllBtn');
    let subjectId = acceptAllBtn?.dataset.subjectId || currentSelectedSubjectId;

    if (!subjectId) {
        alert('No subject selected. Please select a subject card from the left panel first.');
        console.warn('[acceptAllStudents] No subject ID found. Dataset:', acceptAllBtn?.dataset.subjectId, 'Stored:', currentSelectedSubjectId);
        return;
    }

    if (!confirm('Accept all pending students for this subject?')) {
        return;
    }

    try {
        console.log(`[acceptAllStudents] Accepting all students for subject ${subjectId}`);
        
        // Call endpoint to accept all
        const res = await fetch(`/api/subjects/${subjectId}/students/accept-all`, {
            method: 'POST',
            credentials: 'same-origin'
        });

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Batch acceptance failed');
        }

        console.log('[acceptAllStudents] Batch acceptance successful');

        // Reload the student list
        if (typeof loadSubjectStudents === 'function') {
            await loadSubjectStudents(subjectId, currentSelectedSubjectName || 'Subject');
        }

        // Switch to enrolled tab
        showEnrolledStudents();
        alert('All pending students have been accepted!');

    } catch (err) {
        alert(`Error: ${err.message}`);
        console.error('[acceptAllStudents] Error:', err);
    }
}

/**
 * Initialize student section tab toggle functionality
 * Handles switching between "Enrolled" and "New Student" tabs
 */
function initStudentSectionTabs() {
    const enrolledBtn = document.getElementById('enrolledBtn');
    const newStudentBtn = document.getElementById('newStudentBtn');
    const acceptAllBtn = document.getElementById('acceptAllBtn');
    const studentListPanel = document.getElementById('studentListPanel');

    if (!enrolledBtn || !newStudentBtn) {
        console.warn('[initStudentSectionTabs] Student tab buttons not found - skipping initialization');
        return;
    }

    console.log('[initStudentSectionTabs] Initializing student section tabs...');

    // ─── Enrolled Tab Handler ───
    enrolledBtn.addEventListener('click', (e) => {
        e.preventDefault();
        console.log('[initStudentSectionTabs] Enrolled button clicked');
        showEnrolledStudents();
    });

    // ─── New Student Tab Handler ───
    newStudentBtn.addEventListener('click', (e) => {
        e.preventDefault();
        console.log('[initStudentSectionTabs] New Student button clicked');
        showNewStudents();

        // After showing the New Student tab, reload pending students for the selected subject.
        (async () => {
            // Try stored subject id first
            let subjectId = currentSelectedSubjectId;
            // Fallback to acceptAllBtn dataset
            const acceptAllBtn = document.getElementById('acceptAllBtn');
            if (!subjectId && acceptAllBtn) subjectId = acceptAllBtn.dataset.subjectId;

            if (!subjectId) {
                // Try to auto-click the first subject card in the student list (if present)
                const firstCard = document.querySelector('#student-subject-list .subject-card');
                if (firstCard) {
                    console.log('[initStudentSectionTabs] No subject selected — auto-clicking first subject card');
                    firstCard.click();
                    return;
                }

                console.warn('[initStudentSectionTabs] No subject selected and no subject cards available');
                return;
            }

            if (typeof loadSubjectStudents === 'function') {
                try {
                    await loadSubjectStudents(subjectId, currentSelectedSubjectName || 'Subject');
                } catch (err) {
                    console.error('[initStudentSectionTabs] Error loading pending students:', err);
                }
            }
        })();
    });

    // ─── Accept All Button Handler ───
    acceptAllBtn?.addEventListener('click', acceptAllStudents);

    // ─── Show helper message if no subject selected ───
    if (studentListPanel) {
        // Listen for when the Student section becomes visible
        const observer = new MutationObserver(() => {
            const studentSection = document.getElementById('student');
            if (studentSection && studentSection.style.display !== 'none' && !currentSelectedSubjectId) {
                console.log('[initStudentSectionTabs] Student section visible but no subject selected');
                // The subject cards should auto-click the first one, but if not, we wait
            }
        });
        
        observer.observe(document.body, { subtree: true, attributes: true });
    }

    console.log('[initStudentSectionTabs] Student section tabs initialized successfully');
}

/**
 * Initialize all instructor dashboard functionality
 */
function initInstructorDashboard() {
    console.log('[Instructor] Initializing instructor dashboard...');
    initStudentSectionTabs();
    initReportHandlers();
}

/**
 * Initialize report download handlers
 */
function initReportHandlers() {
    const pdfBtn = document.getElementById('download-monthly-pdf');
    const csvBtn = document.getElementById('download-attendance-csv');
    const printBtn = document.getElementById('print-attendance-summary');

    pdfBtn?.addEventListener('click', () => {
        console.log('[Reports] Generating PDF...');
        window.print(); // Simplest way to "save as PDF" for a dashboard
    });

    csvBtn?.addEventListener('click', async () => {
        console.log('[Reports] Exporting CSV...');
        await exportAttendanceToCSV();
    });

    printBtn?.addEventListener('click', () => {
        console.log('[Reports] Printing summary...');
        window.print();
    });
}

/**
 * Export attendance data to CSV using SheetJS
 */
async function exportAttendanceToCSV() {
    // Check if XLSX is loaded (still useful for data formatting even for CSV)
    if (typeof XLSX === 'undefined') {
        alert('Export library (SheetJS) is not loaded correctly. Please refresh the page.');
        console.error('[exportAttendanceToCSV] XLSX library not found');
        return;
    }

    const subjectId = currentSelectedSubjectId;
    if (!subjectId) {
        alert('Please select a subject from the Students or Subjects section first to export its attendance.');
        return;
    }

    try {
        // 1. Fetch instructor profile to get name
        const profileRes = await fetch('/api/user/profile', { credentials: 'same-origin' });
        let instructorName = 'Instructor';
        if (profileRes.ok) {
            const profile = await profileRes.json();
            instructorName = `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || 'Instructor';
        }

        // 2. Fetch students for the subject to get their attendance %
        const res = await fetch(`/api/subjects/${subjectId}/students?status=enrolled`, {
            credentials: 'same-origin'
        });
        
        if (!res.ok) throw new Error('Failed to fetch attendance data');
        const students = await res.json();

        if (students.length === 0) {
            alert('No enrolled students found for this subject.');
            return;
        }

        // 3. Create data array for SheetJS (aoa = array of arrays)
        const data = [
            ["InSight Attendance"],
            [instructorName],
            [currentSelectedSubjectCode || '—', currentSelectedSubjectName || '—'],
            [], // Blank row
            ["Student ID", "Full Name", "Section", "Attendance %"] // Column Headers
        ];
        
        // 4. Add student data rows
        students.forEach(s => {
            const name = `${s.first_name || ''} ${s.last_name || ''}`.trim();
            data.push([
                s.student_id || '',
                name,
                s.section || '',
                `${s.attendance_pct || 0}%`
            ]);
        });

        // 5. Create a SheetJS worksheet from the array
        const ws = XLSX.utils.aoa_to_sheet(data);

        // 6. Convert worksheet to CSV string
        const csv = XLSX.utils.sheet_to_csv(ws);
        
        const safeSubjectName = currentSelectedSubjectName ? currentSelectedSubjectName.replace(/[^a-z0-9]/gi, '_') : 'Subject';
        const fileName = `Attendance_Report_${safeSubjectName}_${new Date().toISOString().split('T')[0]}.csv`;
        
        // 7. Trigger download
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', fileName);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

    } catch (err) {
        console.error('[exportAttendanceToCSV] Error:', err);
        alert('Failed to export attendance data: ' + err.message);
    }
}

/* ─── Load on DOM Ready ───────────────────────────────────────────────────────── */

// Use MutationObserver to handle dynamic DOM loading
document.addEventListener('DOMContentLoaded', () => {
    // Give page-show.js time to initialize
    setTimeout(() => {
        initInstructorDashboard();
    }, 100);
});

// Also try immediate initialization in case DOM is already ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initInstructorDashboard);
} else {
    setTimeout(initInstructorDashboard, 100);
}
