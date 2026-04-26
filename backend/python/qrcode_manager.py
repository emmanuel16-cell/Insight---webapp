"""
qrcode_manager.py  –  QR Code Generation & Student QR Management
Generates unique QR codes for students when they create accounts.
Stores QR data and handles QR code retrieval/regeneration.
"""

import os
import qrcode
import secrets
from io import BytesIO
from base64 import b64encode
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv

from auth import get_db, require_session

load_dotenv()

router = APIRouter(prefix="/api/qr")

# ── Database setup ────────────────────────────────────────

def init_qr_db():
    """QR table initialization (deprecated - moved to user_profiles)."""
    pass


# ── Models ────────────────────────────────────────────────

class QRCodeResponse(BaseModel):
    user_id: int
    qr_code_data: str
    qr_image_base64: str


# ── Functions ─────────────────────────────────────────────

def generate_qr_code_data(user_id: int, email: str) -> str:
    """Create unique QR code data string."""
    unique_token = secrets.token_urlsafe(32)
    return f"INSIGHT:USER:{user_id}:EMAIL:{email}:TOKEN:{unique_token}"


def create_qr_image_base64(qr_data: str) -> str:
    """Generate QR code image and return as base64 string."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_base64 = b64encode(img_bytes.getvalue()).decode()

    return img_base64


def generate_student_qrcode(user_id: int, email: str):
    """Generate and store QR code for student."""
    db = get_db()
    cur = db.cursor(dictionary=True)

    # Check if QR already exists in user_profiles
    cur.execute("SELECT user_id FROM user_profiles WHERE user_id = %s AND qr_code_data IS NOT NULL", (user_id,))
    existing = cur.fetchone()

    if existing:
        cur.close()
        db.close()
        return get_qrcode_by_user(user_id)

    # Generate new QR
    qr_data = generate_qr_code_data(user_id, email)
    qr_image_b64 = create_qr_image_base64(qr_data)

    cur.execute(
        "UPDATE user_profiles SET qr_code_data = %s, qr_image_base64 = %s "
        "WHERE user_id = %s",
        (qr_data, qr_image_b64, user_id)
    )
    db.commit()
    cur.close()
    db.close()
    return {"user_id": user_id, "qr_code_data": qr_data, "qr_image_base64": qr_image_b64}


def get_student_qr_base64(user_id: int, email: str) -> str:
    """Helper to generate and return just the base64 string for a student."""
    qr_data = generate_qr_code_data(user_id, email)
    return create_qr_image_base64(qr_data)


def get_qrcode_by_user(user_id: int):
    """Get QR code for a user."""
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute(
        "SELECT user_id, qr_code_data, qr_image_base64 FROM user_profiles "
        "WHERE user_id = %s",
        (user_id,)
    )
    row = cur.fetchone()
    cur.close()
    db.close()

    if not row or not row.get("qr_code_data"):
        return None

    return {
        "user_id": row["user_id"],
        "qr_code_data": row["qr_code_data"],
        "qr_image_base64": row["qr_image_base64"],
    }


def get_user_by_qrcode_data(qr_data: str):
    """Lookup user by QR code data."""
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute(
        "SELECT user_id FROM user_profiles WHERE qr_code_data = %s",
        (qr_data,)
    )
    row = cur.fetchone()
    cur.close()
    db.close()

    return row["user_id"] if row else None


def verify_qr_token(qr_data: str):
    """
    Verifies if the QR data is valid and returns the user_id.
    Format: INSIGHT:USER:{id}:EMAIL:{email}:TOKEN:{token}
    """
    if not qr_data.startswith("INSIGHT:USER:"):
        return None
    
    # We can either trust the DB lookup or parse and verify.
    # The DB lookup is safer as it checks if this exact token is still assigned to the user.
    return get_user_by_qrcode_data(qr_data)


# ── Routes ────────────────────────────────────────────────

@router.get("/my-qrcode")
async def get_my_qrcode(request: Request):
    """Get logged-in student's QR code."""
    session = require_session(request)
    user_id = session["user_id"]

    if session.get("role") != "student":
        raise HTTPException(403, "Only students can access their QR codes")

    qr = get_qrcode_by_user(user_id)
    if not qr:
        # Auto-generate if not found
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        db.close()
        
        if user:
            qr = generate_student_qrcode(user_id, user["email"])
        else:
            raise HTTPException(404, "QR code not found")

    return qr


@router.post("/regenerate")
async def regenerate_qrcode(request: Request):
    """Regenerate QR code for student."""
    session = require_session(request)
    user_id = session["user_id"]

    if session.get("role") != "student":
        raise HTTPException(403, "Only students can regenerate QR codes")

    db = get_db()
    cur = db.cursor()

    # Clear old QR
    cur.execute("UPDATE user_profiles SET qr_code_data = NULL, qr_image_base64 = NULL WHERE user_id = %s", (user_id,))
    db.commit()
    cur.close()
    db.close()

    # Get email for new QR
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    db.close()

    if not user:
        raise HTTPException(404, "User not found")

    # Generate new QR
    qr = generate_student_qrcode(user_id, user["email"])
    return {"message": "QR code regenerated", "qr": qr}


@router.get("/verify/{qr_data}")
async def verify_qrcode(qr_data: str):
    """Verify QR code and return user info (for gate/instructor scanning)."""
    user_id = get_user_by_qrcode_data(qr_data)

    if not user_id:
        raise HTTPException(404, "Invalid QR code")

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute(
        "SELECT u.id, u.email, p.student_id, p.first_name, p.last_name, p.section "
        "FROM users u "
        "LEFT JOIN user_profiles p ON p.user_id = u.id "
        "WHERE u.id = %s",
        (user_id,)
    )
    user = cur.fetchone()
    cur.close()
    db.close()

    if not user:
        raise HTTPException(404, "User not found")

    return {
        "user_id": user["id"],
        "email": user["email"],
        "student_id": user["student_id"],
        "full_name": f"{user['first_name']} {user['last_name']}" if user['first_name'] else "Unknown",
        "section": user["section"],
    }
