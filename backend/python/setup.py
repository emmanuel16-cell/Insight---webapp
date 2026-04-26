"""
setup.py  –  InSight System Setup
Handles first-time system initialization: checking whether an admin account
exists and creating the very first administrator account.

Endpoints:
  GET  /api/system/setup-status        – returns {"admin_exists": bool}
  POST /api/system/create-first-admin  – creates the first admin (blocked if one exists)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth import get_db, encrypt_password

router = APIRouter(prefix="/api/system")


# ── Helper ────────────────────────────────────────────────

def check_admin_exists() -> bool:
    """Return True if at least one verified admin account exists."""
    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_verified=1")
        count = cur.fetchone()[0]
        cur.close()
        db.close()
        return count > 0
    except Exception:
        # If the table doesn't exist yet (very first boot before init_db),
        # treat it as no admin.
        return False


# ── Pydantic model ────────────────────────────────────────

class FirstAdminRequest(BaseModel):
    email:    str
    password: str


# ── Routes ───────────────────────────────────────────────

@router.get("/setup-status")
async def setup_status():
    """
    Check whether the system has been set up.
    Returns admin_exists: true once the first admin account has been created.
    """
    exists = check_admin_exists()
    return {"admin_exists": exists, "setup_required": not exists}


@router.post("/create-first-admin")
async def create_first_admin(body: FirstAdminRequest):
    """
    Create the very first administrator account.
    This endpoint is permanently disabled once any admin exists —
    subsequent admin creation must go through /api/admin/create-account.
    """
    if check_admin_exists():
        raise HTTPException(
            409,
            "An administrator account already exists. "
            "Please log in through the normal login page."
        )

    # Basic validation
    email = body.email.strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Please provide a valid email address.")

    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    db  = get_db()
    cur = db.cursor()

    # Guard: email not already taken (edge case if someone registered before setup)
    cur.execute("SELECT id FROM users WHERE email=%s", (email,))
    if cur.fetchone():
        cur.close(); db.close()
        raise HTTPException(409, "This email address is already registered.")

    enc_pwd = encrypt_password(body.password)

    cur.execute(
        "INSERT INTO users (email, password_hash, role, is_verified, must_change_password) "
        "VALUES (%s, %s, 'admin', 1, 0)",
        (email, enc_pwd)
    )
    new_id = cur.lastrowid

    # Create an empty profile row so JOINs on user_profiles don't break
    cur.execute(
        "INSERT IGNORE INTO user_profiles (user_id, first_name, last_name) "
        "VALUES (%s, 'System', 'Administrator')",
        (new_id,)
    )

    db.commit()
    cur.close()
    db.close()

    return {
        "message": "Administrator account created successfully. You may now log in.",
        "email":   email,
        "role":    "admin",
    }
