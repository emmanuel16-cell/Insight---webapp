"""
dashboards.py  –  Role-Based Dashboards
Provides dashboard statistics and data for Admin, Instructor, and Student.
"""

import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request
from dotenv import load_dotenv

from auth import get_db, require_session

load_dotenv()

router = APIRouter(prefix="/api/dashboard")

# ── ADMIN DASHBOARD ───────────────────────────────────────

@router.get("/admin")
async def admin_dashboard(request: Request):
    """
    Admin dashboard with system-wide statistics.
    Total students, instructors, courses, today's gate logs, etc.
    """
    session = require_session(request)

    if session.get("role") != "admin":
        raise HTTPException(403, "Only admins can access admin dashboard")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Total users by role
    cur.execute("""
        SELECT role, COUNT(*) as count FROM users GROUP BY role
    """)
    user_stats = {row["role"]: row["count"] for row in cur.fetchall()}

    # Total courses (now using subjects table)
    cur.execute("SELECT COUNT(*) as count FROM subjects")
    total_courses = cur.fetchone()["count"]

    # Total enrollments (now using subject_enrollments table)
    cur.execute("SELECT COUNT(*) as count FROM subject_enrollments WHERE status = 'enrolled'")
    total_enrollments = cur.fetchone()["count"]

    # Today's gate summary (aggregated from gate_logs)
    today = datetime.now().date()
    cur.execute("""
        SELECT 
            COUNT(DISTINCT student_id) as total_checked_in,
            MAX(has_uniform) as with_uniform,
            MAX(has_id_card) as with_id_card
        FROM gate_logs
        WHERE DATE(timestamp) = %s AND event_type = 'check_in'
        GROUP BY student_id
    """, (today,))
    grows = cur.fetchall()
    total_checked_in = len(grows)
    with_uniform = sum(1 for row in grows if row["with_uniform"])
    with_id_card = sum(1 for row in grows if row["with_id_card"])
    
    gate_stats = {
        "total_checked_in": total_checked_in,
        "with_uniform": with_uniform,
        "with_id_card": with_id_card,
    }

    # Recent users (last 7 days)
    week_ago = datetime.now() - timedelta(days=7)
    cur.execute("""
        SELECT COUNT(*) as count FROM users WHERE created_at >= %s
    """, (week_ago,))
    new_users_week = cur.fetchone()["count"]

    # Top courses by enrollment (now using subjects table)
    cur.execute("""
        SELECT s.id, s.code as course_code, s.name as course_name, COUNT(se.id) as enrollment_count
        FROM subjects s
        LEFT JOIN subject_enrollments se ON se.enroll_code = s.join_code AND se.status = 'enrolled'
        GROUP BY s.id
        ORDER BY enrollment_count DESC
        LIMIT 5
    """)
    top_courses = [dict(row) for row in cur.fetchall()]

    # Gate security summary (last ~24h) using aggregated gate_logs
    start_date_24h = (datetime.now() - timedelta(days=1)).date()
    cur.execute("""
        SELECT 
            COUNT(DISTINCT student_id) as total_entries,
            MAX(has_uniform) as with_uniform,
            MAX(has_id_card) as with_id_card
        FROM gate_logs
        WHERE DATE(timestamp) >= %s AND event_type = 'check_in'
        GROUP BY student_id, DATE(timestamp)
    """, (start_date_24h,))
    gsums = cur.fetchall()
    total_entries = len(gsums)
    with_uniform = sum(1 for row in gsums if row["with_uniform"])
    with_id_card = sum(1 for row in gsums if row["with_id_card"])
    
    gate_summary = {
        "total_entries": total_entries,
        "with_uniform": with_uniform,
        "with_id_card": with_id_card,
        "uniform_pct": round((with_uniform / total_entries * 100), 2) if total_entries else 0,
        "id_card_pct": round((with_id_card / total_entries * 100), 2) if total_entries else 0,
    }

    cur.close()
    db.close()

    return {
        "admin_id": session["user_id"],
        "user_statistics": {
            "total_admins": user_stats.get("admin", 0),
            "total_instructors": user_stats.get("instructor", 0),
            "total_students": user_stats.get("student", 0),
            "new_users_this_week": new_users_week,
        },
        "course_statistics": {
            "total_courses": total_courses,
            "total_enrollments": total_enrollments,
            "top_courses": top_courses,
        },
        "gate_security": {
            "today_entries": gate_stats,
            "last_24h_summary": gate_summary,
        },
    }


# ── INSTRUCTOR DASHBOARD ──────────────────────────────────

@router.get("/instructor")
async def instructor_dashboard(request: Request, filter: str = "today"):
    """
    Instructor dashboard with updated subjects-system statistics.
    """
    session = require_session(request)

    if session.get("role") != "instructor":
        raise HTTPException(403, "Only instructors can access instructor dashboard")

    instructor_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    try:
        # Date filter logic
        date_filter = ""
        params = [instructor_id]
        if filter == "today":
            date_filter = " AND DATE(gl.timestamp) = CURDATE()"
        elif filter == "weekly":
            date_filter = " AND DATE(gl.timestamp) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
        elif filter == "monthly":
            date_filter = " AND DATE(gl.timestamp) >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"

        # 1. All Subjects
        cur.execute("SELECT COUNT(*) as count FROM subjects WHERE instructor_id = %s", (instructor_id,))
        total_subjects = cur.fetchone()["count"]

        # 2. Sessions Done (Total unique dates with check-ins for instructor's subjects)
        cur.execute("""
            SELECT COUNT(DISTINCT DATE(gl.timestamp)) as count
            FROM gate_logs gl
            JOIN user_profiles p ON p.user_id = gl.user_id
            JOIN subject_enrollments e ON e.student_id = p.student_id
            JOIN subjects s ON e.enroll_code = s.join_code
            WHERE s.instructor_id = %s AND gl.event_type = 'check_in'
        """, (instructor_id,))
        total_sessions = cur.fetchone()["count"]

        # 3. All Students (Unique enrolled students across all instructor's subjects)
        cur.execute("""
            SELECT COUNT(DISTINCT e.student_id) as count 
            FROM subject_enrollments e 
            JOIN subjects s ON e.enroll_code = s.join_code 
            WHERE s.instructor_id = %s AND e.status = 'enrolled'
        """, (instructor_id,))
        total_students = cur.fetchone()["count"]

        # 4. Avg Attendance (Average of all student attendance rates)
        # Rate = (days present) / (total unique class dates)
        if total_sessions > 0:
            cur.execute(f"""
                SELECT 
                    (COUNT(DISTINCT DATE(gl.timestamp)) / %s) * 100 as student_avg
                FROM gate_logs gl
                JOIN user_profiles p ON p.user_id = gl.user_id
                JOIN subject_enrollments e ON e.student_id = p.student_id
                JOIN subjects s ON e.enroll_code = s.join_code
                WHERE s.instructor_id = %s AND gl.event_type = 'check_in' {date_filter}
                GROUP BY gl.user_id
            """, (total_sessions, instructor_id))
            student_avgs = [row["student_avg"] for row in cur.fetchall()]
            avg_attendance = round(sum(student_avgs) / len(student_avgs), 1) if student_avgs else 0
        else:
            avg_attendance = 0

        # 5. Donut Chart Data (Status counts based on gate_logs)
        # We need to determine late status by comparing min(timestamp) with sc.start_time
        cur.execute(f"""
            SELECT 
                SUM(CASE WHEN TIME(gl.min_ts) <= sc.start_time THEN 1 ELSE 0 END) as present,
                SUM(CASE WHEN TIME(gl.min_ts) > sc.start_time THEN 1 ELSE 0 END) as late
            FROM (
                SELECT gl.user_id, DATE(gl.timestamp) as date, MIN(gl.timestamp) as min_ts, DAYNAME(gl.timestamp) as day_name
                FROM gate_logs gl
                WHERE gl.event_type = 'check_in'
                GROUP BY gl.user_id, DATE(gl.timestamp)
            ) gl
            JOIN user_profiles p ON p.user_id = gl.user_id
            JOIN subject_enrollments e ON e.student_id = p.student_id
            JOIN subjects s ON e.enroll_code = s.join_code
            JOIN schedules sc ON sc.subject_id = s.id AND sc.day_of_week = gl.day_name
            WHERE s.instructor_id = %s {date_filter.replace('DATE(gl.timestamp)', 'gl.date')}
        """, (instructor_id,))
        row = cur.fetchone()
        present_count = row["present"] or 0
        late_count = row["late"] or 0
        
        # Absent calculation: (Total students * total sessions) - (present + late)
        absent_count = max(0, (total_students * total_sessions) - (present_count + late_count))
        
        donut_data = {
            "present": int(present_count),
            "late": int(late_count),
            "absent": int(absent_count)
        }

        # 6. Section Comparison
        cur.execute("""
            SELECT 
                e.section,
                ROUND((COUNT(DISTINCT gl.user_id, DATE(gl.timestamp)) / (COUNT(DISTINCT e.student_id) * %s)) * 100, 1) as attendance_pct
            FROM subject_enrollments e
            JOIN subjects s ON e.enroll_code = s.join_code
            LEFT JOIN user_profiles p ON p.student_id = e.student_id
            LEFT JOIN gate_logs gl ON gl.user_id = p.user_id AND gl.event_type = 'check_in'
            WHERE s.instructor_id = %s AND e.status = 'enrolled'
            GROUP BY e.section
            ORDER BY attendance_pct DESC
        """, (total_sessions if total_sessions > 0 else 1, instructor_id))
        section_comparison = [dict(row) for row in cur.fetchall()]

        # 7. Recent Sessions (Last 5 unique dates with check-ins)
        cur.execute("""
            SELECT 
                DATE(gl.timestamp) as date,
                s.name as subject_name,
                s.code as subject_code,
                sc.start_time as start_time,
                sc.end_time as end_time,
                e.section,
                'completed' as status,
                SUM(CASE WHEN TIME(gl.min_ts) <= sc.start_time THEN 1 ELSE 0 END) as present_count,
                SUM(CASE WHEN TIME(gl.min_ts) > sc.start_time THEN 1 ELSE 0 END) as late_count
            FROM (
                SELECT gl.user_id, DATE(gl.timestamp) as date, MIN(gl.timestamp) as min_ts, DAYNAME(gl.timestamp) as day_name
                FROM gate_logs gl
                WHERE gl.event_type = 'check_in'
                GROUP BY gl.user_id, DATE(gl.timestamp)
            ) gl
            JOIN user_profiles p ON p.user_id = gl.user_id
            JOIN subject_enrollments e ON e.student_id = p.student_id
            JOIN subjects s ON e.enroll_code = s.join_code
            JOIN schedules sc ON sc.subject_id = s.id AND sc.day_of_week = gl.day_name
            WHERE s.instructor_id = %s
            GROUP BY DATE(gl.timestamp), s.id, e.section, sc.id
            ORDER BY date DESC
            LIMIT 5
        """, (instructor_id,))
        recent_sessions = [dict(row) for row in cur.fetchall()]
        # Format dates and times for JSON
        for sess in recent_sessions:
            sess["id"] = f"{sess['date']}_{sess['subject_code']}" # Virtual ID
            sess["date"] = str(sess["date"])
            sess["start_time"] = str(sess["start_time"])
            sess["end_time"] = str(sess["end_time"])
            # In gate logs, we combine present and late for 'present_count' if that's what UI expects
            # Or keep them separate. The original code had present_count and absent_count.
            # I'll combine present+late into present_count and calculate absent_count.
            p_c = int(sess["present_count"] or 0)
            l_c = int(sess["late_count"] or 0)
            
            # Get total students for this specific subject/section to calculate absent
            cur.execute("""
                SELECT COUNT(*) as count 
                FROM subject_enrollments 
                WHERE enroll_code = (SELECT join_code FROM subjects WHERE code = %s LIMIT 1)
                AND section = %s AND status = 'enrolled'
            """, (sess["subject_code"], sess["section"]))
            subj_total = cur.fetchone()["count"]
            
            sess["present_count"] = p_c + l_c
            sess["absent_count"] = max(0, subj_total - (p_c + l_c))
            sess["end_time"] = str(sess["end_time"])

        return {
            "instructor_id": instructor_id,
            "statistics": {
                "avg_attendance": avg_attendance,
                "total_students": total_students,
                "total_sessions": total_sessions,
                "total_subjects": total_subjects
            },
            "donut_data": donut_data,
            "section_comparison": section_comparison,
            "recent_sessions": recent_sessions
        }

    finally:
        cur.close()
        db.close()


# ── STUDENT DASHBOARD ─────────────────────────────────────

@router.get("/student")
async def student_dashboard(request: Request):
    """
    Student dashboard with enrolled subjects, session attendance records, and QR code.
    """
    session = require_session(request)

    if session.get("role") != "student":
        raise HTTPException(403, "Only students can access student dashboard")

    student_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    # Student profile
    cur.execute("""
        SELECT u.email, p.student_id, p.first_name, p.last_name,
               p.gender, p.section, p.contact, p.avatar_url
        FROM users u
        LEFT JOIN user_profiles p ON p.user_id = u.id
        WHERE u.id = %s
    """, (student_id,))
    profile = cur.fetchone()
    
    # Use the student_id string code for enrollments (e.g., "2023-0193")
    stu_code = profile["student_id"] if profile and profile.get("student_id") else str(student_id)

    # Enrolled subjects with attendance stats using gate_logs and schedules
    cur.execute("""
        SELECT
            s.id,
            s.code AS course_code,
            s.name AS course_name,
            s.join_code,
            CONCAT(ip.first_name, ' ', ip.last_name) AS instructor_name
        FROM subjects s
        JOIN subject_enrollments e ON e.enroll_code = s.join_code
        LEFT JOIN users iu ON iu.id = s.instructor_id
        LEFT JOIN user_profiles ip ON ip.user_id = iu.id
        WHERE e.student_id = %s AND e.status = 'enrolled'
        GROUP BY s.id
        ORDER BY s.name
    """, (stu_code,))
    enrolled_courses = [dict(row) for row in cur.fetchall()]
    
    # Calculate attendance for each course using schedules
    for course in enrolled_courses:
        subject_id = course['id']
        
        # 1. Total sessions (opportunities) so far
        # We'll count how many schedules occurred since the student enrolled or in the last 30 days
        cur.execute("SELECT day_of_week FROM schedules WHERE subject_id = %s", (subject_id,))
        subject_schedules = cur.fetchall()
        
        total_opportunities = 0
        num_days = 30 # Default lookback
        import datetime
        today = datetime.date.today()
        for i in range(num_days):
            d = today - datetime.timedelta(days=i)
            day_name = d.strftime('%A')
            schedules_this_day = [s for s in subject_schedules if s['day_of_week'] == day_name]
            total_opportunities += len(schedules_this_day)
            
        course["total_sessions"] = total_opportunities
        
        # 2. Present count (matches between gate_logs and schedules)
        # We join each schedule instance with the best check-in for that day
        cur.execute("""
            SELECT COUNT(*) as count
            FROM schedules sc
            JOIN subjects s ON sc.subject_id = s.id
            JOIN subject_enrollments e ON e.enroll_code = s.join_code
            JOIN user_profiles p ON p.student_id = e.student_id
            JOIN (
                SELECT user_id, DATE(timestamp) as log_date, MIN(timestamp) as first_in, DAYNAME(timestamp) as log_day
                FROM gate_logs
                WHERE user_id = %s AND event_type = 'check_in'
                GROUP BY DATE(timestamp)
            ) gl ON gl.user_id = p.user_id AND gl.log_day = sc.day_of_week
            WHERE s.id = %s AND e.student_id = %s AND gl.log_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        """, (user_id, subject_id, stu_code, num_days))
        
        course["present_count"] = cur.fetchone()["count"] or 0
        course["absent_count"] = max(0, total_opportunities - course["present_count"])
        course["out_range_count"] = 0
    
    # 4. Recent Biometric Logs (Combined Gate, Subject)
    # We'll fetch more than 5 for each to ensure we have enough after combining and filtering
    
    # Gate logs (aggregated by date)
    cur.execute("""
        SELECT 'Gate' AS type, DATE(timestamp) AS `date`, MIN(timestamp) AS time,
               CASE WHEN MAX(CASE WHEN event_type='check_out' THEN 1 ELSE 0 END) = 1 THEN 'Exit' ELSE 'Entry' END AS status,
               'Campus Gate' AS name,
               MIN(timestamp) as sort_time
        FROM gate_logs
        WHERE user_id = %s AND event_type IN ('check_in', 'check_out')
        GROUP BY DATE(timestamp)
        ORDER BY `date` DESC
        LIMIT 10
    """, (student_id,))
    gate_rows = cur.fetchall()

    # Subject logs (from gate_logs where event_type='check_in' matched with schedules)
    # Grouped by log to avoid showing the same entry multiple times for different schedules
    cur.execute("""
        SELECT 'Subject' AS type, DATE(gl.timestamp) as `date`, gl.timestamp AS time,
               MIN(CASE WHEN TIME(gl.timestamp) <= sc.start_time THEN 'present' ELSE 'late' END) as status,
               s.name, gl.timestamp as sort_time
        FROM gate_logs gl
        JOIN user_profiles p ON p.user_id = gl.user_id
        JOIN subject_enrollments e ON e.student_id = p.student_id
        JOIN subjects s ON e.enroll_code = s.join_code
        JOIN schedules sc ON sc.subject_id = s.id AND sc.day_of_week = DAYNAME(gl.timestamp)
        WHERE gl.user_id = %s AND gl.event_type = 'check_in'
        GROUP BY gl.id, s.id
        ORDER BY gl.timestamp DESC
        LIMIT 10
    """, (user_id,))
    subject_rows = cur.fetchall()

    # Combine and sort
    all_recent_logs = []
    for r in gate_rows + subject_rows:
        row_dict = dict(r)
        # Convert date/time objects to strings for JSON
        if row_dict.get('date'):
            row_dict['date'] = str(row_dict['date'])
        if row_dict.get('time'):
            row_dict['time'] = str(row_dict['time'])
        # Keep sort_time as object for sorting, convert to string later if needed
        all_recent_logs.append(row_dict)

    # Sort by sort_time descending (handles datetime objects correctly)
    all_recent_logs.sort(key=lambda x: x.get('sort_time') or datetime.min, reverse=True)
    recent_logs = []
    for log in all_recent_logs[:5]:
        if log.get('sort_time'):
            log['sort_time'] = str(log['sort_time'])
        recent_logs.append(log)

    # Line graph data: Student's daily session attendance (last 7 days)
    cur.execute("""
        SELECT
            DATE(gl.timestamp) as `date`,
            COUNT(DISTINCT s.id) AS total,
            COUNT(DISTINCT gl.timestamp) AS present_count
        FROM gate_logs gl
        JOIN user_profiles p ON p.user_id = gl.user_id
        JOIN subject_enrollments e ON e.student_id = p.student_id
        JOIN subjects s ON e.enroll_code = s.join_code
        WHERE gl.user_id = %s AND gl.timestamp >= CURDATE() - INTERVAL 7 DAY AND gl.event_type = 'check_in'
        GROUP BY DATE(gl.timestamp)
        ORDER BY DATE(gl.timestamp) ASC
    """, (student_id,))
    chart_rows = [dict(row) for row in cur.fetchall()]

    # Compute totals
    total_held = sum(c.get('total_sessions', 0) for c in enrolled_courses)
    total_present = sum(c.get('present_count', 0) for c in enrolled_courses)
    total_absent = sum(c.get('absent_count', 0) + c.get('out_range_count', 0) for c in enrolled_courses)
    overall_pct = round(total_present / total_held * 100, 1) if total_held else 0

    # Format chart data
    chart_data = []
    for row in chart_rows:
        rate = round(row['present_count'] / row['total'] * 100, 1) if row['total'] else 0
        chart_data.append({
            'date': row['date'].isoformat() if hasattr(row['date'], 'isoformat') else str(row['date']),
            'me_rate': rate,
            'others_rate': None
        })

    # Facial features status
    cur.execute("SELECT is_verified FROM facial_features WHERE user_id = %s", (student_id,))
    facial_row = cur.fetchone()
    has_facial_features = bool(facial_row and facial_row["is_verified"]) if facial_row else False

    # QR code info
    cur.execute("SELECT qr_image_base64 FROM user_profiles WHERE user_id = %s", (student_id,))
    qr_row = cur.fetchone()
    has_qrcode = bool(qr_row and qr_row.get("qr_image_base64"))

    cur.close()
    db.close()

    return {
        "student_id": student_id,
        "profile": dict(profile) if profile else None,
        "system_status": {
            "has_facial_features": has_facial_features,
            "has_qrcode": has_qrcode,
        },
        "enrolled_courses": enrolled_courses,
        "recent_logs": recent_logs,
        "chart_data": chart_data,
        "statistics": {
            "total_enrolled_courses": len(enrolled_courses),
            "total_sessions_attended": total_present,
            "total_sessions_held": total_held,
            "total_sessions_missed": total_absent,
            "overall_attendance_percentage": overall_pct,
        }
    }


# ── ANALYTICS ENDPOINTS (Admin Only) ──────────────────────

@router.get("/admin/summary-stats")
async def admin_summary_stats(request: Request):
    """Admin: Get summary stats for the 4 top cards."""
    session = require_session(request)
    if session.get("role") != "admin":
        raise HTTPException(403, "Only admins can access summary stats")
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    # Students: All students that are verified
    cur.execute("SELECT COUNT(*) as count FROM users WHERE role = 'student' AND is_verified = 1")
    total_students = cur.fetchone()["count"]
    
    # Instructors: Total active instructors
    cur.execute("SELECT COUNT(*) as count FROM users WHERE role = 'instructor'")
    total_instructors = cur.fetchone()["count"]
    
    # Departments: Total departments
    cur.execute("SELECT COUNT(*) as count FROM departments")
    total_departments = cur.fetchone()["count"]
    
    # Cameras: Total cameras
    cur.execute("SELECT COUNT(*) as count FROM cameras")
    total_cameras = cur.fetchone()["count"]
    
    cur.close()
    db.close()
    
    return {
        "students": total_students,
        "instructors": total_instructors,
        "departments": total_departments,
        "cameras": total_cameras
    }

@router.get("/analytics/attendance-summary")
async def attendance_summary(request: Request):
    """Admin: Get attendance summary (present, late, absent) as percentages per day for the last 7 days."""
    session = require_session(request)
    if session.get("role") != "admin":
        raise HTTPException(403, "Forbidden")
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    # Get last 7 days attendance from gate_logs
    cur.execute("""
        SELECT 
            DATE_FORMAT(gl.date, '%%a') as day,
            COUNT(DISTINCT gl.user_id) as present_total,
            SUM(CASE WHEN TIME(gl.min_ts) <= sc.start_time THEN 1 ELSE 0 END) as present_count,
            SUM(CASE WHEN TIME(gl.min_ts) > sc.start_time THEN 1 ELSE 0 END) as late_count
        FROM (
            SELECT user_id, DATE(timestamp) as date, MIN(timestamp) as min_ts, DAYNAME(timestamp) as day_name
            FROM gate_logs
            WHERE event_type = 'check_in' AND timestamp >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY user_id, DATE(timestamp)
        ) gl
        JOIN user_profiles p ON p.user_id = gl.user_id
        JOIN subject_enrollments e ON e.student_id = p.student_id
        JOIN subjects s ON e.enroll_code = s.join_code
        JOIN schedules sc ON sc.subject_id = s.id AND sc.day_of_week = gl.day_name
        GROUP BY DATE(gl.date)
        ORDER BY DATE(gl.date) ASC
    """)
    rows = cur.fetchall()
    
    # Total students enrolled to calculate absent
    cur.execute("SELECT COUNT(DISTINCT student_id) as count FROM subject_enrollments WHERE status = 'enrolled'")
    total_enrolled = cur.fetchone()["count"] or 1
    
    cur.close()
    db.close()
    
    # Convert counts to percentages
    results = []
    for row in rows:
        present = row['present_count'] or 0
        late = row['late_count'] or 0
        absent = max(0, total_enrolled - (present + late))
        results.append({
            "day": row['day'],
            "present": round((present / total_enrolled) * 100, 1),
            "late": round((late / total_enrolled) * 100, 1),
            "absent": round((absent / total_enrolled) * 100, 1)
        })
    
    return results

@router.get("/analytics/gate-activity-donut")
async def gate_activity_donut(request: Request):
    """Admin: Get gate activity summary (Entry, Exit, Outside)."""
    session = require_session(request)
    if session.get("role") != "admin":
        raise HTTPException(403, "Forbidden")
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    # Logic: 
    # Entry: students who are currently 'in' (last activity was 'entry' today)
    # Exit: students who are currently 'out' (last activity was 'exit' today)
    # Outside: Total students - (Entry + Exit today) -> this is a bit complex.
    # User's chart: [Enter, Exit, Outside] with data [180, 120, 42]
    # Let's interpret "Outside" as students who haven't entered at all today.
    
    today = datetime.now().date()
    
    # Total students enrolled
    cur.execute("SELECT COUNT(DISTINCT student_id) as count FROM subject_enrollments WHERE status = 'enrolled'")
    total_students = cur.fetchone()["count"]
    
    # Get last activity for each student today from gate_logs
    cur.execute("""
        SELECT user_id, event_type
        FROM gate_logs
        WHERE (user_id, timestamp) IN (
            SELECT user_id, MAX(timestamp)
            FROM gate_logs
            WHERE DATE(timestamp) = %s AND event_type IN ('check_in', 'check_out')
            GROUP BY user_id
        )
    """, (today,))
    activities = cur.fetchall()
    
    entries = sum(1 for a in activities if a['event_type'] == 'check_in')
    exits = sum(1 for a in activities if a['event_type'] == 'check_out')
    
    # Students who haven't logged any activity today
    # "Outside" could mean students not in campus (never entered or already exited)
    # Let's follow the user's requirement: "Enter", "Exit", "Outside"
    # "Enter" = students currently inside
    # "Exit" = students who entered and then exited
    # "Outside" = students who never entered today
    
    # Wait, the user's data was [180, 120, 42]. 
    # Let's just return counts of entries, exits, and those who never showed up.
    
    never_showed = max(0, total_students - (entries + exits))
    
    cur.close()
    db.close()
    
    return [entries, exits, never_showed]

@router.get("/analytics/dept-attendance")
async def dept_attendance(request: Request):
    """Admin: Get today's attendance percentage by department and year level."""
    session = require_session(request)
    if session.get("role") != "admin":
        raise HTTPException(403, "Forbidden")
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    # 1. Get all departments to ensure we have them all
    cur.execute("SELECT code FROM departments")
    depts_list = [row['code'] for row in cur.fetchall()]
    
    # Initialize result with all departments
    result = {}
    for dcode in depts_list:
        result[dcode] = {
            "sections": ['A', 'B', 'C', 'D'],
            "years": {1: [0,0,0,0], 2: [0,0,0,0], 3: [0,0,0,0], 4: [0,0,0,0]}
        }
    
    # 2. Get total students per section
    cur.execute("""
        SELECT up.section, COUNT(*) as total 
        FROM user_profiles up
        JOIN users u ON u.id = up.user_id
        WHERE u.role = 'student' AND up.section IS NOT NULL 
        GROUP BY up.section
    """)
    section_totals = {row['section']: row['total'] for row in cur.fetchall()}
    
    # 3. Get today's attendance counts per section from gate_logs
    cur.execute("""
        SELECT 
            up.section,
            COUNT(DISTINCT gl.user_id) as attended_count
        FROM gate_logs gl
        JOIN user_profiles up ON up.user_id = gl.user_id
        WHERE DATE(gl.timestamp) = CURDATE() AND gl.event_type = 'check_in'
        GROUP BY up.section
    """)
    attendance_rows = cur.fetchall()
    
    # 4. Process into percentages
    for row in attendance_rows:
        section_str = row['section']
        if not section_str or '-' not in section_str:
            continue
            
        try:
            dept, rest = section_str.split('-', 1)
            year = int(rest[0])
            section_letter = rest[1:]
            
            if dept not in result:
                result[dept] = {
                    "sections": ['A', 'B', 'C', 'D'],
                    "years": {1: [0,0,0,0], 2: [0,0,0,0], 3: [0,0,0,0], 4: [0,0,0,0]}
                }
            
            total_in_section = section_totals.get(section_str, 1)
            percentage = round((row['attended_count'] / total_in_section) * 100, 1)
            
            idx = ord(section_letter[0].upper()) - ord('A')
            if 0 <= idx < 4 and 1 <= year <= 4:
                result[dept]["years"][year][idx] = min(100.0, percentage)
        except (ValueError, IndexError):
            continue
            
    cur.close()
    db.close()
    
    return result

@router.get("/analytics/attendance-trends")
async def attendance_trends(days: int = 30, request: Request = None):
    """Admin: Get attendance trends over time."""
    if request:
        session = require_session(request)
        if session.get("role") != "admin":
            raise HTTPException(403, "Only admins can view analytics")
    
    db = get_db()
    cur = db.cursor(dictionary=True)

    # Total students for percentage calculation
    cur.execute("SELECT COUNT(*) as count FROM users WHERE role = 'student'")
    total_students = cur.fetchone()["count"] or 1

    start_date = (datetime.now() - timedelta(days=days)).date()

    cur.execute("""
        SELECT 
            DATE(gl.timestamp) as attendance_date,
            COUNT(DISTINCT gl.user_id) as total_records,
            SUM(CASE WHEN TIME(gl.min_ts) <= s.schedule_start THEN 1 ELSE 0 END) as present,
            SUM(CASE WHEN TIME(gl.min_ts) > s.schedule_start THEN 1 ELSE 0 END) as late,
            0 as absent, -- Will calculate below
            ROUND(
                COUNT(DISTINCT gl.user_id) / %s * 100
            , 2) as attendance_rate
        FROM (
            SELECT user_id, DATE(timestamp) as date, MIN(timestamp) as min_ts, timestamp
            FROM gate_logs
            WHERE event_type = 'check_in' AND timestamp >= %s
            GROUP BY user_id, DATE(timestamp)
        ) gl
        JOIN user_profiles p ON p.user_id = gl.user_id
        JOIN subject_enrollments e ON e.student_id = p.student_id
        JOIN subjects s ON e.enroll_code = s.join_code
        GROUP BY DATE(gl.timestamp)
        ORDER BY DATE(gl.timestamp) ASC
    """, (total_students if total_students > 0 else 1, start_date))
    rows = cur.fetchall()
    
    trends = []
    for row in rows:
        present = int(row['present'] or 0)
        late = int(row['late'] or 0)
        absent = max(0, total_students - (present + late))
        trends.append({
            "attendance_date": str(row['attendance_date']),
            "total_records": total_students,
            "present": present,
            "late": late,
            "absent": absent,
            "attendance_rate": row['attendance_rate']
        })
    cur.close()
    db.close()

    return {
        "period_days": days,
        "trends": trends,
    }


@router.get("/analytics/gate-security")
async def gate_security_analytics(days: int = 7, request: Request = None):
    """Admin: Get gate security analytics."""
    if request:
        session = require_session(request)
        if session.get("role") != "admin":
            raise HTTPException(403, "Only admins can view analytics")

    db = get_db()
    cur = db.cursor(dictionary=True)

    start_date = (datetime.now() - timedelta(days=days)).date()

    cur.execute("""
        SELECT 
            DATE(timestamp) as date,
            COUNT(DISTINCT student_id) as total_entries,
            MAX(has_uniform) as with_uniform,
            MAX(has_id_card) as with_id_card
        FROM gate_logs
        WHERE DATE(timestamp) >= %s AND event_type = 'check_in'
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
    """, (start_date,))
    rows = cur.fetchall()
    gate_logs = []
    for row in rows:
        total = row['total_entries']
        u = row['with_uniform']
        i = row['with_id_card']
        gate_logs.append({
            "date": row['date'],
            "total_entries": total,
            "with_uniform": u,
            "with_id_card": i,
            "uniform_percentage": round(u/total*100, 2) if total else 0,
            "id_card_percentage": round(i/total*100, 2) if total else 0
        })
    cur.close()
    db.close()

    return {
        "period_days": days,
        "analytics": gate_logs,
    }
