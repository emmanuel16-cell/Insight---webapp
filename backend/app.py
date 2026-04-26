"""
app.py  –  InSight Main Application
FastAPI entry point. Mounts static files, includes all routers,
serves HTML pages, and exposes the YOLO /detect endpoint.
"""

import os
import cv2
import numpy as np
import uvicorn
import socket

from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from ultralytics import YOLO
from dotenv import load_dotenv

load_dotenv()
import asyncio

# ── DISCOVERY HELPERS ─────────────────────────────────────
def get_local_ip():
    """Returns the primary local IP address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually connect, just used to find the right interface
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

async def broadcast_server_ip():
    """Broadcasts the server's local IP on the network for Flutter discovery."""
    broadcast_target = "255.255.255.255"
    port = 8888
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    print(f"📡 Discovery: Broadcasting IP on port {port}...")
    try:
        while True:
            ip = get_local_ip()
            message = f"INSIGHT_SERVER_IP:{ip}"
            sock.sendto(message.encode(), (broadcast_target, port))
            await asyncio.sleep(5) # Broadcast every 5 seconds
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"⚠️ Discovery service error: {e}")
    finally:
        sock.close()

# ── LIFESPAN ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the discovery broadcast in the background
    discovery_task = asyncio.create_task(broadcast_server_ip())

    # Startup logic: initialize database tables
    print("📊 Initializing InSight database tables...")
    # Note: These functions are imported later in the file
    init_db()
    print("  ✅ Auth tables initialized")
    init_facial_db()
    print("  ✅ Facial features tables initialized")
    init_gate_db()
    print("  ✅ Gate security tables initialized")
    init_attendance_db()
    print("  ✅ Attendance tables initialized")
    print("✅  All database tables initialized successfully!")

    # Try initialize RabbitMQ for background workers (optional)
    try:
        import rabbitmq
        ok = await rabbitmq.init_rabbit()
        if ok:
            print("✅  RabbitMQ initialized for background tasks")
        else:
            print("⚠️  RabbitMQ not available; continuing without workers")
    except Exception as e:
        print(f"⚠️  RabbitMQ init exception: {e}")

    yield

    # Shutdown logic
    discovery_task.cancel()
    try:
        import rabbitmq
        await rabbitmq.close_rabbit()
        print("✅ RabbitMQ connection closed")
    except Exception as e:
        print(f"⚠️ RabbitMQ shutdown error: {e}")

# ── APP INSTANCE ──────────────────────────────────────────
app = FastAPI(
    title="InSight",
    description="Multi-Subject AI Attendance & Gate Security System",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for development (mobile/web)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── DIRECTORIES ───────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
PYTHON_DIR = os.path.join(BASE_DIR, "python")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SOURCE_DIR = os.path.join(PUBLIC_DIR, "source")
SCRIPT_DIR = os.path.join(PUBLIC_DIR, "script")
HTML_DIR   = os.path.join(PUBLIC_DIR, "frontend")
STYLE_DIR  = os.path.join(PUBLIC_DIR, "style")
VENDOR_DIR  = os.path.join(PUBLIC_DIR, "vendor")

MODEL_PATH = os.path.join(PUBLIC_DIR, "model", "best.pt")

# ── STATIC MOUNTS ─────────────────────────────────────────
app.mount("/public",  StaticFiles(directory=PUBLIC_DIR),  name="public")
app.mount("/static",  StaticFiles(directory=STATIC_DIR),  name="static")
app.mount("/python",  StaticFiles(directory=PYTHON_DIR),  name="python")
app.mount("/style",   StaticFiles(directory=STYLE_DIR),   name="style")
app.mount("/vendor",   StaticFiles(directory=VENDOR_DIR),   name="vendor")
app.mount("/source",  StaticFiles(directory=SOURCE_DIR),  name="source")
app.mount("/script",  StaticFiles(directory=SCRIPT_DIR),  name="script")

# ── ROUTERS ───────────────────────────────────────────────
from auth import router as auth_router, init_db, get_session, SESSION_COOKIE
from user_profile import router as profile_router
from admin import router as admin_router
from qrcode_manager import router as qr_router
from facial_features import router as facial_router, init_facial_db
from gate_security import router as gate_router, init_gate_db
from dashboards import router as dashboard_router
from attendance import router as attendance_router, init_attendance_db
from setup import router as setup_router, check_admin_exists

app.include_router(setup_router)   # must be first — used before any admin exists
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(admin_router)
app.include_router(qr_router)
app.include_router(facial_router)
app.include_router(gate_router)
app.include_router(dashboard_router)
app.include_router(attendance_router)



# ── YOLO ──────────────────────────────────────────────────
print("Loading YOLO model…")
try:
    model = YOLO(MODEL_PATH)
    model.fuse()
    print("✅  YOLO model loaded")
except Exception as e:
    print(f"⚠️  YOLO model not loaded: {e}")
    model = None

# ── AUTH GUARD ────────────────────────────────────────────

def guard(request: Request, allowed_roles: list[str]) -> RedirectResponse | None:
    """Returns RedirectResponse to /login if session invalid/wrong role."""
    token   = request.cookies.get(SESSION_COOKIE)
    session = get_session(token)
    if not session or session["role"] not in allowed_roles:
        return RedirectResponse(url="/login", status_code=302)
    return None

# ── HTML ROUTES ───────────────────────────────────────────

@app.get("/setup")
async def setup_page(request: Request):
    """First-time setup page. Redirects to /login once an admin exists."""
    if check_admin_exists():
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(os.path.join(HTML_DIR, "setup.html"))


@app.get("/")
async def home(request: Request):
    # Before anything else: if no admin account exists, go to first-time setup.
    if not check_admin_exists():
        return RedirectResponse(url="/setup", status_code=302)
    token   = request.cookies.get(SESSION_COOKIE)
    session = get_session(token)
    if session:
        rmap = {"admin": "/admin", "instructor": "/instructor", "student": "/student"}
        return RedirectResponse(url=rmap.get(session["role"], "/student"), status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login")
async def login_page(request: Request):
    # Redirect to setup if the system hasn't been initialized yet.
    if not check_admin_exists():
        return RedirectResponse(url="/setup", status_code=302)
    token   = request.cookies.get(SESSION_COOKIE)
    session = get_session(token)
    if session:
        rmap = {"admin": "/admin", "instructor": "/instructor", "student": "/student"}
        return RedirectResponse(url=rmap.get(session["role"], "/student"), status_code=302)
    return FileResponse(os.path.join(HTML_DIR, "index.html"))


@app.get("/admin")
async def admin_page(request: Request):
    redir = guard(request, ["admin"])
    if redir:
        return redir
    return FileResponse(os.path.join(HTML_DIR, "admin.html"))


@app.get("/instructor")
async def instructor_page(request: Request):
    redir = guard(request, ["instructor"])
    if redir:
        return redir
    return FileResponse(os.path.join(HTML_DIR, "instructor.html"))


@app.get("/debug-face")
async def debug_face_page(request: Request):
    return FileResponse(os.path.join(HTML_DIR, "debug-face.html"))


@app.get("/student")
async def student_page(request: Request):
    redir = guard(request, ["student"])
    if redir:
        return redir
    return FileResponse(os.path.join(HTML_DIR, "student.html"))


@app.get("/security")
async def security_page(request: Request):
    redir = guard(request, ["admin", "instructor"])
    if redir:
        return redir
    return FileResponse(os.path.join(HTML_DIR, "security.html"))


@app.get("/camera")
async def camera_page(request: Request):
    redir = guard(request, ["admin", "instructor"])
    if redir:
        return redir
    return FileResponse(os.path.join(HTML_DIR, "camera.html"))


@app.get("/view")
async def view_page(request: Request):
    redir = guard(request, ["admin", "instructor"])
    if redir:
        return redir
    return FileResponse(os.path.join(HTML_DIR, "view.html"))


@app.get("/visitor-kiosk")
async def visitor_kiosk_page(request: Request):
    return FileResponse(os.path.join(HTML_DIR, "visitor_kiosk.html"))


# ── YOLO DETECTION ────────────────────────────────────────

@app.post("/detect")
async def detect(request: Request, file: UploadFile = File(...)):
    """Receive a JPEG frame, run YOLO, return detections as JSON."""
    # Optional: auth check — only logged-in users may use this
    token   = request.cookies.get(SESSION_COOKIE)
    session = get_session(token)
    if not session:
        raise JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    if model is None:
        return JSONResponse(content=[])

    contents = await file.read()
    np_array = np.frombuffer(contents, np.uint8)
    img      = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

    if img is None:
        return JSONResponse(content=[])

    results    = model.track(img, imgsz=416, conf=0.3, iou=0.4, persist=True)
    detections = []

    for box in results[0].boxes:
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        cls_id  = int(box.cls[0])
        conf    = float(box.conf[0])
        label   = model.names[cls_id]
        track_id = int(box.id[0]) if box.id is not None else None
        detections.append({
            "class":      label,
            "confidence": round(conf, 2),
            "track_id":   track_id,
            "box":        {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        })

    return JSONResponse(content=detections)


# ── START ─────────────────────────────────────────────────
if __name__ == "__main__":
    # Use "0.0.0.0" to allow connections from other devices on the same network (e.g., mobile)
    host = "0.0.0.0" 
    port = 8000
    print(f"\n{'='*40}")
    print(f"  Local access: http://192.168.100.34:8000")
    print(f"  InSight API  →  http://{host}:{port}")
    print(f"  Local access: http://127.0.0.1:{port}")
    print(f"{'='*40}\n")
    uvicorn.run("app:app", host=host, port=port, reload=True)


