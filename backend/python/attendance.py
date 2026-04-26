"""
attendance.py  –  Attendance Tracking (Refactored)
Provides student attendance history using the gate_logs system.
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request
from auth import get_db, require_session

router = APIRouter(prefix="/api/attendance")

def init_attendance_db():
    """
    Deprecated: The system now uses gate_logs and subjects.
    Legacy system is no longer used.
    """
    pass

def get_student_attendance(user_id: int, subject_id: int | None = None, days_back: int = 30) -> list:
    """
    Get attendance records for a student using gate_logs.
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    start_date = (datetime.now() - timedelta(days=days_back)).date()

    try:
        # Join gate_logs with schedules to determine which subject was attended
        # based on the timestamp of the check_in.
        # We look for the first check-in of the day and match it against all schedules for that day.
        query = """
            SELECT 
                gl.first_in as scanned_at,
                gl.log_date as attendance_date,
                CASE WHEN TIME(gl.first_in) <= sc.start_time THEN 'present' ELSE 'late' END as status,
                'gate' as recognition_method,
                s.code as course_code,
                s.name as course_name,
                s.id as subject_id
            FROM (
                SELECT user_id, DATE(timestamp) as log_date, MIN(timestamp) as first_in, DAYNAME(timestamp) as log_day
                FROM gate_logs
                WHERE user_id = %s AND event_type = 'check_in' AND DATE(timestamp) >= %s
                GROUP BY DATE(timestamp)
            ) gl
            JOIN user_profiles p ON p.user_id = gl.user_id
            JOIN subject_enrollments e ON e.student_id = p.student_id
            JOIN subjects s ON e.enroll_code = s.join_code
            JOIN schedules sc ON sc.subject_id = s.id AND sc.day_of_week = gl.log_day
            WHERE 1=1
        """
        params = [user_id, start_date]

        if subject_id:
            query += " AND s.id = %s"
            params.append(subject_id)

        query += " ORDER BY gl.first_in DESC"
        
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        cur.close()
        db.close()

        out = []
        for r in rows:
            scanned_at = r['scanned_at']
            out.append({
                'student_id': user_id,
                'course_id': r['subject_id'],
                'course_code': r['course_code'],
                'course_name': r['course_name'],
                'attendance_date': str(r['attendance_date']),
                'time_in': scanned_at.strftime('%H:%M:%S') if scanned_at else None,
                'status': r['status'],
                'recognition_method': r['recognition_method'],
                'confidence': None,
            })
        return out

    except Exception as e:
        print(f"[attendance.py] get_student_attendance error: {e}")
        if cur: cur.close()
        if db: db.close()
        return []

@router.get("/my-attendance")
async def get_my_attendance(course_id: int | None = None, request: Request = None):
    """Student views their attendance records."""
    session = require_session(request)
    if session.get("role") != "student":
        raise HTTPException(403, "Only students can access their attendance")
    
    user_id = session["user_id"]
    records = get_student_attendance(user_id, course_id)
    return {
        "user_id": user_id,
        "records": records,
    }
