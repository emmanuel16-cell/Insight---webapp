"""
auth.py  –  InSight Authentication Router
Handles: register, OTP verify, account info, login, logout,
         forgot-password, reset-password, resend OTP,
         and the admin "create-account" temp-password flow.
"""

import os
import random
import string
import hashlib
import hmac
import time
import secrets
import mysql.connector

from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python"))
from text_encrypt import encrypt_user_data, decrypt_user_data  # noqa
import asyncio

load_dotenv()

router = APIRouter(prefix="/api/auth")

SESSION_COOKIE = "insight_session"
SESSION_TTL    = 60 * 60 * 8   # 8 hours


# ─────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def init_db():
    """Create all tables if they don't exist."""
    db  = get_db()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            email               VARCHAR(255) UNIQUE NOT NULL,
            password_hash       BLOB NOT NULL,
            role                ENUM('admin','instructor','student') NOT NULL DEFAULT 'student',
            is_verified         TINYINT(1) NOT NULL DEFAULT 0,
            is_approved         TINYINT(1) NOT NULL DEFAULT 0,
            must_change_password TINYINT(1) NOT NULL DEFAULT 0,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id   INT AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(20) UNIQUE NOT NULL,
            name VARCHAR(200) NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id    INT PRIMARY KEY,
            student_id VARCHAR(50),
            first_name VARCHAR(100),
            last_name  VARCHAR(100),
            gender     VARCHAR(20),
            department VARCHAR(50),
            section    VARCHAR(50),
            contact    VARCHAR(20),
            avatar_url VARCHAR(500),
            qr_code_data    VARCHAR(500) UNIQUE,
            qr_image_base64 LONGTEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS otp_tokens (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            email      VARCHAR(255) NOT NULL,
            otp        VARCHAR(10)  NOT NULL,
            purpose    ENUM('register','forgot') NOT NULL,
            expires_at BIGINT NOT NULL,
            INDEX idx_email_purpose (email, purpose)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token      VARCHAR(128) PRIMARY KEY,
            user_id    INT NOT NULL,
            role       VARCHAR(20)  NOT NULL,
            expires_at BIGINT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Attendance tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            code             VARCHAR(20) NOT NULL,
            name             VARCHAR(200) NOT NULL,
            instructor_id    INT,
            join_code        VARCHAR(20) UNIQUE NOT NULL,
            schedule_start   TIME,
            schedule_end     TIME,
            time_window_min  INT DEFAULT 30,
            latitude         DECIMAL(10, 8),
            longitude        DECIMAL(11, 8),
            location_radius  INT DEFAULT 100,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instructor_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            subject_id   INT NOT NULL,
            day_of_week  ENUM('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday') NOT NULL,
            start_time   TIME NOT NULL,
            end_time     TIME NOT NULL,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subject_enrollments (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            enroll_code VARCHAR(20) NOT NULL,
            student_id  VARCHAR(50) NOT NULL,
            section     VARCHAR(50),
            fullname    VARCHAR(255),
            status      ENUM('pending','enrolled') NOT NULL DEFAULT 'pending',
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_code_stu (enroll_code, student_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gate_logs (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            user_id         INT NULL,
            student_id      INT NULL,
            visitor_id      INT NULL,
            camera_id       INT NULL,
            event_type      VARCHAR(100) NULL,
            method          VARCHAR(50) NULL DEFAULT 'face',
            logged_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            timestamp       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            first_name      VARCHAR(100) NULL,
            last_name       VARCHAR(100) NULL,
            face_confidence FLOAT NULL,
            has_uniform     TINYINT(1) DEFAULT 0,
            has_id_card     TINYINT(1) DEFAULT 0,
            image_url       VARCHAR(500) NULL,
            overall_status  ENUM('allowed','warning','denied','visitor') DEFAULT 'warning',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (visitor_id) REFERENCES visitors(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gate_activity (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            student_id   INT NULL,
            visitor_id   INT NULL,
            activity_type ENUM('entry','exit') NOT NULL,
            timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (visitor_id) REFERENCES visitors(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'gate_logs'
    """)
    gate_log_columns = {row[0] for row in cur.fetchall()}

    gate_log_additions = {
        "user_id": "ALTER TABLE gate_logs ADD COLUMN user_id INT NULL",
        "student_id": "ALTER TABLE gate_logs ADD COLUMN student_id INT NULL",
        "visitor_id": "ALTER TABLE gate_logs ADD COLUMN visitor_id INT NULL",
        "camera_id": "ALTER TABLE gate_logs ADD COLUMN camera_id INT NULL",
        "event_type": "ALTER TABLE gate_logs ADD COLUMN event_type VARCHAR(100) NULL",
        "method": "ALTER TABLE gate_logs ADD COLUMN method VARCHAR(50) NULL DEFAULT 'face'",
        "logged_at": "ALTER TABLE gate_logs ADD COLUMN logged_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "timestamp": "ALTER TABLE gate_logs ADD COLUMN timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "first_name": "ALTER TABLE gate_logs ADD COLUMN first_name VARCHAR(100) NULL",
        "last_name": "ALTER TABLE gate_logs ADD COLUMN last_name VARCHAR(100) NULL",
        "face_confidence": "ALTER TABLE gate_logs ADD COLUMN face_confidence FLOAT NULL",
        "has_uniform": "ALTER TABLE gate_logs ADD COLUMN has_uniform TINYINT(1) DEFAULT 0",
        "has_id_card": "ALTER TABLE gate_logs ADD COLUMN has_id_card TINYINT(1) DEFAULT 0",
        "image_url": "ALTER TABLE gate_logs ADD COLUMN image_url VARCHAR(500) NULL",
        "overall_status": "ALTER TABLE gate_logs ADD COLUMN overall_status ENUM('allowed','warning','denied','visitor') DEFAULT 'warning'",
    }
    for column_name, sql in gate_log_additions.items():
        if column_name not in gate_log_columns:
            cur.execute(sql)
        elif column_name == "overall_status":
            # Update ENUM if it already exists
            cur.execute("ALTER TABLE gate_logs MODIFY COLUMN overall_status ENUM('allowed','warning','denied','visitor') DEFAULT 'warning'")

    cur.execute("ALTER TABLE gate_logs MODIFY COLUMN event_type VARCHAR(100) NULL")
    cur.execute("ALTER TABLE gate_logs MODIFY COLUMN method VARCHAR(50) NULL DEFAULT 'face'")

    # Migration for gate_activity
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'gate_activity'")
    activity_columns = {row[0] for row in cur.fetchall()}
    if "visitor_id" not in activity_columns:
        cur.execute("ALTER TABLE gate_activity ADD COLUMN visitor_id INT NULL")
    if "student_id" in activity_columns:
        cur.execute("ALTER TABLE gate_activity MODIFY COLUMN student_id INT NULL")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            user_id       INT NULL,
            first_name    VARCHAR(100) NOT NULL,
            last_name     VARCHAR(100) NOT NULL,
            student_id    VARCHAR(50),
            reason        TEXT,
            severity      ENUM('low','medium','high','critical') DEFAULT 'medium',
            reported_by   INT NULL,
            image_url     VARCHAR(500),
            status        ENUM('active','resolved') DEFAULT 'active',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at   DATETIME NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (reported_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            first_name   VARCHAR(100) NOT NULL,
            last_name    VARCHAR(100) NOT NULL,
            contact      VARCHAR(50),
            purpose      TEXT,
            face_image_url VARCHAR(500),
            face_encoding  LONGBLOB,
            time_in      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            time_out     DATETIME NULL,
            recorded_by  INT NULL,
            FOREIGN KEY (recorded_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # Migration for visitors table
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'visitors'")
    visitor_columns = {row[0] for row in cur.fetchall()}
    if "face_image_url" not in visitor_columns:
        cur.execute("ALTER TABLE visitors ADD COLUMN face_image_url VARCHAR(500)")
    if "face_encoding" not in visitor_columns:
        cur.execute("ALTER TABLE visitors ADD COLUMN face_encoding LONGBLOB")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS uniform_violations (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            user_id         INT NULL,
            student_id      VARCHAR(50),
            first_name      VARCHAR(100) NULL,
            last_name       VARCHAR(100) NULL,
            violation_type  VARCHAR(100) NOT NULL,
            description     TEXT,
            image_url       VARCHAR(500),
            camera_id       INT NULL,
            gate_log_id     INT NULL,
            status          ENUM('pending','reviewed','resolved') DEFAULT 'pending',
            reported_by     INT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at     DATETIME NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (reported_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS temporary_passes (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            user_id      INT NOT NULL,
            reason       TEXT,
            expires_at   DATETIME NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            issued_by    INT NULL,
            status       ENUM('active','expired','revoked') DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (issued_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    db.commit()
    cur.close()
    db.close()


# ─────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────

def create_session(user_id: int, role: str) -> str:
    token   = secrets.token_hex(64)
    expires = int(time.time()) + SESSION_TTL
    db  = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    cur.execute(
        "INSERT INTO sessions (token, user_id, role, expires_at) VALUES (%s,%s,%s,%s)",
        (token, user_id, role, expires)
    )
    db.commit()
    cur.close()
    db.close()
    return token


def get_session(token: str) -> dict | None:
    if not token:
        return None
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT user_id, role, expires_at FROM sessions WHERE token=%s", (token,)
    )
    row = cur.fetchone()
    cur.close()
    db.close()
    if not row:
        return None
    user_id, role, expires_at = row
    if int(time.time()) > expires_at:
        delete_session(token)
        return None
    return {"user_id": user_id, "role": role}


def delete_session(token: str):
    db  = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM sessions WHERE token=%s", (token,))
    db.commit()
    cur.close()
    db.close()


def require_session(request: Request) -> dict:
    """Raise 401 if no valid session. Returns session dict."""
    token   = request.cookies.get(SESSION_COOKIE)
    session = get_session(token)
    if not session:
        raise HTTPException(401, "Not authenticated")
    return session


def require_role(session: dict, *roles: str):
    """Raise 403 if session role not in allowed roles."""
    if session["role"] not in roles:
        raise HTTPException(403, "Insufficient permissions")


# ─────────────────────────────────────────────────────────
# Password helpers
# ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> bytes:
    salt = os.urandom(16)
    dk   = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 260_000)
    return salt + dk


def verify_password(plain: str, stored_blob: bytes) -> bool:
    salt      = stored_blob[:16]
    stored_dk = stored_blob[16:]
    dk        = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 260_000)
    return hmac.compare_digest(dk, stored_dk)


def encrypt_password(plain: str) -> bytes:
    raw = hash_password(plain)
    return encrypt_user_data({"pwd": raw.hex()})


def decrypt_and_verify(plain: str, cipher_blob: bytes) -> bool:
    data = decrypt_user_data(cipher_blob)
    raw  = bytes.fromhex(data["pwd"])
    return verify_password(plain, raw)


def generate_temp_password(length: int = 10) -> str:
    """Generate a secure random temporary password."""
    chars = string.ascii_letters + string.digits + "!@#$%"
    pwd   = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("!@#$%"),
    ]
    pwd  += random.choices(chars, k=length - len(pwd))
    random.shuffle(pwd)
    return "".join(pwd)


# ─────────────────────────────────────────────────────────
# Email helpers
# ─────────────────────────────────────────────────────────

GMAIL_FROM = os.getenv("GMAIL_ADDRESS", "")
GMAIL_PASS = os.getenv("GMAIL_PASSWORD", "")


def _send_email(to_email: str, subject: str, html_body: str):
    msg              = MIMEMultipart("alternative")
    msg["Subject"]   = subject
    msg["From"]      = GMAIL_FROM
    msg["To"]        = to_email
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_FROM, GMAIL_PASS)
        s.sendmail(GMAIL_FROM, to_email, msg.as_string())


def _send_email_sync(to_email: str, subject: str, html_body: str):
    # Kept for explicit naming used by async fallback
    _send_email(to_email, subject, html_body)


async def _send_email_async(to_email: str, subject: str, html_body: str):
    """Try to publish email send task to RabbitMQ; fallback to sync send."""
    try:
        import rabbitmq
        payload = {"to_email": to_email, "subject": subject, "html": html_body}
        try:
            await rabbitmq.publish_task("send_email", payload, routing_key="email")
            return True
        except Exception as e:
            # Publishing failed; fallback to synchronous SMTP in thread
            print(f"⚠️ RabbitMQ publish failed, falling back to SMTP: {e}")
            await asyncio.to_thread(_send_email_sync, to_email, subject, html_body)
            return True
    except Exception as e:
        # If rabbitmq module not importable or other errors, send via SMTP
        print(f"⚠️ send_email_async fallback path: {e}")
        await asyncio.to_thread(_send_email_sync, to_email, subject, html_body)
        return True


async def send_otp_email(to_email: str, otp: str, purpose: str):
    subj = (
        "InSight – Your Verification Code"
        if purpose == "register"
        else "InSight – Password Reset Code"
    )
    label = "verification" if purpose == "register" else "password reset"
    body  = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;
                border-radius:12px;background:#f9fafb;border:1px solid #e5e7eb">
      <h2 style="color:#023047">InSight</h2>
      <p style="color:#374151">Your {label} code is:</p>
      <div style="font-size:40px;font-weight:900;letter-spacing:14px;color:#219ebc;
                  margin:20px 0;text-align:center">{otp}</div>
      <p style="color:#6b7280;font-size:13px">
        This code expires in 10 minutes.<br>
        If you did not request this, you can safely ignore this email.
      </p>
    </div>"""
    await _send_email_async(to_email, subj, body)


async def send_temp_password_email(to_email: str, role: str, temp_password: str):
    role_label = role.capitalize()
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;
                border-radius:12px;background:#f9fafb;border:1px solid #e5e7eb">
      <h2 style="color:#023047">Welcome to InSight</h2>
      <p style="color:#374151">
        Your <strong>{role_label}</strong> account has been created by an administrator.
      </p>
      <p style="color:#374151">Use the temporary password below to log in:</p>
      <div style="font-size:28px;font-weight:900;letter-spacing:6px;color:#219ebc;
                  margin:20px 0;text-align:center;background:#e0f2fe;padding:16px;
                  border-radius:8px;font-family:monospace">{temp_password}</div>
      <p style="color:#ef4444;font-weight:700">
        ⚠️ You must change this password on your first login.
      </p>
      <p style="color:#6b7280;font-size:13px">
        Log in at: <a href="/login" style="color:#219ebc">/login</a>
      </p>
    </div>"""
    await _send_email_async(to_email, "InSight – Your Account Has Been Created", body)


# ─────────────────────────────────────────────────────────
# OTP helpers
# ─────────────────────────────────────────────────────────

def generate_otp(length: int = 5) -> str:
    return "".join(random.choices(string.digits, k=length))


def store_otp(email: str, otp: str, purpose: str):
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "DELETE FROM otp_tokens WHERE email=%s AND purpose=%s", (email, purpose)
    )
    expires = int(time.time()) + 600  # 10 min
    cur.execute(
        "INSERT INTO otp_tokens (email, otp, purpose, expires_at) VALUES (%s,%s,%s,%s)",
        (email, otp, purpose, expires)
    )
    db.commit()
    cur.close()
    db.close()


def verify_otp(email: str, otp: str, purpose: str) -> bool:
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT otp, expires_at FROM otp_tokens "
        "WHERE email=%s AND purpose=%s ORDER BY id DESC LIMIT 1",
        (email, purpose)
    )
    row = cur.fetchone()
    cur.close()
    db.close()
    if not row:
        return False
    stored_otp, expires_at = row
    if int(time.time()) > expires_at:
        return False
    return hmac.compare_digest(stored_otp, otp)


def delete_otp(email: str, purpose: str):
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "DELETE FROM otp_tokens WHERE email=%s AND purpose=%s", (email, purpose)
    )
    db.commit()
    cur.close()
    db.close()


# ─────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    confirm_password: str

class VerifyOtpRequest(BaseModel):
    email: str
    otp: str
    purpose: str

class InfoRequest(BaseModel):
    email: str
    student_id: str
    first_name: str
    last_name: str
    gender: str
    department: str
    section: str
    contact: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ForgotRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    new_password: str
    confirm_password: str

class ResendRequest(BaseModel):
    email: str
    purpose: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str



# ─────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────

# ── REGISTER ─────────────────────────────────────────────

@router.post("/register")
async def register(body: RegisterRequest):
    if body.password != body.confirm_password:
        raise HTTPException(400, "Passwords do not match")

    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, is_verified FROM users WHERE email=%s", (body.email,))
    existing = cur.fetchone()
    cur.close()
    db.close()

    if existing:
        _, is_verified = existing
        if is_verified:
            raise HTTPException(409, "Email is already registered")
    else:
        enc_pwd = encrypt_password(body.password)
        db2  = get_db()
        cur2 = db2.cursor()
        cur2.execute(
            "INSERT INTO users (email, password_hash, role, is_verified) "
            "VALUES (%s,%s,'student',0)",
            (body.email, enc_pwd)
        )
        db2.commit()
        cur2.close()
        db2.close()

    otp = generate_otp()
    store_otp(body.email, otp, "register")
    try:
        await send_otp_email(body.email, otp, "register")
    except Exception as e:
        raise HTTPException(500, f"Failed to send email: {e}")

    return {"message": "OTP sent", "email": body.email}


# ── REGISTER OTP VERIFY ───────────────────────────────────

@router.post("/register/verify")
async def register_verify(body: VerifyOtpRequest):
    if not verify_otp(body.email, body.otp, "register"):
        raise HTTPException(400, "Invalid or expired OTP")
    delete_otp(body.email, "register")
    return {"message": "OTP verified", "email": body.email}


# ── SAVE ACCOUNT INFO ─────────────────────────────────────

@router.post("/info")
async def save_info(body: InfoRequest):
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, role FROM users WHERE email=%s", (body.email,))
    row = cur.fetchone()
    if not row:
        cur.close(); db.close()
        raise HTTPException(404, "User not found")

    user_id, role = row
    cur.execute("UPDATE users SET is_verified=1 WHERE id=%s", (user_id,))
    # Auto-approve admins and instructors for now, students need manual approval
    if role != 'student':
        cur.execute("UPDATE users SET is_approved=1 WHERE id=%s", (user_id,))

    cur.execute("""
        INSERT INTO user_profiles
            (user_id, student_id, first_name, last_name, gender, department, section, contact)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            student_id=%s, first_name=%s, last_name=%s,
            gender=%s, department=%s, section=%s, contact=%s
    """, (
        user_id, body.student_id, body.first_name, body.last_name,
        body.gender, body.department, body.section, body.contact,
        body.student_id, body.first_name, body.last_name,
        body.gender, body.department, body.section, body.contact
    ))
    db.commit()
    cur.close()
    db.close()

    return {"message": "Account info saved. Please wait for admin approval.", "user_id": user_id, "role": role}


# ── LOGIN ─────────────────────────────────────────────────

@router.post("/login")
async def login(body: LoginRequest, response: Response):
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id, password_hash, role, is_verified, must_change_password, is_approved "
        "FROM users WHERE email=%s",
        (body.email,)
    )
    row = cur.fetchone()
    cur.close()
    db.close()

    if not row:
        print(f"DEBUG: Login failed - Email not found: {body.email}")
        raise HTTPException(401, "Invalid email or password")

    user_id, enc_pwd_blob, role, is_verified, must_change, is_approved = row

    if not is_verified:
        print(f"DEBUG: Login failed - Not verified: {body.email}")
        raise HTTPException(403, "Account not yet verified. Please complete registration.")

    if role == 'student' and not is_approved:
        print(f"DEBUG: Login failed - Not approved: {body.email}")
        raise HTTPException(403, "Account pending admin approval.")

    if isinstance(enc_pwd_blob, str):
        enc_pwd_blob = enc_pwd_blob.encode("latin-1")

    try:
        ok = decrypt_and_verify(body.password, enc_pwd_blob)
    except Exception as e:
        print(f"DEBUG: Login failed - Decryption error for {body.email}: {e}")
        ok = False

    if not ok:
        print(f"DEBUG: Login failed - Password mismatch for {body.email}")
        raise HTTPException(401, "Invalid email or password")

    token = create_session(user_id, role)
    response.set_cookie(
        key=SESSION_COOKIE, value=token,
        httponly=True, samesite="lax",
        max_age=SESSION_TTL, path="/"
    )

    redirect_map = {
        "admin":      "/admin",
        "instructor": "/instructor",
        "student":    "/student",
    }

    return {
        "message":             "Login successful",
        "role":                role,
        "must_change_password": bool(must_change),
        "redirect":            redirect_map.get(role, "/student"),
    }


# ── LOGOUT ────────────────────────────────────────────────

@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"message": "Logged out"}


# ── ME (session info) ─────────────────────────────────────

@router.get("/me")
async def me(request: Request):
    session = require_session(request)
    return session


# ── FORGOT PASSWORD – send code ───────────────────────────

@router.post("/forgot")
async def forgot(body: ForgotRequest):
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id FROM users WHERE email=%s AND is_verified=1", (body.email,)
    )
    row = cur.fetchone()
    cur.close()
    db.close()

    if row:
        otp = generate_otp()
        store_otp(body.email, otp, "forgot")
        try:
            await send_otp_email(body.email, otp, "forgot")
        except Exception as e:
            raise HTTPException(500, f"Failed to send email: {e}")

    # Always return OK to prevent email enumeration
    return {"message": "If that email exists, a reset code was sent"}


# ── FORGOT OTP VERIFY ─────────────────────────────────────

@router.post("/forgot/verify")
async def forgot_verify(body: VerifyOtpRequest):
    if not verify_otp(body.email, body.otp, "forgot"):
        raise HTTPException(400, "Invalid or expired OTP")
    return {"message": "OTP verified", "email": body.email}


# ── RESET PASSWORD ────────────────────────────────────────

@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    if body.new_password != body.confirm_password:
        raise HTTPException(400, "Passwords do not match")

    db  = get_db()
    cur = db.cursor()
    # Require that the forgot OTP was verified recently (still in table)
    cur.execute(
        "SELECT id FROM otp_tokens "
        "WHERE email=%s AND purpose='forgot' AND expires_at > %s",
        (body.email, int(time.time()))
    )
    if not cur.fetchone():
        cur.close(); db.close()
        raise HTTPException(400, "Reset session expired, please start over")

    enc_pwd = encrypt_password(body.new_password)
    cur.execute(
        "UPDATE users SET password_hash=%s, must_change_password=0 WHERE email=%s",
        (enc_pwd, body.email)
    )
    db.commit()
    delete_otp(body.email, "forgot")
    cur.close()
    db.close()
    return {"message": "Password reset successfully"}


# ── CHANGE PASSWORD (while logged in) ─────────────────────

@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, request: Request):
    session = require_session(request)
    user_id = session["user_id"]

    if body.new_password != body.confirm_password:
        raise HTTPException(400, "Passwords do not match")

    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT password_hash FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); db.close()
        raise HTTPException(404, "User not found")

    enc_blob = row[0]
    if isinstance(enc_blob, str):
        enc_blob = enc_blob.encode("latin-1")

    try:
        ok = decrypt_and_verify(body.current_password, enc_blob)
    except Exception:
        ok = False

    if not ok:
        cur.close(); db.close()
        raise HTTPException(400, "Current password is incorrect")

    enc_new = encrypt_password(body.new_password)
    cur.execute(
        "UPDATE users SET password_hash=%s, must_change_password=0 WHERE id=%s",
        (enc_new, user_id)
    )
    db.commit()
    cur.close()
    db.close()
    return {"message": "Password changed successfully"}


# ── RESEND OTP ────────────────────────────────────────────

@router.post("/resend")
async def resend(body: ResendRequest):
    if body.purpose not in ("register", "forgot"):
        raise HTTPException(400, "Invalid purpose")
    otp = generate_otp()
    store_otp(body.email, otp, body.purpose)
    try:
        await send_otp_email(body.email, otp, body.purpose)
    except Exception as e:
        raise HTTPException(500, f"Failed to send email: {e}")
    return {"message": "OTP resent"}
