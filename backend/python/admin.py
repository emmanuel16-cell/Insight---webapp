"""
admin.py  –  InSight Admin + Instructor + Student API Router
Covers:
  POST /api/admin/create-account          – create instructor/admin account with temp password
  GET  /api/admin/users                   – list all users (admin)
  PUT  /api/admin/users/{id}/status       – toggle user active/inactive (admin)
  DELETE /api/admin/users/{id}            – delete user (admin)

  GET  /api/subjects                      – list subjects for current instructor
  POST /api/subjects                      – create new subject
  DELETE /api/subjects/{id}               – delete subject

  GET  /api/students/enrollments          – new enrollment requests for instructor
  POST /api/students/enroll/{subject_id}/{student_id} – accept/reject enrollment
  POST /api/enroll                        – student enroll in a subject via join code

  GET  /api/gate-logs                     – paginated gate logs (admin)
  POST /api/gate-logs                     – record entry/exit (from camera system)

  GET  /api/dashboard/stats              – overview stats (role-aware)

  GET/POST /api/blacklist                – blacklist management
  GET/POST /api/visitors                 – visitor management
  GET/POST /api/uniform-violations       – uniform violation reports
"""

import os
import secrets
import sys
import re
from datetime import date, time as dt_time
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel
from dotenv import load_dotenv
import time
import shutil
import base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python"))
from location_verification import is_within_location, validate_coordinates, haversine_distance
from qr_code_attendance import generate_session_qr
from img_encrypt import encrypt_image
from facial_features import detect_and_extract_face_embedding

from auth import (
    get_db, require_session, require_role, encrypt_password,
    send_temp_password_email, generate_temp_password
)

load_dotenv()

router = APIRouter()


# ─────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────

class CreateAccountRequest(BaseModel):
    role:  str          # "instructor" | "admin"
    email: str

class SubjectCreate(BaseModel):
    code: str
    name: str
    schedule_start: str | None = None  # "HH:MM"
    schedule_end: str | None = None    # "HH:MM"
    time_window_min: int = 30
    latitude: float | None = None
    longitude: float | None = None
    location_radius: int = 100

class EnrollRequest(BaseModel):
    join_code: str

class GateLogCreate(BaseModel):
    user_id:    int
    event_type: str   # "check_in" | "check_out"
    method:     str = "face"

class BlacklistCreate(BaseModel):
    user_id:       int | None = None
    first_name:    str
    last_name:     str
    student_id:    str | None = None
    reason:        str | None = None
    severity:      str = "medium"  # low, medium, high, critical

class VisitorCreate(BaseModel):
    first_name: str
    last_name:  str
    contact:    str | None = None
    purpose:    str | None = None
    face_image_base64: str | None = None

class UniformViolationCreate(BaseModel):
    user_id:      int | None = None
    first_name:   str | None = None
    last_name:    str | None = None
    student_id:   str | None = None
    violation_type: str   # missing_uniform, improper_uniform, no_id_card
    description:  str | None = None
    image_url:    str | None = None

class ScheduleCreate(BaseModel):
    day_of_week: str  # Monday, Tuesday, etc.
    start_time:  str  # HH:MM
    end_time:    str  # HH:MM

class TemporaryPassCreate(BaseModel):
    user_id:    int
    reason:     str | None = None
    expires_at: str   # "YYYY-MM-DD HH:MM:SS"


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def make_join_code() -> str:
    return secrets.token_hex(4).upper()   # e.g. "A3F8B2C1"


def _requires_gate_entry_scan(session_ctx: dict, student_id: int, method: str | None) -> bool:
    """Only require gate entry for student self-scans done via QR/manual QR."""
    return (
        session_ctx.get("role") == "student"
        and student_id == session_ctx.get("user_id")
        and (method or "").lower() in {"qr", "manual_qr"}
    )


def _has_allowed_gate_entry(cur, student_id: int, attendance_date) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM gate_logs
        WHERE (user_id=%s OR student_id=%s)
          AND DATE(timestamp)=%s
          AND event_type='check_in'
        LIMIT 1
        """,
        (student_id, student_id, attendance_date)
    )
    return cur.fetchone() is not None


# ─────────────────────────────────────────────────────────
# ADMIN – Create Account
# ─────────────────────────────────────────────────────────

@router.post("/api/admin/create-account")
async def create_account(body: CreateAccountRequest, request: Request):
    session = require_session(request)
    require_role(session, "admin")

    if body.role not in ("instructor", "admin"):
        raise HTTPException(400, "Role must be 'instructor' or 'admin'")

    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE email=%s", (body.email,))
    if cur.fetchone():
        cur.close(); db.close()
        raise HTTPException(409, "Email already registered")

    temp_pwd = generate_temp_password()
    enc_pwd  = encrypt_password(temp_pwd)

    cur.execute(
        "INSERT INTO users (email, password_hash, role, is_verified, must_change_password) "
        "VALUES (%s,%s,%s,1,1)",
        (body.email, enc_pwd, body.role)
    )
    new_id = cur.lastrowid
    # Create an empty profile row
    cur.execute(
        "INSERT IGNORE INTO user_profiles (user_id) VALUES (%s)", (new_id,)
    )
    db.commit()
    cur.close()
    db.close()

    try:
        await send_temp_password_email(body.email, body.role, temp_pwd)
    except Exception as e:
        # Don't roll back — account exists, just warn
        return {
            "message": f"Account created but email failed: {e}",
            "email": body.email,
        }

    return {"message": "Account created. Temporary password emailed.", "email": body.email}


# ─────────────────────────────────────────────────────────
# ADMIN – Departments
# ─────────────────────────────────────────────────────────

@router.get("/api/admin/departments")
async def get_departments():
    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT code, name FROM departments ORDER BY code")
    rows = cur.fetchall()
    cur.close()
    db.close()

    # Format datetime objects to strings
    formatted_rows = []
    for row in rows:
        row_dict = dict(row)
        if row_dict.get('date'):
            row_dict['date'] = row_dict['date'].isoformat()
        if row_dict.get('check_in'):
            row_dict['check_in'] = row_dict['check_in'].isoformat()
        if row_dict.get('check_out'):
            row_dict['check_out'] = row_dict['check_out'].isoformat()
        formatted_rows.append(row_dict)
    return formatted_rows


@router.post("/api/admin/departments")
async def create_department(body: dict, request: Request):
    session = require_session(request)
    require_role(session, "admin")
    
    code = body.get("code")
    name = body.get("name")
    if not code or not name:
        raise HTTPException(400, "Code and Name are required")

    db  = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO departments (code, name) VALUES (%s, %s)",
            (code, name)
        )
        db.commit()
    except Exception as e:
        cur.close(); db.close()
        raise HTTPException(409, f"Department code already exists: {e}")
    
    cur.close()
    db.close()
    return {"message": "Department created"}

@router.get("/api/admin/pending-students")
async def list_pending_students(request: Request):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    # Use LEFT JOIN to ensure we see the user even if the profile is somehow missing
    cur.execute(
        "SELECT u.id, u.email, u.role, u.is_verified, u.created_at, "
        "       p.first_name, p.last_name, p.section, p.student_id, p.contact "
        "FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id "
        "WHERE u.role='student' AND u.is_verified=1 AND u.is_approved=0 "
        "ORDER BY u.created_at DESC"
    )
    rows = cur.fetchall()
    # Convert date/time objects to strings
    formatted_rows = []
    for row in rows:
        row_dict = dict(row)
        if row_dict.get('created_at'):
            row_dict['created_at'] = str(row_dict['created_at'])
        formatted_rows.append(row_dict)

    cur.close()
    db.close()
    return formatted_rows


@router.post("/api/admin/approve-student/{user_id}")
async def approve_student(user_id: int, request: Request, action: str = "approve"):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor()
    if action == "approve":
        cur.execute("UPDATE users SET is_approved=1 WHERE id=%s", (user_id,))
        msg = "Student approved"
    else:
        # "remove" or "reject"
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        msg = "Student removed"
    
    db.commit()
    cur.close()
    db.close()
    return {"message": msg}


@router.post("/api/admin/approve-all-students")
async def approve_all_students(request: Request):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE users SET is_approved=1 WHERE role='student' AND is_verified=1 AND is_approved=0"
    )
    count = cur.rowcount
    db.commit()
    cur.close()
    db.close()
    return {"message": f"Approved {count} students"}


@router.get("/api/admin/users")
async def list_users(request: Request, role: str | None = None):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor(dictionary=True)

    if role:
        # If filtering by role, usually we want only approved/active ones for the main lists
        # except for the special pending-students endpoint.
        query = (
            "SELECT u.id, u.email, u.role, u.is_verified, u.is_approved, u.created_at, "
            "       p.first_name, p.last_name, p.section, p.contact, p.student_id, p.department "
            "FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id "
            "WHERE u.role=%s "
        )
        if role == 'student':
            query += " AND u.is_approved=1 "
        
        query += " ORDER BY u.created_at DESC"
        cur.execute(query, (role,))
    else:
        cur.execute(
            "SELECT u.id, u.email, u.role, u.is_verified, u.is_approved, u.created_at, "
            "       p.first_name, p.last_name, p.section, p.contact, p.student_id, p.department "
            "FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id "
            "ORDER BY u.created_at DESC"
        )
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    # Format dates/times to strings
    formatted = []
    for r in rows:
        row = dict(r)
        if 'date' in row and row['date']:
            row['date'] = str(row['date'])
        if 'check_in' in row and row['check_in']:
            row['check_in'] = str(row['check_in'])
        if 'check_out' in row and row['check_out']:
            row['check_out'] = str(row['check_out'])
        formatted.append(row)
    return formatted


@router.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    session = require_session(request)
    require_role(session, "admin")

    if user_id == session["user_id"]:
        raise HTTPException(400, "Cannot delete your own account")

    db  = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
    db.commit()
    cur.close()
    db.close()
    return {"message": "User deleted"}


# ─────────────────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────────────────

@router.get("/api/subjects")
async def get_subjects(request: Request):
    session = require_session(request)
    role    = session["role"]
    uid     = session["user_id"]

    db  = get_db()
    cur = db.cursor(dictionary=True)

    if role == "instructor":
        cur.execute(
            "SELECT s.*, "
            "       (SELECT COUNT(*) FROM subject_enrollments e "
            "        WHERE e.enroll_code=s.join_code AND e.status='enrolled') AS student_count "
            "FROM subjects s WHERE s.instructor_id=%s ORDER BY s.created_at DESC",
            (uid,)
        )
    elif role == "student":
        # Fetch student's string ID
        cur.execute("SELECT student_id FROM user_profiles WHERE user_id=%s", (uid,))
        p_row = cur.fetchone()
        stu_code = p_row['student_id'] if p_row else None

        cur.execute(
            "SELECT s.id, s.code, s.name, s.join_code, "
            "       CONCAT(p.first_name,' ',p.last_name) AS instructor_name, "
            "       e.status AS enrollment_status "
            "FROM subjects s "
            "JOIN subject_enrollments e ON e.enroll_code=s.join_code AND e.student_id=%s "
            "LEFT JOIN users u ON u.id=s.instructor_id "
            "LEFT JOIN user_profiles p ON p.user_id=u.id "
            "ORDER BY s.created_at DESC",
            (stu_code,)
        )
    else:
        # Admin sees all
        cur.execute(
            "SELECT s.*, CONCAT(p.first_name,' ',p.last_name) AS instructor_name "
            "FROM subjects s "
            "LEFT JOIN users u ON u.id=s.instructor_id "
            "LEFT JOIN user_profiles p ON p.user_id=u.id "
            "ORDER BY s.created_at DESC"
        )

    rows = cur.fetchall()
    cur.close()
    db.close()

    # Format datetime objects for JSON serialization
    formatted_rows = []
    for r in rows:
        row = dict(r)
        for key in ['date', 'check_in', 'check_out', 'enrolled_at', 'last_check_in']:
            if key in row and row[key]:
                row[key] = str(row[key])
        formatted_rows.append(row)
    return formatted_rows


@router.post("/api/subjects")
async def create_subject(body: SubjectCreate, request: Request):
    session = require_session(request)
    require_role(session, "instructor", "admin")

    db  = get_db()
    cur = db.cursor()

    join_code = make_join_code()
    # Ensure uniqueness
    while True:
        cur.execute("SELECT id FROM subjects WHERE join_code=%s", (join_code,))
        if not cur.fetchone():
            break
        join_code = make_join_code()

    cur.execute(
        "INSERT INTO subjects (code, name, instructor_id, join_code, schedule_start, schedule_end, time_window_min, latitude, longitude, location_radius) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (body.code, body.name, session["user_id"], join_code, body.schedule_start, body.schedule_end, body.time_window_min, body.latitude, body.longitude, body.location_radius)
    )
    new_id = cur.lastrowid
    db.commit()
    cur.close()
    db.close()
    return {"id": new_id, "join_code": join_code, "message": "Subject created"}


@router.delete("/api/subjects/{subject_id}")
async def delete_subject(subject_id: int, request: Request):
    session = require_session(request)
    require_role(session, "instructor", "admin")

    db  = get_db()
    cur = db.cursor()
    # Ensure instructor owns it (unless admin)
    if session["role"] == "instructor":
        cur.execute(
            "SELECT id FROM subjects WHERE id=%s AND instructor_id=%s",
            (subject_id, session["user_id"])
        )
        if not cur.fetchone():
            cur.close(); db.close()
            raise HTTPException(403, "Not your subject")

    cur.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
    db.commit()
    cur.close()
    db.close()
    return {"message": "Subject deleted"}


@router.get("/api/subjects/{subject_id}/schedules")
async def get_subject_schedules(subject_id: int, request: Request):
    session = require_session(request)
    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM schedules WHERE subject_id=%s ORDER BY FIELD(day_of_week, 'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')", (subject_id,))
    rows = cur.fetchall()
    cur.close(); db.close()
    
    # Format times to strings
    formatted = []
    for r in rows:
        row = dict(r)
        if row.get('start_time'): row['start_time'] = str(row['start_time'])
        if row.get('end_time'): row['end_time'] = str(row['end_time'])
        formatted.append(row)
    return formatted


@router.post("/api/subjects/{subject_id}/schedules")
async def add_subject_schedule(subject_id: int, body: ScheduleCreate, request: Request):
    session = require_session(request)
    require_role(session, "instructor", "admin")

    db  = get_db()
    cur = db.cursor()
    
    # Verify ownership if instructor
    if session["role"] == "instructor":
        cur.execute("SELECT id FROM subjects WHERE id=%s AND instructor_id=%s", (subject_id, session["user_id"]))
        if not cur.fetchone():
            cur.close(); db.close()
            raise HTTPException(403, "Not your subject")

    cur.execute(
        "INSERT INTO schedules (subject_id, day_of_week, start_time, end_time) VALUES (%s, %s, %s, %s)",
        (subject_id, body.day_of_week, body.start_time, body.end_time)
    )
    db.commit()
    cur.close(); db.close()
    return {"message": "Schedule added"}


@router.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request):
    session = require_session(request)
    require_role(session, "instructor", "admin")
    
    db = get_db()
    cur = db.cursor()
    
    if session["role"] == "instructor":
        # Check ownership via subject
        cur.execute("""
            SELECT s.id FROM schedules sc
            JOIN subjects s ON sc.subject_id = s.id
            WHERE sc.id = %s AND s.instructor_id = %s
        """, (schedule_id, session["user_id"]))
        if not cur.fetchone():
            cur.close(); db.close()
            raise HTTPException(403, "Not your schedule")
            
    cur.execute("DELETE FROM schedules WHERE id = %s", (schedule_id,))
    db.commit()
    cur.close(); db.close()
    return {"message": "Schedule deleted"}


# ─────────────────────────────────────────────────────────
# STUDENT – Enroll via join code
# ─────────────────────────────────────────────────────────

@router.get("/api/student/subjects")
async def get_student_subjects(request: Request):
    session = require_session(request)
    require_role(session, "student")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    
    # Fetch the student's string student_id from their profile
    cur.execute("SELECT student_id FROM user_profiles WHERE user_id=%s", (session["user_id"],))
    prof = cur.fetchone()
    if not prof or not prof['student_id']:
        cur.close(); db.close()
        return [] # Profile not complete
    
    stu_code = prof['student_id']

    # Only get subjects where status is 'enrolled'
    # Join on subjects.join_code = enrollments.enroll_code
    cur.execute(
        "SELECT s.id, s.code, s.name, s.join_code, s.schedule_start, s.schedule_end, "
        "       CONCAT(p.first_name,' ',p.last_name) AS instructor_name, "
        "       'enrolled' AS status "
        "FROM subjects s "
        "JOIN subject_enrollments e ON e.enroll_code=s.join_code "
        "LEFT JOIN user_profiles p ON p.user_id=s.instructor_id "
        "WHERE e.student_id=%s AND e.status='enrolled'",
        (stu_code,)
    )
    rows = cur.fetchall()
    
    # Format times
    for r in rows:
        if r.get('schedule_start'): r['schedule_start'] = str(r['schedule_start'])
        if r.get('schedule_end'): r['schedule_end'] = str(r['schedule_end'])

    cur.close()
    db.close()
    return rows


@router.get("/api/student/enrollments")
async def get_student_enrollments(request: Request):
    """Get all enrollment applications for the current student (subject_enrollments table)."""
    session = require_session(request)
    require_role(session, "student")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    
    # Fetch the student's string student_id from their profile
    cur.execute("SELECT student_id FROM user_profiles WHERE user_id=%s", (session["user_id"],))
    prof = cur.fetchone()
    if not prof or not prof['student_id']:
        cur.close(); db.close()
        return []
    
    stu_code = prof['student_id']

    # Get all enrollments for this student with subject details
    cur.execute(
        "SELECT e.enroll_code, e.student_id, e.section, e.fullname, e.status, e.enrolled_at, "
        "       s.code, s.name, CONCAT(p.first_name,' ',p.last_name) AS instructor_name "
        "FROM subject_enrollments e "
        "JOIN subjects s ON s.join_code = e.enroll_code "
        "LEFT JOIN user_profiles p ON p.user_id = s.instructor_id "
        "WHERE e.student_id=%s "
        "ORDER BY e.enrolled_at DESC",
        (stu_code,)
    )
    rows = cur.fetchall()

    cur.close()
    db.close()
    return rows


@router.post("/api/student/subjects/enroll")
async def enroll_student(body: EnrollRequest, request: Request):
    session = require_session(request)
    require_role(session, "student")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    
    # Verify subject exists
    cur.execute("SELECT join_code FROM subjects WHERE join_code=%s", (body.join_code,))
    row = cur.fetchone()
    if not row:
        cur.close(); db.close()
        raise HTTPException(404, "Invalid join code")
    
    enroll_code = row['join_code']

    # Get student's string student_id, section, and full name
    cur.execute("SELECT student_id, section, first_name, last_name FROM user_profiles WHERE user_id=%s", (session["user_id"],))
    prof = cur.fetchone()
    if not prof or not prof['student_id']:
        cur.close(); db.close()
        raise HTTPException(400, "Please complete your profile (Student ID) before enrolling")
    
    stu_code = prof['student_id']
    section = prof.get('section', '')
    fullname = f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip()

    try:
        cur.execute(
            "INSERT INTO subject_enrollments (enroll_code, student_id, section, fullname, status) "
            "VALUES (%s,%s,%s,%s,'pending')",
            (enroll_code, stu_code, section, fullname)
        )
        db.commit()
    except Exception:
        cur.close(); db.close()
        raise HTTPException(400, "Already applied or enrolled in this subject")

    cur.close()
    db.close()
    return {"message": "Application sent"}


# ─────────────────────────────────────────────────────────
# INSTRUCTOR – Manage student enrollments
# ─────────────────────────────────────────────────────────

@router.get("/api/subjects/{subject_id}/students")
async def get_students(subject_id: int, request: Request, status: str = "enrolled"):
    session = require_session(request)
    require_role(session, "instructor", "admin")

    db  = get_db()
    cur = db.cursor(dictionary=True)

    # Get the join_code for this subject
    cur.execute("SELECT join_code FROM subjects WHERE id=%s", (subject_id,))
    s_row = cur.fetchone()
    if not s_row:
        cur.close(); db.close()
        raise HTTPException(404, "Subject not found")
    
    enroll_code = s_row['join_code']

    # If status is pending, we return all enrollment details as requested
    if status == "pending":
        cur.execute(
            "SELECT e.id, e.enroll_code, e.status, e.enrolled_at, "
            "       p.user_id, p.first_name, p.last_name, p.section, p.student_id "
            "FROM subject_enrollments e "
            "JOIN user_profiles p ON p.student_id=e.student_id "
            "WHERE e.enroll_code=%s AND e.status='pending' "
            "ORDER BY e.enrolled_at DESC",
            (enroll_code,)
        )
    else:
        # For enrolled students, show their profile and last gate check-in
        cur.execute(
            "SELECT e.id, e.enroll_code, e.status, e.enrolled_at, "
            "       p.user_id, p.first_name, p.last_name, p.section, p.student_id, "
            "       (SELECT MAX(timestamp) FROM gate_logs WHERE user_id = p.user_id AND event_type='check_in') as last_check_in "
            "FROM subject_enrollments e "
            "JOIN user_profiles p ON p.student_id=e.student_id "
            "WHERE e.enroll_code=%s AND e.status='enrolled' "
            "ORDER BY p.last_name",
            (enroll_code,)
        )
    
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    # Format datetime objects for JSON serialization
    formatted_rows = []
    for r in rows:
        row = dict(r)
        if 'date' in row and row['date']:
            row['date'] = str(row['date'])
        if 'check_in' in row and row['check_in']:
            row['check_in'] = str(row['check_in'])
        if 'check_out' in row and row['check_out']:
            row['check_out'] = str(row['check_out'])
        formatted_rows.append(row)
    return formatted_rows


@router.post("/api/subjects/{subject_id}/students/{student_id}")
async def accept_student(
    subject_id: int, student_id: int,
    request: Request, action: str = "accept"
):
    session = require_session(request)
    require_role(session, "instructor", "admin")

    db  = get_db()
    cur = db.cursor()

    # Get subject join_code
    cur.execute("SELECT join_code FROM subjects WHERE id=%s", (subject_id,))
    s_row = cur.fetchone()
    if not s_row:
        cur.close(); db.close()
        raise HTTPException(404, "Subject not found")
    enroll_code = s_row[0]

    # Get student string ID
    cur.execute("SELECT student_id FROM user_profiles WHERE user_id=%s", (student_id,))
    p_row = cur.fetchone()
    if not p_row:
        cur.close(); db.close()
        raise HTTPException(404, "Student profile not found")
    stu_code = p_row[0]

    msg = None
    if action == "accept":
        cur.execute(
            "UPDATE subject_enrollments SET status='enrolled' "
            "WHERE enroll_code=%s AND student_id=%s",
            (enroll_code, stu_code)
        )
        msg = "accepted"
    elif action == "revert":
        # Move an enrolled student back to pending (application list)
        cur.execute(
            "UPDATE subject_enrollments SET status='pending' "
            "WHERE enroll_code=%s AND student_id=%s",
            (enroll_code, stu_code)
        )
        msg = "reverted"
    else:
        # Default: remove the enrollment/application permanently
        cur.execute(
            "DELETE FROM subject_enrollments WHERE enroll_code=%s AND student_id=%s",
            (enroll_code, stu_code)
        )
        msg = "removed"

    db.commit()
    cur.close()
    db.close()
    return {"message": f"Student {msg}"}


@router.delete("/api/subjects/{subject_id}/students/{student_id}")
async def remove_student(subject_id: int, student_id: int, request: Request):
    return await accept_student(subject_id, student_id, request, action="reject")


@router.get("/api/subjects/{subject_id}/analytics")
async def get_subject_analytics(subject_id: int, request: Request, filter: str = "all"):
    session = require_session(request)
    db  = get_db()
    cur = db.cursor(dictionary=True)

    # Date filter logic
    date_clause = ""
    gate_date_clause = ""
    params = [subject_id]
    
    if filter == "today":
        date_clause = " AND date = CURDATE()"
        gate_date_clause = " AND DATE(timestamp) = CURDATE()"
    elif filter == "weekly":
        date_clause = " AND date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
        gate_date_clause = " AND DATE(timestamp) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
    elif filter == "monthly":
        date_clause = " AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
        gate_date_clause = " AND DATE(timestamp) >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"

    # Get subject info
    cur.execute("SELECT join_code FROM subjects WHERE id=%s", (subject_id,))
    s_row = cur.fetchone()
    if not s_row:
        cur.close(); db.close()
        raise HTTPException(404, "Subject not found")
    
    enroll_code = s_row['join_code']

    # 1. Distribution
    # We use gate_logs to determine presence, matched against schedules for that day.
    
    # Get total enrolled students
    cur.execute("SELECT COUNT(*) as count FROM subject_enrollments WHERE enroll_code=%s AND status='enrolled'", (enroll_code,))
    enrolled_count = cur.fetchone()['count'] or 0

    # Get all schedules for this subject
    cur.execute("SELECT day_of_week, start_time FROM schedules WHERE subject_id = %s", (subject_id,))
    schedules = cur.fetchall()
    
    if not schedules:
        # Fallback to old behavior if no schedules are defined yet
        cur.execute("SELECT schedule_start FROM subjects WHERE id=%s", (subject_id,))
        sched_start = cur.fetchone().get('schedule_start')
        
        cur.execute(f"""
            SELECT 
                COUNT(DISTINCT gl.user_id, DATE(gl.timestamp)) as present_count,
                SUM(CASE WHEN TIME(gl.min_ts) > %s THEN 1 ELSE 0 END) as late_count
            FROM (
                SELECT user_id, DATE(timestamp) as date, MIN(timestamp) as min_ts
                FROM gate_logs
                WHERE event_type = 'check_in' {gate_date_clause}
                GROUP BY user_id, DATE(timestamp)
            ) gl
            JOIN user_profiles p ON p.user_id = gl.user_id
            JOIN subject_enrollments e ON e.student_id = p.student_id
            WHERE e.enroll_code = %s AND e.status = 'enrolled'
        """, (sched_start, enroll_code))
        
        counts = cur.fetchone()
        present = counts['present_count'] or 0
        late = counts['late_count'] or 0
        
        days_in_period = 1
        if filter == "weekly": days_in_period = 7
        elif filter == "monthly": days_in_period = 30
        
        total_opportunities = enrolled_count * days_in_period
    else:
        # New behavior: match logs with schedules by day_of_week
        # We join each schedule with the 'best' check-in for that schedule.
        # For simplicity, we'll consider the first check-in of the day that happened before or near the start time.
        cur.execute(f"""
            SELECT 
                COUNT(*) as present_count,
                SUM(CASE WHEN TIME(gl.first_in) > s.start_time THEN 1 ELSE 0 END) as late_count
            FROM schedules s
            JOIN subject_enrollments e ON s.subject_id = (SELECT id FROM subjects WHERE join_code = e.enroll_code LIMIT 1)
            JOIN user_profiles p ON p.student_id = e.student_id
            LEFT JOIN (
                SELECT user_id, DATE(timestamp) as log_date, MIN(timestamp) as first_in, DAYNAME(timestamp) as log_day
                FROM gate_logs
                WHERE event_type = 'check_in' {gate_date_clause}
                GROUP BY user_id, DATE(timestamp)
            ) gl ON gl.user_id = p.user_id AND gl.log_day = s.day_of_week
            WHERE s.subject_id = %s AND e.enroll_code = %s AND e.status = 'enrolled' AND gl.first_in IS NOT NULL
        """, (subject_id, enroll_code))
        
        counts = cur.fetchone()
        present = counts['present_count'] or 0
        late = counts['late_count'] or 0
        
        # Calculate total opportunities by counting all schedule instances in the period
        total_opportunities = 0
        
        # Get date range
        num_days = 1
        if filter == "weekly": num_days = 7
        elif filter == "monthly": num_days = 30
        
        import datetime
        today = datetime.date.today()
        for i in range(num_days):
            d = today - datetime.timedelta(days=i)
            day_name = d.strftime('%A')
            # Count how many schedules apply to this day
            schedules_this_day = [s for s in schedules if s['day_of_week'] == day_name]
            total_opportunities += len(schedules_this_day) * enrolled_count
    
    absent = max(0, total_opportunities - present)
    total = total_opportunities or 1
    
    dist = {
        "present": round(100 * (present - late) / total),
        "late": round(100 * late / total),
        "absent": round(100 * absent / total)
    }

    # 2. High/Low Attendance
    # Using gate_logs to calculate attendance percentage per student
    # Note: total_opportunities_per_student is total_opportunities / enrolled_count
    opps_per_student = (total_opportunities / enrolled_count) if enrolled_count > 0 else 1
    
    # Improved: Match each student's logs with schedules to get precise attendance count
    cur.execute(f"""
        SELECT 
            CONCAT(p.first_name,' ',p.last_name) AS name, 
            p.section,
            ROUND(100 * (
                SELECT COUNT(*)
                FROM schedules s2
                JOIN (
                    SELECT user_id, DATE(timestamp) as log_date, MIN(timestamp) as first_in, DAYNAME(timestamp) as log_day
                    FROM gate_logs
                    WHERE event_type = 'check_in' {gate_date_clause}
                    GROUP BY user_id, DATE(timestamp)
                ) gl2 ON gl2.user_id = p.user_id AND gl2.log_day = s2.day_of_week
                WHERE s2.subject_id = %s AND gl2.first_in IS NOT NULL
            ) / GREATEST(%s, 1), 1) AS attendance_pct
        FROM subject_enrollments e
        JOIN user_profiles p ON p.student_id = e.student_id
        WHERE e.enroll_code = %s AND e.status = 'enrolled'
        GROUP BY p.user_id
        ORDER BY attendance_pct DESC
    """, (subject_id, opps_per_student, enroll_code))
    
    all_students = cur.fetchall()
    cur.close()
    db.close()

    # Filter out students with 0 attendance if no logs in period? 
    # Actually, keep them but they'll be in 'low_attendance'
    valid_students = [dict(s) for s in all_students]
    
    return {
        "distribution": dist,
        "high_attendance": valid_students[:5],
        "low_attendance":  valid_students[::-1][:5]
    }


# ─────────────────────────────────────────────────────────
# CLASS SESSIONS
# ─────────────────────────────────────────────────────────

@router.post("/api/subjects/{subject_id}/students/accept-all")
async def accept_all_students(subject_id: int, request: Request):
    session = require_session(request)
    require_role(session, "instructor", "admin")

    db  = get_db()
    cur = db.cursor()
    
    # Get subject join_code
    cur.execute("SELECT join_code FROM subjects WHERE id=%s", (subject_id,))
    s_row = cur.fetchone()
    if not s_row:
        cur.close(); db.close()
        raise HTTPException(404, "Subject not found")
    enroll_code = s_row[0]

    cur.execute(
        "UPDATE subject_enrollments SET status='enrolled' "
        "WHERE enroll_code=%s AND status='pending'",
        (enroll_code,)
    )
    db.commit()
    cur.close()
    db.close()
    return {"message": "All students accepted"}


# ─────────────────────────────────────────────────────────
# BLACKLIST
# ─────────────────────────────────────────────────────────

@router.get("/api/blacklist")
async def get_blacklist(request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT b.*, 
               u.email as user_email,
               p.student_id as original_student_id,
               CONCAT(p.first_name, ' ', p.last_name) as user_fullname
        FROM blacklist b
        LEFT JOIN users u ON b.user_id = u.id
        LEFT JOIN user_profiles p ON u.id = p.user_id
        ORDER BY b.created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    for r in rows:
        if r['created_at']: r['created_at'] = str(r['created_at'])
        if r['resolved_at']: r['resolved_at'] = str(r['resolved_at'])
    return rows

@router.post("/api/blacklist")
async def add_to_blacklist(body: BlacklistCreate, request: Request):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO blacklist (user_id, first_name, last_name, student_id, reason, severity, reported_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (body.user_id, body.first_name, body.last_name, body.student_id, body.reason, body.severity, session["user_id"]))
    db.commit()
    cur.close()
    db.close()
    return {"message": "Person added to blacklist"}

@router.delete("/api/blacklist/{id}")
async def remove_from_blacklist(id: int, request: Request):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM blacklist WHERE id=%s", (id,))
    db.commit()
    cur.close()
    db.close()
    return {"message": "Person removed from blacklist"}


# ─────────────────────────────────────────────────────────
# UNIFORM VIOLATIONS
# ─────────────────────────────────────────────────────────

@router.get("/api/uniform-violations")
async def get_violations(request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT v.*, 
               p.student_id as original_student_id,
               CONCAT(p.first_name, ' ', p.last_name) as user_fullname
        FROM uniform_violations v
        LEFT JOIN user_profiles p ON v.user_id = p.user_id
        ORDER BY v.created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    for r in rows:
        if r['created_at']: r['created_at'] = str(r['created_at'])
        if r['resolved_at']: r['resolved_at'] = str(r['resolved_at'])
    return rows

@router.post("/api/uniform-violations")
async def report_violation(body: UniformViolationCreate, request: Request):
    session = require_session(request)
    # Could be reported by admin or automated system
    
    db  = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO uniform_violations (user_id, student_id, first_name, last_name, violation_type, description, image_url, reported_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (body.user_id, body.student_id, body.first_name, body.last_name, body.violation_type, body.description, body.image_url, session["user_id"]))
    db.commit()
    cur.close()
    db.close()
    return {"message": "Violation reported"}


# ─────────────────────────────────────────────────────────
# GATE LOGS
# ─────────────────────────────────────────────────────────

@router.get("/api/gate-logs")
async def get_gate_logs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    user_id: int | None = None
):
    session = require_session(request)

    db  = get_db()
    cur = db.cursor(dictionary=True)

    if session["role"] == "student":
        # Students see only their own logs aggregated by date
        cur.execute(
            "SELECT DATE(timestamp) as `date`, "
            "MIN(CASE WHEN event_type = 'check_in' THEN timestamp END) as check_in, "
            "MAX(CASE WHEN event_type = 'check_out' THEN timestamp END) as check_out, "
            "MAX(has_uniform) as has_uniform, "
            "MAX(has_id_card) as has_id_card, "
            "p.student_id AS student_id, CONCAT(p.first_name,' ',p.last_name) AS name "
            "FROM gate_logs gl "
            "LEFT JOIN user_profiles p ON p.user_id=gl.user_id "
            "WHERE gl.user_id=%s AND gl.event_type IN ('check_in', 'check_out') "
            "GROUP BY gl.user_id, DATE(gl.timestamp) "
            "ORDER BY `date` DESC LIMIT %s OFFSET %s",
            (session["user_id"], limit, offset)
        )
    elif user_id:
        cur.execute(
            "SELECT DATE(timestamp) as `date`, "
            "MIN(CASE WHEN event_type = 'check_in' THEN timestamp END) as check_in, "
            "MAX(CASE WHEN event_type = 'check_out' THEN timestamp END) as check_out, "
            "MAX(has_uniform) as has_uniform, "
            "MAX(has_id_card) as has_id_card, "
            "p.student_id AS student_id, CONCAT(p.first_name,' ',p.last_name) AS name "
            "FROM gate_logs gl "
            "LEFT JOIN user_profiles p ON p.user_id=gl.user_id "
            "WHERE gl.user_id=%s AND gl.event_type IN ('check_in', 'check_out') "
            "GROUP BY gl.user_id, DATE(gl.timestamp) "
            "ORDER BY `date` DESC LIMIT %s OFFSET %s",
            (user_id, limit, offset)
        )
    else:
        cur.execute(
            "SELECT DATE(timestamp) as `date`, "
            "MIN(CASE WHEN event_type = 'check_in' THEN timestamp END) as check_in, "
            "MAX(CASE WHEN event_type = 'check_out' THEN timestamp END) as check_out, "
            "MAX(has_uniform) as has_uniform, "
            "MAX(has_id_card) as has_id_card, "
            "u.email, p.student_id AS student_id, CONCAT(p.first_name,' ',p.last_name) AS name "
            "FROM gate_logs gl "
            "JOIN users u ON u.id=gl.user_id "
            "LEFT JOIN user_profiles p ON p.user_id=gl.user_id "
            "WHERE gl.event_type IN ('check_in', 'check_out') "
            "GROUP BY gl.user_id, DATE(gl.timestamp) "
            "ORDER BY `date` DESC LIMIT %s OFFSET %s",
            (limit, offset)
        )

    rows = cur.fetchall()
    cur.close()
    db.close()
    
    # Format dates/times to strings for Flutter
    formatted = []
    for r in rows:
        row = dict(r)
        if 'date' in row and row['date']:
            row['date'] = str(row['date'])
        if 'check_in' in row and row['check_in']:
            row['check_in'] = str(row['check_in'])
        if 'check_out' in row and row['check_out']:
            row['check_out'] = str(row['check_out'])
        formatted.append(row)
    return formatted


@router.post("/api/gate-logs")
async def create_gate_log(body: GateLogCreate, request: Request):
    """Called by the camera/detection system when a person is identified."""
    session = require_session(request)

    db  = get_db()
    cur = db.cursor()
    try:
        # insert raw event
        cur.execute(
            "INSERT INTO gate_logs (user_id, student_id, event_type, method, timestamp) "
            "VALUES (%s,%s,%s,%s,NOW())",
            (body.user_id, body.user_id, body.event_type, body.method)
        )
        db.commit()

        return {"message": "Gate log recorded"}
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass



# ─────────────────────────────────────────────────────────
# VISITORS
# ─────────────────────────────────────────────────────────

@router.get("/api/visitors")
async def list_visitors(request: Request, search: str | None = None):
    session = require_session(request)
    require_role(session, "admin", "instructor") # security usually has admin/special role

    db  = get_db()
    cur = db.cursor(dictionary=True)
    
    query = "SELECT * FROM visitors"
    params = []
    if search:
        query += " WHERE first_name LIKE %s OR last_name LIKE %s OR contact LIKE %s OR purpose LIKE %s"
        search_val = f"%{search}%"
        params = [search_val, search_val, search_val, search_val]
    
    query += " ORDER BY time_in DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    db.close()

    # Format datetimes
    for r in rows:
        if r.get('time_in'): r['time_in'] = r['time_in'].isoformat()
        if r.get('time_out'): r['time_out'] = r['time_out'].isoformat()
    return rows

@router.post("/api/visitors")
async def add_visitor(body: VisitorCreate, request: Request):
    # Kiosk allows visitors to register themselves, so we only check session if it's from Admin dashboard
    # However, to maintain security, we can allow registration if the user is an admin OR if the request is for self-registration
    token = request.cookies.get("insight_session")
    session = None
    if token:
        from auth import get_session
        session = get_session(token)

    db  = get_db()
    cur = db.cursor()
    
    face_image_url = None
    face_encoding = None
    
    if body.face_image_base64:
        try:
            # Decode base64 image
            header, encoded = body.face_image_base64.split(",", 1) if "," in body.face_image_base64 else (None, body.face_image_base64)
            image_data = base64.b64decode(encoded)
            
            # Extract embedding and crop
            embedding, cropped_bytes = detect_and_extract_face_embedding(image_data)
            
            if embedding is not None:
                face_encoding = embedding.tobytes()
                
                # Encrypt and save image
                encrypted_img = encrypt_image(cropped_bytes)
                
                # Ensure directory exists
                log_dir = os.path.join("public", "logs", "visitors")
                os.makedirs(log_dir, exist_ok=True)
                
                # Filename: visitor_TIMESTAMP.jpg.enc
                filename = f"visitor_{int(time.time())}.jpg.enc"
                filepath = os.path.join(log_dir, filename)
                
                with open(filepath, "wb") as f:
                    f.write(encrypted_img)
                
                face_image_url = f"/public/logs/visitors/{filename}"
        except Exception as e:
            print(f"Error processing visitor face: {e}")

    recorded_by = session["user_id"] if session else None

    cur.execute(
        "INSERT INTO visitors (first_name, last_name, contact, purpose, recorded_by, face_image_url, face_encoding) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (body.first_name, body.last_name, body.contact, body.purpose, recorded_by, face_image_url, face_encoding)
    )
    db.commit()
    new_id = cur.lastrowid
    cur.close()
    db.close()
    return {"id": new_id, "message": "Visitor recorded successfully"}

@router.put("/api/visitors/{visitor_id}/time-out")
async def visitor_time_out(visitor_id: int, request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE visitors SET time_out=CURRENT_TIMESTAMP WHERE id=%s AND time_out IS NULL",
        (visitor_id,)
    )
    db.commit()
    affected = cur.rowcount
    cur.close()
    db.close()
    
    if affected == 0:
        raise HTTPException(400, "Visitor already timed out or not found")
    return {"message": "Visitor timed out"}


# ─────────────────────────────────────────────────────────
# BLACKLIST
# ─────────────────────────────────────────────────────────

@router.get("/api/blacklist")
async def get_blacklist(request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT b.*, u.email as user_email, p.first_name as reporter_fn, p.last_name as reporter_ln "
        "FROM blacklist b "
        "LEFT JOIN users u ON u.id = b.user_id "
        "LEFT JOIN user_profiles p ON p.user_id = b.reported_by "
        "ORDER BY b.created_at DESC"
    )
    rows = cur.fetchall()
    cur.close()
    db.close()

    for r in rows:
        if r.get('created_at'): r['created_at'] = r['created_at'].isoformat()
        if r.get('resolved_at'): r['resolved_at'] = r['resolved_at'].isoformat()
    return rows

@router.post("/api/blacklist")
async def add_to_blacklist(body: BlacklistCreate, request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO blacklist (user_id, first_name, last_name, student_id, reason, severity, reported_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (body.user_id, body.first_name, body.last_name, body.student_id, body.reason, body.severity, session["user_id"])
    )
    db.commit()
    new_id = cur.lastrowid
    cur.close()
    db.close()
    return {"id": new_id, "message": "Added to blacklist"}

@router.put("/api/blacklist/{blacklist_id}/resolve")
async def resolve_blacklist(blacklist_id: int, request: Request):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE blacklist SET status='resolved', resolved_at=CURRENT_TIMESTAMP WHERE id=%s",
        (blacklist_id,)
    )
    db.commit()
    cur.close()
    db.close()
    return {"message": "Blacklist entry resolved"}


# ─────────────────────────────────────────────────────────
# UNIFORM VIOLATIONS
# ─────────────────────────────────────────────────────────

@router.get("/api/uniform-violations")
async def get_violations(request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT v.*, p.first_name as reporter_fn, p.last_name as reporter_ln "
        "FROM uniform_violations v "
        "LEFT JOIN user_profiles p ON p.user_id = v.reported_by "
        "ORDER BY v.created_at DESC"
    )
    rows = cur.fetchall()
    cur.close()
    db.close()

    for r in rows:
        if r.get('created_at'): r['created_at'] = r['created_at'].isoformat()
        if r.get('resolved_at'): r['resolved_at'] = r['resolved_at'].isoformat()
    return rows

@router.post("/api/uniform-violations")
async def report_violation(body: UniformViolationCreate, request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO uniform_violations (user_id, student_id, first_name, last_name, violation_type, description, image_url, reported_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (body.user_id, body.student_id, body.first_name, body.last_name, body.violation_type, body.description, body.image_url, session["user_id"])
    )
    db.commit()
    new_id = cur.lastrowid
    cur.close()
    db.close()
    return {"id": new_id, "message": "Violation reported"}

# ─────────────────────────────────────────────────────────
# TEMPORARY PASSES
# ─────────────────────────────────────────────────────────

@router.get("/api/temporary-passes")
async def get_temporary_passes(request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT t.*, 
               p.student_id as original_student_id,
               CONCAT(p.first_name, ' ', p.last_name) as user_fullname,
               CONCAT(ip.first_name, ' ', ip.last_name) as issuer_name
        FROM temporary_passes t
        LEFT JOIN user_profiles p ON t.user_id = p.user_id
        LEFT JOIN user_profiles ip ON t.issued_by = ip.user_id
        ORDER BY t.created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    for r in rows:
        if r['created_at']: r['created_at'] = str(r['created_at'])
        if r['expires_at']: r['expires_at'] = str(r['expires_at'])
    return rows

@router.post("/api/temporary-passes")
async def issue_temporary_pass(body: TemporaryPassCreate, request: Request):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO temporary_passes (user_id, reason, expires_at, issued_by)
        VALUES (%s, %s, %s, %s)
    """, (body.user_id, body.reason, body.expires_at, session["user_id"]))
    db.commit()
    cur.close()
    db.close()
    return {"message": "Temporary pass issued"}

@router.delete("/api/temporary-passes/{id}")
async def revoke_temporary_pass(id: int, request: Request):
    session = require_session(request)
    require_role(session, "admin")

    db  = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM temporary_passes WHERE id=%s", (id,))
    db.commit()
    cur.close()
    db.close()
    return {"message": "Temporary pass revoked"}

@router.put("/api/uniform-violations/{violation_id}/status")
async def update_violation_status(violation_id: int, status: str, request: Request):
    session = require_session(request)
    require_role(session, "admin", "instructor")

    if status not in ('reviewed', 'resolved'):
        raise HTTPException(400, "Invalid status")

    db  = get_db()
    cur = db.cursor()
    if status == 'resolved':
        cur.execute(
            "UPDATE uniform_violations SET status=%s, resolved_at=CURRENT_TIMESTAMP WHERE id=%s",
            (status, violation_id)
        )
    else:
        cur.execute(
            "UPDATE uniform_violations SET status=%s WHERE id=%s",
            (status, violation_id)
        )
    db.commit()
    cur.close()
    db.close()
    return {"message": f"Violation status updated to {status}"}


# ─────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────

@router.get("/api/dashboard/stats")
async def dashboard_stats(request: Request):
    session = require_session(request)
    role    = session["role"]
    uid     = session["user_id"]

    db  = get_db()
    cur = db.cursor(dictionary=True)

    if role == "admin":
        # Total students, today's gate check-ins
        cur.execute("SELECT COUNT(*) AS total_students FROM users WHERE role='student' AND is_approved=1")
        total = cur.fetchone()["total_students"]

        cur.execute("""
            SELECT 
                COUNT(DISTINCT user_id) as present
            FROM gate_logs 
            WHERE event_type='check_in' AND DATE(timestamp) = CURDATE()
        """)
        today_stats = cur.fetchone()
        
        cur.close(); db.close()
        return {
            "total_students": total,
            "today_present":  today_stats["present"] or 0,
            "today_late":     0, # Placeholder
            "today_absent":   max(0, total - (today_stats["present"] or 0)),
        }

    elif role == "instructor":
        cur.execute(
            "SELECT COUNT(*) AS subject_count FROM subjects WHERE instructor_id=%s", (uid,)
        )
        subjects = cur.fetchone()["subject_count"]

        cur.execute(
            "SELECT COUNT(DISTINCT p.user_id) AS student_count "
            "FROM subject_enrollments e "
            "JOIN subjects s ON s.join_code = e.enroll_code "
            "JOIN user_profiles p ON p.student_id = e.student_id "
            "WHERE s.instructor_id=%s AND e.status='enrolled'",
            (uid,)
        )
        students = cur.fetchone()["student_count"]

        # For gate-based instructor stats: count how many of THEIR enrolled students checked in today
        cur.execute("""
            SELECT COUNT(DISTINCT gl.user_id) as present_today
            FROM gate_logs gl
            JOIN user_profiles p ON p.user_id = gl.user_id
            JOIN subject_enrollments e ON e.student_id = p.student_id
            JOIN subjects s ON s.join_code = e.enroll_code
            WHERE s.instructor_id = %s 
              AND e.status = 'enrolled'
              AND gl.event_type = 'check_in'
              AND DATE(gl.timestamp) = CURDATE()
        """, (uid,))
        present_today = cur.fetchone()["present_today"]

        cur.close(); db.close()
        return {
            "subject_count":  subjects,
            "student_count":  students,
            "present_today":  present_today or 0,
            "avg_attendance": 0.0 # Placeholder or calculate over time
        }

    else:  # student
        # Student's own gate attendance
        cur.execute(
            "SELECT COUNT(DISTINCT DATE(timestamp)) as days_present "
            "FROM gate_logs WHERE user_id=%s AND event_type='check_in'",
            (uid,)
        )
        present = cur.fetchone()["days_present"]

        # Get total subjects enrolled
        cur.execute(
            "SELECT COUNT(*) as enrolled_count FROM subject_enrollments e "
            "JOIN user_profiles p ON p.student_id = e.student_id "
            "WHERE p.user_id = %s AND e.status='enrolled'", (uid,)
        )
        enrolled = cur.fetchone()["enrolled_count"]

        cur.close(); db.close()
        return {
            "days_present":   present or 0,
            "subjects_count": enrolled or 0,
            "last_check_in":  "N/A" # Could fetch latest timestamp
        }


# ─────────────────────────────────────────────────────────
# ADMIN-COMPAT ALIASES (frontend expects /api/admin/*)
# ─────────────────────────────────────────────────────────

@router.get("/api/admin/visitors")
async def admin_list_visitors(request: Request, search: str | None = None):
    return await list_visitors(request, search)


@router.post("/api/admin/visitors")
async def admin_add_visitor(body: VisitorCreate, request: Request):
    return await add_visitor(body, request)


@router.put("/api/admin/visitors/{visitor_id}/time-out")
async def admin_visitor_time_out(visitor_id: int, request: Request):
    return await visitor_time_out(visitor_id, request)


@router.get("/api/admin/blacklist")
async def admin_get_blacklist(request: Request):
    return await get_blacklist(request)


@router.post("/api/admin/blacklist")
async def admin_add_to_blacklist(body: BlacklistCreate, request: Request):
    return await add_to_blacklist(body, request)


@router.put("/api/admin/blacklist/{blacklist_id}/resolve")
async def admin_resolve_blacklist(blacklist_id: int, request: Request):
    return await resolve_blacklist(blacklist_id, request)


@router.get("/api/admin/violations")
async def admin_get_violations(request: Request):
    return await get_violations(request)
