"""
user_profile.py  –  InSight User Profile Router
GET  /api/user/profile          – fetch own profile
PUT  /api/user/profile          – update own profile
POST /api/user/change-password  – change password (logged in)
"""

import os
import time
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from dotenv import load_dotenv

from auth import get_db, require_session, encrypt_password, decrypt_and_verify

load_dotenv()

router = APIRouter(prefix="/api/user")


# ── Pydantic models ───────────────────────────────────────

class ProfileUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name:  str | None = None
    gender:     str | None = None
    department: str | None = None
    section:    str | None = None
    contact:    str | None = None
    email:      str | None = None
    avatar_url: str | None = None

class ChangePasswordRequest(BaseModel):
    current_password: str | None = None
    new_password:     str
    confirm_password: str


# ── GET profile ───────────────────────────────────────────

@router.get("/profile")
async def get_profile(request: Request):
    session = require_session(request)
    user_id = session["user_id"]

    db  = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute(
        "SELECT u.id, u.email, u.role, u.must_change_password, "
        "       p.student_id, p.first_name, p.last_name, "
        "       p.gender, p.department, p.section, p.contact, p.avatar_url "
        "FROM users u "
        "LEFT JOIN user_profiles p ON p.user_id = u.id "
        "WHERE u.id = %s",
        (user_id,)
    )
    row = cur.fetchone()
    
    # Get facial biometrics if exists
    biometrics = None
    if session.get("role") == "student":
        cur.execute(
            "SELECT face_id, profile_photo_path, is_verified FROM facial_features WHERE user_id = %s",
            (user_id,)
        )
        bio_row = cur.fetchone()
        # Only include biometrics if face_id exists (fully registered)
        if bio_row and bio_row.get("face_id"):
            biometrics = {
                "face_id": bio_row["face_id"],
                "profile_photo_path": bio_row["profile_photo_path"],
                "is_verified": bool(bio_row["is_verified"])
            }
    
    cur.close()
    db.close()

    if not row:
        raise HTTPException(404, "User not found")

    profile = {
        "id":                  row["id"],
        "email":               row["email"],
        "role":                row["role"],
        "must_change_password": bool(row["must_change_password"]),
        "student_id":          row["student_id"],
        "first_name":          row["first_name"],
        "last_name":           row["last_name"],
        "gender":              row["gender"],
        "department":          row["department"],
        "section":             row["section"],
        "contact":             row["contact"],
        "avatar_url":          row["avatar_url"],
    }
    
    # Add biometric data for students
    if biometrics:
        profile["registered_biometrics"] = biometrics

    return profile


@router.post("/profile/upload-avatar")
async def upload_avatar(file: UploadFile = File(...), request: Request = None):
    """
    Simple avatar upload for non-student users (Admin/Instructor).
    Does NOT extract facial features.
    """
    session = require_session(request)
    user_id = session["user_id"]
    
    # Create directory if not exists
    upload_dir = "public/profile_photos"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    # Generate unique filename
    ext = os.path.splitext(file.filename)[1]
    filename = f"avatar_{user_id}_{int(time.time())}{ext}"
    file_path = os.path.join(upload_dir, filename)
    
    # Save file
    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)
        
    avatar_url = f"/{file_path}"
    
    # Update DB
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE user_profiles SET avatar_url=%s WHERE user_id=%s",
        (avatar_url, user_id)
    )
    db.commit()
    cur.close()
    db.close()
    
    return {"message": "Avatar uploaded", "avatar_url": avatar_url}

@router.put("/profile")
async def update_profile(body: ProfileUpdateRequest, request: Request):
    session = require_session(request)
    user_id = session["user_id"]

    db  = get_db()
    cur = db.cursor()

    try:
        # 1. Handle Employee ID generation if it's the first time
        cur.execute("SELECT student_id FROM user_profiles WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        current_sid = row[0] if row else None
        
        # If no SID, generate FCLTY-XXXX (for non-students)
        if not current_sid and session["role"] != "student":
            cur.execute("SELECT MAX(id) FROM users")
            max_id = cur.fetchone()[0] or 0
            current_sid = f"FCLTY-{1000 + max_id}"

        # Update email in users table if provided
        if body.email:
            cur.execute(
                "UPDATE users SET email=%s WHERE id=%s",
                (body.email, user_id)
            )

        # Upsert profile row
        cur.execute("""
            INSERT INTO user_profiles
                (user_id, student_id, first_name, last_name, gender, department, section, contact, avatar_url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                student_id=COALESCE(student_id, VALUES(student_id)),
                first_name=VALUES(first_name),
                last_name=VALUES(last_name),
                gender=VALUES(gender),
                department=VALUES(department),
                section=VALUES(section),
                contact=VALUES(contact),
                avatar_url=COALESCE(VALUES(avatar_url), avatar_url)
        """, (
            user_id, current_sid,
            body.first_name, body.last_name, body.gender,
            body.department, body.section, body.contact, body.avatar_url
        ))
        db.commit()
        return {"message": "Profile updated successfully"}
    except Exception as e:
        print(f"ERROR updating profile: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        cur.close()
        db.close()


# ── POST change-password ──────────────────────────────────

@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, request: Request):
    session = require_session(request)
    user_id = session["user_id"]

    if body.new_password != body.confirm_password:
        raise HTTPException(400, "Passwords do not match")

    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    db  = get_db()
    cur = db.cursor()

    # 1. Verify current password if provided
    if body.current_password:
        cur.execute("SELECT password_hash FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
        if not row or not decrypt_and_verify(body.current_password, row[0]):
            cur.close(); db.close()
            raise HTTPException(401, "Incorrect current password")

    # 2. Update to new password
    enc_new = encrypt_password(body.new_password)
    cur.execute(
        "UPDATE users SET password_hash=%s, must_change_password=0 WHERE id=%s",
        (enc_new, user_id)
    )
    db.commit()
    cur.close()
    db.close()
    return {"message": "Password updated successfully"}