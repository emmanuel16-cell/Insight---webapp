import os
import cv2
import numpy as np
import time
import json
import asyncio
import threading
import base64
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form, Response
from pydantic import BaseModel
from typing import List
from auth import get_db, require_session
from facial_features import (
    detect_and_extract_face_embedding, 
    find_matching_student_for_face,
    find_matching_visitor_for_face
)
from qrcode_manager import verify_qr_token
from ultralytics import YOLO
from python.img_encrypt import encrypt_image

# Try to import rabbitmq publisher if available
try:
    import rabbitmq
except ImportError:
    rabbitmq = None

router = APIRouter(prefix="/api/gate")

# Global YOLO model and lock
MODEL_PATH = "public/model/best.pt"
yolo_model = None
yolo_lock = threading.Lock()

try:
    if os.path.exists(MODEL_PATH):
        yolo_model = YOLO(MODEL_PATH)
        print(f"YOLO model loaded for gate security from {MODEL_PATH}")
except Exception as e:
    print(f"Failed to load YOLO model: {e}")

# Camera frame storage and processing queue
ingest_queue = asyncio.Queue(maxsize=100)
PREVIEW_DIR = "public/source/camera-preview"

class CameraManager:
    def __init__(self):
        self.cameras = {} # id -> { 'running': bool, 'thread': Thread, 'latest_frame': bytes, 'last_seen': datetime, 'last_detection': dict }
        self.lock = threading.Lock()

    def start_camera(self, cam_row):
        cam_id = cam_row['id']
        rtsp_url = cam_row.get('rtsp_url')
        if not rtsp_url:
            return False

        with self.lock:
            if cam_id in self.cameras and self.cameras[cam_id]['running']:
                return False
            
            self.cameras[cam_id] = {
                'running': True,
                'latest_frame': None,
                'last_seen': None,
                'last_detection': None,
                'position': cam_row.get('position')
            }

        def _capture_loop(cid, url):
            cap = cv2.VideoCapture(url)
            while True:
                with self.lock:
                    if cid not in self.cameras or not self.cameras[cid]['running']:
                        break
                
                ret, frame = cap.read()
                if not ret:
                    time.sleep(1)
                    cap.open(url)
                    continue
                
                # Resize for efficiency
                frame = cv2.resize(frame, (640, 480))
                _, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()

                with self.lock:
                    self.cameras[cid]['latest_frame'] = frame_bytes
                    self.cameras[cid]['last_seen'] = datetime.utcnow()

                # Every N frames or seconds, enqueue for detection if queue not full
                try:
                    # Simple throttling: only process if queue is mostly empty
                    if ingest_queue.qsize() < 5:
                        item = { 'cam_id': cid, 'image_bytes': frame_bytes, 'meta': None }
                        asyncio.run_coroutine_threadsafe(ingest_queue.put(item), loop)
                except Exception:
                    pass

                time.sleep(0.1)
            cap.release()

        t = threading.Thread(target=_capture_loop, args=(cam_id, rtsp_url), daemon=True)
        t.start()
        return True

    def stop_camera(self, cam_id):
        with self.lock:
            if cam_id in self.cameras:
                self.cameras[cam_id]['running'] = False
                return True
        return False

camera_manager = CameraManager()

def init_gate_db():
    db = get_db()
    cur = db.cursor()
    
    # Gate rules table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gate_rules (
            id INT AUTO_INCREMENT PRIMARY KEY,
            rule_name VARCHAR(100),
            require_uniform BOOLEAN DEFAULT TRUE,
            require_id_card BOOLEAN DEFAULT TRUE,
            allow_late BOOLEAN DEFAULT TRUE,
            min_confidence FLOAT DEFAULT 0.75,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Gate logs table (expanded for AI metadata)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gate_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            student_id INT,
            camera_id INT NULL,
            event_type ENUM('check_in', 'check_out') DEFAULT 'check_in',
            method ENUM('face', 'qr', 'manual') DEFAULT 'face',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            face_confidence FLOAT,
            has_uniform BOOLEAN,
            has_id_card BOOLEAN,
            first_name VARCHAR(100) NULL,
            last_name VARCHAR(100) NULL,
            overall_status ENUM('allowed', 'warning', 'denied', 'visitor') DEFAULT 'allowed'
        )
    """)

    # Cameras table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cameras (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            rtsp_url VARCHAR(500) NULL,
            device_id VARCHAR(100) NULL,
            active BOOLEAN DEFAULT FALSE,
            location VARCHAR(200) NULL,
            position ENUM('entry', 'exit', 'other') DEFAULT 'entry',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Gate activity table (dedicated for entry/exit tracking)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gate_activity (
            id INT AUTO_INCREMENT PRIMARY KEY,
            student_id INT,
            activity_type ENUM('entry', 'exit') NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    db.commit()
    cur.close()
    db.close()

# ── Background Worker for Ingest Queue ──────────────────

def detect_qr_in_image(image_cv2) -> str | None:
    """Detect and decode QR code in image using OpenCV."""
    try:
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(image_cv2)
        return data if data else None
    except Exception as e:
        print(f"QR detection error: {e}")
        return None

async def process_ingest_queue():
    while True:
        item = await ingest_queue.get()
        cam_id = item['cam_id']
        image_bytes = item['image_bytes']
        meta = item['meta']

        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None: continue

            # 1. Try QR detection first (Temporary ID logic)
            qr_data = detect_qr_in_image(img)
            qr_user_id = verify_qr_token(qr_data) if qr_data else None
            
            # 2. Face recognition
            face_encoding, _ = detect_and_extract_face_embedding(image_bytes)
            match = None
            visitor_match = None
            if face_encoding is not None:
                match = find_matching_student_for_face(face_encoding, threshold=0.4)
                if not match:
                    visitor_match = find_matching_visitor_for_face(face_encoding, threshold=0.4)
            
            # Identify person (QR takes precedence for identification if face fails)
            student_id = None
            visitor_id = None
            method = 'face'
            confidence = 0.0
            full_name = "Unknown"
            person_type = 'student' # default

            if qr_user_id:
                student_id = qr_user_id
                method = 'qr'
                confidence = 1.0
                # Get name from DB
                db = get_db(); cur = db.cursor(dictionary=True)
                cur.execute("SELECT first_name, last_name FROM user_profiles WHERE user_id=%s", (qr_user_id,))
                user_row = cur.fetchone()
                cur.close(); db.close()
                if user_row:
                    full_name = f"{user_row['first_name']} {user_row['last_name']}"
            elif match:
                student_id = match['user_id']
                method = 'face'
                confidence = match.get('confidence', 0.0)
                full_name = match.get('full_name', 'Unknown')
            elif visitor_match:
                visitor_id = visitor_match['visitor_id']
                person_type = 'visitor'
                method = 'face'
                confidence = visitor_match.get('confidence', 0.0)
                full_name = visitor_match.get('full_name', 'Unknown')

            if student_id or visitor_id:
                # 3. YOLO detection (with metadata hints)
                has_uniform, has_id_card = False, False
                with yolo_lock:
                    has_uniform, has_id_card = detect_uniform_and_id(img)
                
                # Merge with browser hints
                if meta:
                    if meta.get('has_uniform'): has_uniform = True
                    if meta.get('has_id_card'): has_id_card = True

                # Check for database-issued temporary pass if physical ID is missing
                is_temp_pass = False
                if method == 'qr':
                    is_temp_pass = True
                    has_id_card = True
                
                if student_id and not has_id_card:
                    if has_active_temporary_pass(student_id):
                        has_id_card = True
                        is_temp_pass = True
                        print(f"Verified: {full_name} has an active temporary pass.")

                # Visitors are exempted from uniform/ID rules in this context usually, 
                # but we still log their status.
                
                # 4. Rules & Logging
                rules = get_gate_rules()
                status = "allowed"
                
                if person_type == 'visitor':
                    status = "visitor"
                else:
                    blacklist_entry = is_user_blacklisted(student_id)
                    if blacklist_entry:
                        status = "denied"
                        print(f"🚨 BLACKLIST ALERT: {full_name} detected at gate!")
                    elif not has_classes_today(student_id):
                        status = "visitor"
                        print(f"ℹ️ {full_name} is logged as a Visitor (No classes today).")
                    elif (rules['require_uniform'] and not has_uniform) or (rules['require_id_card'] and not has_id_card):
                        status = "warning"
                    
                    if status != "denied" and method == 'face' and confidence < rules['min_confidence']:
                        status = "warning"

                db = get_db()
                cur = db.cursor(dictionary=True)
                try:
                    # Determine event_type
                    position = None
                    try:
                        cur.execute("SELECT position FROM cameras WHERE id=%s", (cam_id,))
                        crow = cur.fetchone()
                        if crow: position = crow.get('position')
                    except Exception: pass

                    event_type = 'check_in'
                    if position and str(position).lower().strip() == 'exit':
                        event_type = 'check_out'

                    # Deduplication
                    if student_id:
                        cur.execute(
                            "SELECT id, event_type, camera_id, has_uniform, has_id_card, overall_status FROM gate_logs WHERE student_id=%s ORDER BY timestamp DESC LIMIT 1",
                            (student_id,)
                        )
                    elif visitor_id:
                        cur.execute(
                            "SELECT id, event_type, camera_id, has_uniform, has_id_card, overall_status FROM gate_logs WHERE visitor_id=%s ORDER BY timestamp DESC LIMIT 1",
                            (visitor_id,)
                        )
                    else:
                        cur.execute(
                            "SELECT id, event_type, camera_id, has_uniform, has_id_card, overall_status FROM gate_logs WHERE user_id IS NULL AND first_name=%s AND last_name=%s ORDER BY timestamp DESC LIMIT 1",
                            (full_name.split(' ')[0], full_name.split(' ')[1] if ' ' in full_name else '')
                        )
                    
                    last = cur.fetchone()
                    
                    is_duplicate = False
                    if last:
                        if event_type == 'check_in':
                            if last.get('event_type') == 'check_in' and last.get('camera_id') == cam_id:
                                is_duplicate = True
                                # If they now have uniform/ID but didn't before, log it anyway (to update status)
                                if (has_uniform and not last.get('has_uniform')) or (has_id_card and not last.get('has_id_card')):
                                    is_duplicate = False
                        else:
                            # For check_out, deduplicate if last event was also check_out within last 5 mins
                            if last.get('event_type') == 'check_out' and last.get('camera_id') == cam_id:
                                is_duplicate = True

                    if not is_duplicate:
                        image_url = save_encrypted_log_image(img, folder="logs", prefix="gate")
                        
                        first_name = full_name.split(' ')[0]
                        last_name = full_name.split(' ')[1] if ' ' in full_name else ''
                        
                        cur.execute(
                            """
                            INSERT INTO gate_logs
                            (user_id, student_id, visitor_id, camera_id, event_type, method, timestamp, face_confidence, has_uniform, has_id_card, overall_status, image_url, first_name, last_name)
                            VALUES (%s,%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (student_id, student_id, visitor_id, cam_id, event_type, method, confidence, int(bool(has_uniform)), int(bool(has_id_card)), status, image_url, first_name, last_name)
                        )
                        log_id = cur.lastrowid
                        
                        cur.execute(
                            "INSERT INTO gate_activity (student_id, visitor_id, activity_type, timestamp) VALUES (%s, %s, %s, NOW())",
                            (student_id, visitor_id, 'entry' if event_type == 'check_in' else 'exit')
                        )
                        db.commit()

                        if student_id and (status == "warning" or (not has_uniform or not has_id_card)):
                            match_data = {'user_id': student_id, 'full_name': full_name}
                            report_uniform_violation_auto(student_id, match_data, has_uniform, has_id_card, log_id)

                    cur.close(); db.close()
                except Exception as e:
                    print(f"Error logging ingest result: {e}")

                # Update camera state
                if cam_id in camera_manager.cameras:
                    with camera_manager.lock:
                        camera_manager.cameras[cam_id]['last_detection'] = {
                            'student_id': student_id,
                            'visitor_id': visitor_id,
                            'full_name': full_name,
                            'confidence': confidence,
                            'has_uniform': has_uniform,
                            'has_id_card': has_id_card,
                            'status': status,
                            'is_temp_pass': is_temp_pass,
                            'method': method,
                            'timestamp': datetime.utcnow().isoformat()
                        }
        except Exception as e:
            print(f"Error in ingest background worker: {e}")
        finally:
            ingest_queue.task_done()

# Start the background worker
loop = asyncio.get_event_loop()
threading.Thread(target=lambda: loop.run_until_complete(process_ingest_queue()), daemon=True).start()

# ── Models ────────────────────────────────────────────────

class GateRuleRequest(BaseModel):
    rule_name: str
    require_uniform: bool = True
    require_id_card: bool = True
    allow_late: bool = True
    min_confidence: float = 0.75

# ── Detection Functions ──────────────────────────────────

def is_user_blacklisted(user_id: int) -> dict | None:
    if not user_id: return None
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM blacklist WHERE user_id=%s AND status='active' LIMIT 1",
        (user_id,)
    )
    row = cur.fetchone()
    cur.close(); db.close()
    return row

def has_active_temporary_pass(user_id: int) -> bool:
    if not user_id: return False
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id FROM temporary_passes WHERE user_id=%s AND status='active' AND expires_at > NOW() LIMIT 1",
        (user_id,)
    )
    row = cur.fetchone()
    cur.close(); db.close()
    return row is not None

def has_classes_today(user_id: int) -> bool:
    """Checks if a student has any classes today based on schedules and subject_enrollments."""
    if not user_id: return False
    
    # Get today's day of week
    today_name = datetime.now().strftime('%A')
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    # First get student_id (the string one)
    cur.execute("SELECT student_id FROM user_profiles WHERE user_id=%s", (user_id,))
    prof = cur.fetchone()
    if not prof:
        cur.close(); db.close()
        return False
    
    stu_code = prof['student_id']
    
    # Check if any enrolled subject has a schedule for today
    cur.execute("""
        SELECT s.id 
        FROM schedules s
        JOIN subjects sub ON s.subject_id = sub.id
        JOIN subject_enrollments e ON sub.join_code = e.enroll_code
        WHERE e.student_id = %s AND e.status = 'enrolled' AND s.day_of_week = %s
        LIMIT 1
    """, (stu_code, today_name))
    
    row = cur.fetchone()
    
    # Fallback: if no schedules are defined yet, check if they are enrolled in any subject
    # This ensures we don't accidentally mark everyone as visitors if schedules aren't set up.
    if not row:
        cur.execute("""
            SELECT id FROM schedules LIMIT 1
        """)
        any_schedules = cur.fetchone()
        
        if not any_schedules:
            # No schedules in system yet, fallback to enrollment check
            cur.execute("""
                SELECT id FROM subject_enrollments WHERE student_id = %s AND status = 'enrolled' LIMIT 1
            """, (stu_code,))
            row = cur.fetchone()
    
    cur.close(); db.close()
    return row is not None

def report_uniform_violation_auto(user_id: int, match_data: dict, has_uniform: bool, has_id_card: bool, gate_log_id: int = None):
    if not user_id: return
    
    violation_type = None
    if not has_uniform and not has_id_card:
        violation_type = "Missing Uniform & ID Card"
    elif not has_uniform:
        violation_type = "Missing Uniform"
    elif not has_id_card:
        violation_type = "Missing ID Card"
        
    if not violation_type:
        return

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO uniform_violations (user_id, student_id, first_name, last_name, violation_type, description, gate_log_id, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')",
            (
                user_id, 
                match_data.get('student_id'), 
                match_data.get('first_name'), 
                match_data.get('last_name'), 
                violation_type, 
                f"Automatic detection via gate camera.",
                gate_log_id
            )
        )
        db.commit()
    except Exception as e:
        print(f"Error reporting auto violation: {e}")
    finally:
        cur.close(); db.close()

def detect_uniform_and_id(image_cv2) -> tuple[bool, bool]:
    if yolo_model is None: return False, False
    try:
        results = yolo_model.predict(image_cv2, conf=0.5, verbose=False)
        has_uniform, has_id_card = False, False
        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = yolo_model.names.get(class_id, "unknown").lower()
                    
                    # LOGGING: Print detections to console for debugging
                    print(f"YOLO Detection: {class_name} (conf: {float(box.conf[0]):.2f})")
                    
                    if "uniform" in class_name or "shirt" in class_name: 
                        has_uniform = True
                    if "id" in class_name or "card" in class_name: 
                        has_id_card = True
                        
        return has_uniform, has_id_card
    except Exception as e:
        print(f"Error in uniform detection: {e}")
        return False, False

def get_gate_rules() -> dict:
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM gate_rules WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
    rule = cur.fetchone()
    cur.close(); db.close()
    if not rule:
        return {"require_uniform": True, "require_id_card": True, "allow_late": True, "min_confidence": 0.75}
    return dict(rule)

def save_encrypted_log_image(image_cv2, folder="logs", prefix="log") -> str | None:
    """Encodes image to JPG, encrypts it, and saves it to public/logs/"""
    try:
        success, buffer = cv2.imencode('.jpg', image_cv2)
        if not success: return None
        
        encrypted_data = encrypt_image(buffer.tobytes())
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}_{timestamp}.jpg.enc"
        
        save_path = os.path.join("public", folder, filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        with open(save_path, "wb") as f:
            f.write(encrypted_data)
            
        return f"/{folder}/{filename}"
    except Exception as e:
        print(f"Error saving encrypted image: {e}")
        return None

def log_gate_entry(student_id, face_confidence, has_uniform, has_id_card, overall_status, cam_id=None, method='face', image_cv2=None):
    if not student_id: return False
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        image_url = None
        if image_cv2 is not None:
            image_url = save_encrypted_log_image(image_cv2, folder="logs", prefix="gate")

        position = None
        if cam_id:
            cur.execute("SELECT position FROM cameras WHERE id=%s", (cam_id,))
            crow = cur.fetchone()
            if crow: position = crow.get('position') if isinstance(crow, dict) else crow[0]
        
        event_type = 'check_out' if position and str(position).lower().strip() == 'exit' else 'check_in'
        
        cur.execute("SELECT id, event_type, camera_id, has_uniform, has_id_card, overall_status FROM gate_logs WHERE student_id=%s ORDER BY timestamp DESC LIMIT 1", (student_id,))
        last = cur.fetchone()
        
        # Deduplication logic
        is_duplicate = False
        if last:
            if event_type == 'check_in':
                if last.get('event_type') == 'check_in' and last.get('camera_id') == cam_id:
                    is_duplicate = True
                    last_u = bool(last.get('has_uniform'))
                    last_id = bool(last.get('has_id_card'))
                    if (has_uniform and not last_u) or (has_id_card and not last_id):
                        is_duplicate = False
            else:
                # For exit: ALWAYS allow re-logging to update check-out time
                is_duplicate = False

        if is_duplicate:
            cur.close(); db.close(); return False

        cur.execute("""
            INSERT INTO gate_logs (user_id, student_id, camera_id, event_type, method, timestamp, face_confidence, has_uniform, has_id_card, overall_status, image_url)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
        """, (student_id, student_id, cam_id, event_type, method, face_confidence, int(bool(has_uniform)), int(bool(has_id_card)), overall_status, image_url))
        
        # Also log to gate_activity
        activity_type = 'entry' if event_type == 'check_in' else 'exit'
        cur.execute(
            "INSERT INTO gate_activity (student_id, activity_type, timestamp) VALUES (%s, %s, NOW())",
            (student_id, activity_type)
        )
        
        db.commit()

        cur.close(); db.close()
        return True
    except Exception as e:
        print(f"Error logging gate entry: {e}")
        cur.close(); db.close(); return False

# ── Routes ────────────────────────────────────────────────

def find_matching_visitor_for_face(encoding, threshold=0.4):
    """
    Search for a matching visitor face encoding in the database.
    """
    if encoding is None: return None
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    # Only match visitors who checked in within the last 24 hours or have no time_out
    cur.execute("SELECT id, first_name, last_name, face_encoding FROM visitors WHERE face_encoding IS NOT NULL AND (time_out IS NULL OR time_in > DATE_SUB(NOW(), INTERVAL 1 DAY))")
    visitors = cur.fetchall()
    cur.close(); db.close()

    best_match = None
    min_dist = 1.0
    
    for v in visitors:
        if v['face_encoding']:
            v_enc = np.frombuffer(v['face_encoding'], dtype=np.float32)
            dist = 1 - np.dot(encoding, v_enc) # Simple cosine distance for unit vectors
            if dist < threshold and dist < min_dist:
                min_dist = dist
                best_match = {
                    'visitor_id': v['id'],
                    'full_name': f"{v['first_name']} {v['last_name']}",
                    'confidence': 1 - dist
                }
                
    return best_match

@router.post("/check-entry")
async def check_gate_entry(file: UploadFile = File(...), request: Request = None):
    if request:
        session = require_session(request)
        if session.get("role") not in ["admin", "instructor"]:
            raise HTTPException(403, "Forbidden")

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    image_cv2 = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image_cv2 is None: raise HTTPException(400, "Invalid image")

    # 1. Try QR detection (Temporary ID logic)
    qr_data = detect_qr_in_image(image_cv2)
    qr_user_id = verify_qr_token(qr_data) if qr_data else None

    # 2. Face recognition
    face_encoding, _ = detect_and_extract_face_embedding(contents)
    match = None
    visitor_match = None
    if face_encoding is not None:
        match = find_matching_student_for_face(face_encoding, threshold=0.4)
        if not match:
            visitor_match = find_matching_visitor_for_face(face_encoding, threshold=0.4)
    
    # Identify person
    student_id = None
    visitor_id = None
    person_type = 'student'
    method = 'face'
    confidence = 0.0
    full_name = "Unknown"
    student_id_num = "—"

    if qr_user_id:
        student_id = qr_user_id
        method = 'qr'
        confidence = 1.0
        db = get_db(); cur = db.cursor(dictionary=True)
        cur.execute("SELECT first_name, last_name, student_id FROM user_profiles WHERE user_id=%s", (qr_user_id,))
        user_row = cur.fetchone()
        cur.close(); db.close()
        if user_row:
            full_name = f"{user_row['first_name']} {user_row['last_name']}"
            student_id_num = user_row['student_id']
    elif match:
        student_id = match['user_id']
        method = 'face'
        confidence = match.get('confidence', 0.0)
        full_name = match.get('full_name', 'Unknown')
        student_id_num = match.get('student_id', '—')
    elif visitor_match:
        visitor_id = visitor_match['visitor_id']
        person_type = 'visitor'
        method = 'face'
        confidence = visitor_match.get('confidence', 0.0)
        full_name = visitor_match.get('full_name', 'Unknown')
        student_id_num = "VISITOR"

    with yolo_lock:
        has_uniform, has_id_card = detect_uniform_and_id(image_cv2)

    # QR acts as temporary ID
    if method == 'qr':
        has_id_card = True

    # Check for database-issued temporary pass if physical ID is missing
    if student_id and not has_id_card:
        if has_active_temporary_pass(student_id):
            has_id_card = True
            print(f"Verified: {full_name} has an active temporary pass.")

    rules = get_gate_rules()
    status = "allowed"
    reasons = []
    
    if not student_id and not visitor_id:
        status = "denied"
        reasons.append("Not recognized")
    elif person_type == 'visitor':
        status = "visitor"
        reasons.append("Registered Visitor")
    else:
        blacklist_entry = is_user_blacklisted(student_id)
        if blacklist_entry:
            status = "denied"
            reasons.append(f"Blacklisted: {blacklist_entry.get('reason', 'No reason provided')}")
        elif not has_classes_today(student_id):
            status = "visitor"
            reasons.append("No classes today")
        else:
            if method == 'face' and confidence < rules["min_confidence"]: 
                status = "warning"
                reasons.append("Low confidence")
            if rules["require_uniform"] and not has_uniform: 
                status = "warning"
                reasons.append("No uniform")
            if rules["require_id_card"] and not has_id_card: 
                status = "warning"
                reasons.append("No ID card")

    if student_id or visitor_id:
        # Log
        log_id = None
        db = get_db(); cur = db.cursor()
        try:
            image_url = save_encrypted_log_image(image_cv2, folder="logs", prefix="gate")
            
            f_name = full_name.split(' ')[0]
            l_name = full_name.split(' ')[1] if ' ' in full_name else ''
            
            cur.execute(
                """
                INSERT INTO gate_logs 
                (user_id, student_id, visitor_id, method, face_confidence, has_uniform, has_id_card, overall_status, image_url, first_name, last_name) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (student_id, student_id, visitor_id, method, confidence, int(has_uniform), int(has_id_card), status, image_url, f_name, l_name)
            )
            db.commit()
            log_id = cur.lastrowid
            
            if student_id or visitor_id:
                # Log to gate_activity
                cur.execute(
                    "INSERT INTO gate_activity (student_id, visitor_id, activity_type, timestamp) VALUES (%s, %s, 'entry', NOW())",
                    (student_id, visitor_id)
                )
                db.commit()

            # Auto-report violation if needed
            if student_id and status == "warning":
                report_uniform_violation_auto(student_id, {
                    "student_id": student_id,
                    "first_name": f_name,
                    "last_name": l_name,
                    "student_id_num": student_id_num
                }, has_uniform, has_id_card, log_id)
                
        except Exception as e:
            print(f"Log error: {e}")
        finally:
            cur.close(); db.close()

        # Get daily status for students
        checked_in = False
        daily_u = has_uniform
        daily_id = has_id_card
        
        if student_id:
            db = get_db()
            cur = db.cursor(dictionary=True)
            try:
                cur.execute("""
                    SELECT 
                        MAX(CASE WHEN event_type = 'check_in' THEN 1 ELSE 0 END) as checked_in,
                        MAX(has_uniform) as daily_u,
                        MAX(has_id_card) as daily_id
                    FROM gate_logs 
                    WHERE student_id=%s AND DATE(timestamp)=CURDATE()
                """, (student_id,))
                row = cur.fetchone()
                if row:
                    checked_in = bool(row.get('checked_in'))
                    daily_u = bool(row.get('daily_u'))
                    daily_id = bool(row.get('daily_id'))
            except Exception: pass
            finally: cur.close(); db.close()

        return {
            "match": True,
            "student_id": student_id, 
            "full_name": full_name, 
            "student_id_num": student_id_num, 
            "face_confidence": confidence, 
            "has_uniform": has_uniform, 
            "has_id_card": has_id_card, 
            "checked_in_today": checked_in, 
            "daily_uniform": daily_u, 
            "daily_id_card": daily_id, 
            "overall_status": status, 
            "method": method, 
            "message": "; ".join(reasons) if reasons else "Allowed",
            "person_type": person_type
        }
    return {"overall_status": "denied", "message": "Person not recognized"}

@router.get("/logs")
async def get_gate_logs(request: Request, limit: int = 100):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT gl.*, u.email, p.first_name, p.last_name, p.student_id
        FROM gate_logs gl
        LEFT JOIN users u ON u.id = gl.student_id
        LEFT JOIN user_profiles p ON p.user_id = u.id
        WHERE gl.event_type IN ('check_in', 'check_out')
        ORDER BY gl.timestamp DESC LIMIT %s
    """, (limit,))
    logs = cur.fetchall()
    cur.close(); db.close()
    for row in logs:
        if row.get("timestamp"):
            row["timestamp"] = row["timestamp"].isoformat()
    return {"total_logs": len(logs), "logs": [dict(log) for log in logs]}


@router.get("/in-out-logs")
async def get_in_out_logs(request: Request, limit: int = 100):
    session = require_session(request)
    if session.get("role") not in ["admin", "instructor"]:
        raise HTTPException(403, "Forbidden")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        """
        SELECT
            ga.id,
            ga.student_id,
            ga.visitor_id,
            ga.activity_type,
            ga.timestamp,
            up.student_id AS student_code,
            up.first_name,
            up.last_name,
            v.first_name AS visitor_first_name,
            v.last_name AS visitor_last_name
        FROM gate_activity ga
        LEFT JOIN user_profiles up ON up.user_id = ga.student_id
        LEFT JOIN visitors v ON v.id = ga.visitor_id
        ORDER BY ga.timestamp DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    cur.close()
    db.close()

    for row in rows:
        if row.get("timestamp"):
            row["timestamp"] = row["timestamp"].isoformat()
        if row.get("student_id"):
            full = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
            row["full_name"] = full or f"Student #{row['student_id']}"
        elif row.get("visitor_id"):
            vfull = f"{row.get('visitor_first_name') or ''} {row.get('visitor_last_name') or ''}".strip()
            row["full_name"] = vfull or f"Visitor #{row['visitor_id']}"
        else:
            row["full_name"] = "Unknown"

    return {"total_logs": len(rows), "logs": rows}


@router.get("/blacklist-alerts")
async def get_blacklist_alerts(request: Request, limit: int = 20, since_id: int = 0):
    session = require_session(request)
    if session.get("role") not in ["admin", "instructor"]:
        raise HTTPException(403, "Forbidden")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        """
        SELECT
            gl.id,
            gl.student_id,
            gl.camera_id,
            gl.timestamp,
            gl.overall_status,
            gl.image_url,
            gl.first_name,
            gl.last_name,
            up.student_id AS student_code,
            up.avatar_url,
            b.reason AS blacklist_reason,
            b.severity AS blacklist_severity
        FROM gate_logs gl
        INNER JOIN blacklist b ON b.user_id = gl.student_id AND b.status = 'active'
        LEFT JOIN user_profiles up ON up.user_id = gl.student_id
        WHERE gl.overall_status = 'denied' AND gl.id > %s
        ORDER BY gl.id DESC
        LIMIT %s
        """,
        (since_id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    db.close()

    for row in rows:
        if row.get("timestamp"):
            row["timestamp"] = row["timestamp"].isoformat()
        full = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        row["full_name"] = full or f"Student #{row.get('student_id', '—')}"
        cam_id = row.get("camera_id")
        row["snapshot_url"] = f"/api/gate/cameras/{cam_id}/snapshot?ts={int(time.time() * 1000)}" if cam_id else None

    return {"alerts": rows}

@router.post("/set-rules")
async def set_gate_rules_api(body: GateRuleRequest, request: Request):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    db = get_db(); cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO gate_rules (rule_name, require_uniform, require_id_card, allow_late, min_confidence, active)
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (body.rule_name, body.require_uniform, body.require_id_card, body.allow_late, body.min_confidence))
        db.commit(); cur.close(); db.close()
        return {"message": "Rules updated", "rules": body.dict()}
    except Exception as e:
        cur.close(); db.close(); raise HTTPException(400, str(e))

@router.get("/rules")
async def get_gate_rules_endpoint():
    return {"rules": get_gate_rules()}

# Camera APIs
class CameraCreateRequest(BaseModel):
    name: str
    rtsp_url: str | None = None
    device_id: str | None = None
    location: str | None = None
    position: str | None = None
    active: bool = False

@router.get("/cameras")
async def list_cameras(request: Request):
    session = require_session(request)
    if session.get("role") not in ["admin", "instructor"]: raise HTTPException(403, "Forbidden")
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM cameras ORDER BY id")
    rows = cur.fetchall()
    cur.close(); db.close()
    return {"cameras": [dict(r) for r in rows]}

@router.post("/cameras")
async def create_camera(body: CameraCreateRequest, request: Request):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    db = get_db(); cur = db.cursor()
    cur.execute("INSERT INTO cameras (name, rtsp_url, device_id, active, location, position) VALUES (%s,%s,%s,%s,%s,%s)",
                (body.name, body.rtsp_url, body.device_id, int(body.active), body.location, body.position))
    db.commit(); cam_id = cur.lastrowid
    cur.close(); db.close()
    if body.active and body.rtsp_url:
        db2 = get_db(); cur2 = db2.cursor(dictionary=True)
        cur2.execute("SELECT * FROM cameras WHERE id=%s", (cam_id,))
        row = cur2.fetchone()
        cur2.close(); db2.close()
        if row: camera_manager.start_camera(row)
    return {"id": cam_id, "message": "Created"}


@router.post("/cameras/{cam_id}/preview")
async def upload_camera_preview(cam_id: int, file: UploadFile = File(...), request: Request = None):
    session = require_session(request)
    if session.get("role") != "admin":
        raise HTTPException(403, "Forbidden")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM cameras WHERE id=%s", (cam_id,))
    row = cur.fetchone()
    cur.close()
    db.close()
    if not row:
        raise HTTPException(404, "Camera not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty preview upload")

    try:
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Invalid image bytes")
        ok, encoded = cv2.imencode(".png", img)
        if not ok:
            raise ValueError("Image encode failed")
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        preview_path = os.path.join(PREVIEW_DIR, f"{cam_id}.png")
        with open(preview_path, "wb") as f:
            f.write(encoded.tobytes())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Failed to process preview: {exc}")

    return {"message": "Preview updated"}

@router.post("/cameras/{cam_id}/start")
async def api_start_camera(cam_id: int, request: Request):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM cameras WHERE id=%s", (cam_id,))
    row = cur.fetchone()
    cur.close(); db.close()
    if not row: raise HTTPException(404, "Not found")
    camera_manager.start_camera(row)
    db2 = get_db(); cur2 = db2.cursor(); cur2.execute("UPDATE cameras SET active=1 WHERE id=%s", (cam_id,)); db2.commit(); cur2.close(); db2.close()
    return {"message": "Started"}

@router.post("/cameras/{cam_id}/stop")
async def api_stop_camera(cam_id: int, request: Request):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    camera_manager.stop_camera(cam_id)
    db = get_db(); cur = db.cursor(); cur.execute("UPDATE cameras SET active=0 WHERE id=%s", (cam_id,)); db.commit(); cur.close(); db.close()
    return {"message": "Stopped"}

@router.post("/cameras/{cam_id}/client-start")
async def api_client_start_camera(cam_id: int, request: Request):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    db = get_db(); cur = db.cursor(); cur.execute("UPDATE cameras SET active=1 WHERE id=%s", (cam_id,)); db.commit(); cur.close(); db.close()
    return {"message": "Active"}

@router.post("/cameras/{cam_id}/client-stop")
async def api_client_stop_camera(cam_id: int, request: Request):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    db = get_db(); cur = db.cursor(); cur.execute("UPDATE cameras SET active=0 WHERE id=%s", (cam_id,)); db.commit(); cur.close(); db.close()
    return {"message": "Inactive"}

@router.get("/cameras/{cam_id}/snapshot")
async def camera_snapshot(cam_id: int, request: Request):
    session = require_session(request)
    entry = camera_manager.cameras.get(cam_id)
    if not entry or not entry.get('latest_frame'): raise HTTPException(404, "No snapshot")
    return Response(content=entry['latest_frame'], media_type='image/jpeg')

@router.get("/cameras/{cam_id}/last")
async def camera_last_detection(cam_id: int, request: Request):
    session = require_session(request)
    entry = camera_manager.cameras.get(cam_id)
    if not entry: return {"running": False, "last_detection": None}
    det = entry.get('last_detection')
    if det and det.get('student_id'):
        db = get_db()
        cur = db.cursor(dictionary=True)
        try:
            # Aggregate today's status from gate_logs directly
            cur.execute("""
                SELECT 
                    MAX(CASE WHEN event_type = 'check_in' THEN 1 ELSE 0 END) as checked_in,
                    MAX(CASE WHEN event_type = 'check_out' THEN 1 ELSE 0 END) as checked_out,
                    MAX(has_uniform) as daily_u,
                    MAX(has_id_card) as daily_id
                FROM gate_logs 
                WHERE student_id=%s AND DATE(timestamp)=CURDATE()
            """, (det['student_id'],))
            daily = cur.fetchone()
            if daily:
                det['checked_in_today'] = bool(daily.get('checked_in'))
                det['checked_out_today'] = bool(daily.get('checked_out'))
                det['daily_uniform'] = bool(daily.get('daily_u'))
                det['daily_id_card'] = bool(daily.get('daily_id'))
            else:
                det['checked_in_today'] = False
                det['checked_out_today'] = False
                det['daily_uniform'] = False
                det['daily_id_card'] = False
        except Exception:
            pass
        finally:
            cur.close(); db.close()
    return {"running": bool(entry.get('running')), "last_detection": det}

@router.post("/cameras/{cam_id}/ingest")
async def ingest_camera_frame(cam_id: int, file: UploadFile = File(...), meta: str = Form(None), request: Request = None):
    session = require_session(request)
    contents = await file.read()
    item = {'cam_id': cam_id, 'image_bytes': contents, 'meta': json.loads(meta) if meta else None}
    if rabbitmq:
        try:
            await rabbitmq.publish_camera_ingest_async(cam_id, contents, item['meta'])
            return {"queued": True}
        except Exception: pass
    await ingest_queue.put(item)
    return {"queued": True}

@router.delete("/cameras/{cam_id}")
async def delete_camera(cam_id: int, request: Request):
    session = require_session(request)
    if session.get("role") != "admin": raise HTTPException(403, "Forbidden")
    camera_manager.stop_camera(cam_id)
    db = get_db(); cur = db.cursor(); cur.execute("DELETE FROM cameras WHERE id=%s", (cam_id,)); db.commit(); cur.close(); db.close()
    with camera_manager.lock:
        if cam_id in camera_manager.cameras: del camera_manager.cameras[cam_id]
    return {"message": "Deleted"}
