"""
facial_features.py  –  Facial Feature Extraction & Storage (OpenCV + InsightFace)
Captures facial embeddings when students upload profile photos.
Uses OpenCV for face detection and InsightFace (MobileFaceNet) for feature extraction.

"""

import os
import cv2
import numpy as np
from io import BytesIO
import base64
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel
from dotenv import load_dotenv
import threading

from auth import get_db, require_session

load_dotenv()

router = APIRouter(prefix="/api/facial")

# ── InsightFace Model Loading ──────────────────────────────────────────

# Load InsightFace model globally (lazy loading - loads on first use)
_face_analyser = None
_face_lock = threading.Lock()

def get_face_analyser():
    """Get or initialize InsightFace analyser from local model directory."""
    global _face_analyser
    if _face_analyser is None:
        try:
            import insightface
            
            # Load model from local directory: \public\model\buffalo_sc
            model_path = os.path.join(os.path.dirname(__file__), "public", "model")
            
            _face_analyser = insightface.app.FaceAnalysis(
                name='buffalo_sc',
                root=model_path,  # Use local model directory
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            _face_analyser.prepare(ctx_id=-1, det_size=(640, 640))
            print("✅ InsightFace model (buffalo_sc - MobileFaceNet) loaded from local directory")
        except Exception as e:
            print(f"⚠️  InsightFace model error: {e}")
            _face_analyser = None
    return _face_analyser


# ── Database setup ────────────────────────────────────────

def init_facial_db():
    """Create facial features table if not exists, with schema migration support."""
    db = get_db()
    cur = db.cursor()
    
    try:
        # Create table with full schema
        cur.execute("""
            CREATE TABLE IF NOT EXISTS facial_features (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                user_id         INT UNIQUE NOT NULL,
                face_id         VARCHAR(50),
                face_encoding   LONGBLOB NOT NULL,
                embedding_dim   INT DEFAULT 512,
                profile_photo_path VARCHAR(255),
                is_verified     TINYINT(1) NOT NULL DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        db.commit()
    except Exception as e:
        print(f"Info: Table may already exist: {e}")
    
    # Add missing columns if they don't exist (schema migration)
    try:
        cur.execute("ALTER TABLE facial_features ADD COLUMN face_id VARCHAR(50) UNIQUE")
        print("✅ Added face_id column to facial_features table")
    except Exception as e:
        if "Duplicate column" in str(e) or "already exists" in str(e):
            print("ℹ️  face_id column already exists")
        else:
            print(f"⚠️  Error adding face_id: {e}")
    
    try:
        cur.execute("ALTER TABLE facial_features ADD COLUMN profile_photo_path VARCHAR(255)")
        print("✅ Added profile_photo_path column to facial_features table")
    except Exception as e:
        if "Duplicate column" in str(e) or "already exists" in str(e):
            print("ℹ️  profile_photo_path column already exists")
        else:
            print(f"⚠️  Error adding profile_photo_path: {e}")
    
    db.commit()
    cur.close()
    db.close()


# ── Models ────────────────────────────────────────────────

class FacialFeatureResponse(BaseModel):
    user_id: int
    is_verified: bool
    embedding_dim: int


# ── Face Detection & Recognition Functions ────────────────────────────

def detect_and_extract_face_embedding(image_bytes: bytes) -> tuple[np.ndarray, bytes] | tuple[None, None]:
    """
    Detect face in image, crop it to a square with padding, and extract 512-dim embedding.
    
    Args:
        image_bytes: Raw image bytes (JPG/PNG)
    
    Returns:
        (embedding, cropped_image_bytes) or (None, None) if no face detected
    """
    try:
        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            print("Error: Could not decode image")
            return None, None

        # Get face analyser
        analyser = get_face_analyser()
        if analyser is None:
            print("Error: InsightFace model not available")
            return None, None

        # Detect faces (thread-safe access to analyser)
        with _face_lock:
            faces = analyser.get(image)

        if not faces or len(faces) == 0:
            print("No faces detected in image")
            return None, None

        # Process first (primary) face
        face = faces[0]
        embedding = face.embedding
        bbox = face.bbox.astype(int)  # [x1, y1, x2, y2]

        # ── Square Crop with Padding ──────────────────────────────
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        
        # Calculate center
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        
        # Determine square size (use larger dimension + padding)
        # Padding is 30% of the face size
        padding = int(max(w, h) * 0.3)
        size = max(w, h) + padding * 2
        
        # Calculate square bounds
        nx1 = max(0, cx - size // 2)
        ny1 = max(0, cy - size // 2)
        nx2 = min(image.shape[1], nx1 + size)
        ny2 = min(image.shape[0], ny1 + size)
        
        # Adjust if hitting boundaries to keep it square
        if nx2 - nx1 < size:
            nx1 = max(0, nx2 - size)
        if ny2 - ny1 < size:
            ny1 = max(0, ny2 - size)

        cropped_face = image[ny1:ny2, nx1:nx2]
        
        # Encode cropped face back to bytes
        _, buffer = cv2.imencode('.jpg', cropped_face)
        cropped_bytes = buffer.tobytes()

        return embedding, cropped_bytes

    except Exception as e:
        print(f"Error in face detection/embedding: {e}")
        return None, None


def get_face_bounding_box(image_bytes: bytes) -> tuple | None:
    """
    Get bounding box of detected face for debugging/visualization.
    
    Returns:
        (x1, y1, x2, y2) or None if no face detected
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            return None

        analyser = get_face_analyser()
        if analyser is None:
            return None

        with _face_lock:
            faces = analyser.get(image)
        if not faces:
            return None

        # Get bounding box from first face
        bbox = faces[0].bbox
        return (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))

    except Exception as e:
        print(f"Error getting face bbox: {e}")
        return None

# ── Storage & Retrieval Functions ──────────────────────────────────────

def create_profile_photos_dir():
    """Ensure profile photos directory exists."""
    profile_dir = os.path.join(os.path.dirname(__file__), "public", "profile_photos")
    os.makedirs(profile_dir, exist_ok=True)
    return profile_dir


def save_profile_photo(user_id: int, image_bytes: bytes) -> str | None:
    """
    Save profile photo to disk with unique filename.
    
    Args:
        user_id: Student user ID
        image_bytes: Raw image bytes
    
    Returns:
        Path to saved photo relative to public folder
    """
    try:
        profile_dir = create_profile_photos_dir()
        
        # Create filename: user_id_timestamp.jpg
        import time
        timestamp = int(time.time())
        filename = f"user_{user_id}_{timestamp}.jpg"
        filepath = os.path.join(profile_dir, filename)
        
        # Save image
        with open(filepath, 'wb') as f:
            f.write(image_bytes)
        
        # Return relative path for storage
        relative_path = f"profile_photos/{filename}"
        return relative_path
    except Exception as e:
        print(f"Error saving profile photo: {e}")
        return None


def generate_face_id(user_id: int, timestamp: int) -> str:
    """Generate unique face ID for registered biometrics."""
    return f"FACE_{user_id}_{timestamp}"


def store_facial_features(user_id: int, face_embedding: np.ndarray, profile_photo_path: str = None) -> str | None:
    """
    Store facial embedding in database with profile photo path.
    
    Args:
        user_id: Student user ID
        face_embedding: 512-dim numpy array from InsightFace
        profile_photo_path: Path to saved profile photo
    
    Returns:
        face_id if successful, None otherwise
    """
    db = get_db()
    cur = db.cursor()

    # Serialize numpy array to bytes
    embedding_bytes = face_embedding.tobytes()
    embedding_dim = len(face_embedding)
    
    # Generate face_id
    import time
    timestamp = int(time.time())
    face_id = generate_face_id(user_id, timestamp)

    try:
        cur.execute("""
            INSERT INTO facial_features (user_id, face_id, face_encoding, embedding_dim, profile_photo_path, is_verified)
            VALUES (%s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                face_id = VALUES(face_id),
                face_encoding = VALUES(face_encoding),
                embedding_dim = VALUES(embedding_dim),
                profile_photo_path = VALUES(profile_photo_path),
                is_verified = 1,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, face_id, embedding_bytes, embedding_dim, profile_photo_path))

        # ── Synchronize with user_profiles.avatar_url ──────────────────
        if profile_photo_path:
            # Construct the full public URL for the avatar
            avatar_url = f"/public/{profile_photo_path}"
            cur.execute(
                "UPDATE user_profiles SET avatar_url = %s WHERE user_id = %s",
                (avatar_url, user_id)
            )

        db.commit()
        cur.close()
        db.close()
        return face_id
    except Exception as e:
        print(f"Error storing facial features: {e}")
        cur.close()
        db.close()
        return None


def get_facial_features(user_id: int) -> dict | None:
    """
    Retrieve facial features from database.
    
    Args:
        user_id: Student user ID
    
    Returns:
        Dict with embeddings and metadata or None if not found
    """
    db = get_db()
    cur = db.cursor(dictionary=True)

    try:
        cur.execute(
            "SELECT face_id, face_encoding, embedding_dim, profile_photo_path FROM facial_features WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        cur.close()
        db.close()

        if not row or not row["face_encoding"]:
            return None

        # Deserialize bytes to numpy array
        embedding_dim = row["embedding_dim"]
        embedding = np.frombuffer(row["face_encoding"], dtype=np.float32).reshape(embedding_dim)
        
        return {
            "embedding": embedding,
            "face_id": row["face_id"],
            "profile_photo_path": row["profile_photo_path"],
            "embedding_dim": embedding_dim
        }

    except Exception as e:
        print(f"Error retrieving facial features: {e}")
        cur.close()
        db.close()
        return None

# ── Face Comparison & Matching Functions ───────────────────────────────

def compare_faces(embedding1: np.ndarray, embedding2: np.ndarray, threshold=0.4) -> float:
    """
    Compare two face embeddings using cosine similarity.
    
    Args:
        embedding1: First 512-dim embedding
        embedding2: Second 512-dim embedding
        threshold: Similarity threshold (0.4 typical for InsightFace)
    
    Returns:
        Similarity score (0-1). Higher is more similar.
    """
    try:
        # Normalize embeddings
        emb1_norm = embedding1 / np.linalg.norm(embedding1)
        emb2_norm = embedding2 / np.linalg.norm(embedding2)
        
        # Cosine similarity
        similarity = np.dot(emb1_norm, emb2_norm) / (
            np.linalg.norm(emb1_norm) * np.linalg.norm(emb2_norm) + 1e-6
        )
        
        return float(similarity)
    except Exception as e:
        print(f"Error comparing faces: {e}")
        return 0.0


def find_matching_student_for_face(face_embedding: np.ndarray, threshold=0.4) -> dict | None:
    """
    Find student whose facial features match given embedding (InsightFace).
    Uses cosine similarity for comparison.
    
    Args:
        face_embedding: 512-dim embedding from camera/upload
        threshold: Similarity threshold (0.4 = ~97% match)
    
    Returns:
        Student info dict or None if no match
    """
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)

        cur.execute(
            "SELECT ff.user_id, ff.face_encoding, ff.embedding_dim, u.email, "
            "       p.first_name, p.last_name, p.student_id "
            "FROM facial_features ff "
            "JOIN users u ON u.id = ff.user_id "
            "LEFT JOIN user_profiles p ON p.user_id = u.id "
            "WHERE ff.is_verified = 1"
        )
        rows = cur.fetchall()
        cur.close()
        db.close()

        best_match = None
        best_similarity = 0.0

        for row in rows:
            # Deserialize stored embedding
            stored_embedding = np.frombuffer(
                row["face_encoding"], 
                dtype=np.float32
            ).reshape(row["embedding_dim"])
            
            # Compare
            similarity = compare_faces(face_embedding, stored_embedding)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = row

        # Return match if similarity exceeds threshold
        if best_match and best_similarity >= threshold:
            return {
                "user_id": best_match["user_id"],
                "email": best_match["email"],
                "full_name": (
                    f"{best_match['first_name']} {best_match['last_name']}"
                    if best_match['first_name'] else "Unknown"
                ),
                "student_id": best_match["student_id"],
                "confidence": best_similarity,  # 0.4-1.0
            }

        return None

    except Exception as e:
        print(f"Error finding matching student: {e}")
        return None


def find_matching_visitor_for_face(face_embedding: np.ndarray, threshold=0.4) -> dict | None:
    """
    Find visitor whose facial features match given embedding.
    Uses cosine similarity for comparison.
    
    Args:
        face_embedding: 512-dim embedding from camera/upload
        threshold: Similarity threshold (0.4 typical for InsightFace)
    
    Returns:
        Visitor info dict or None if no match
    """
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)

        # Only check visitors who haven't timed out yet (or within last 24h)
        cur.execute(
            "SELECT id, first_name, last_name, face_encoding "
            "FROM visitors "
            "WHERE face_encoding IS NOT NULL AND (time_out IS NULL OR time_in > DATE_SUB(NOW(), INTERVAL 24 HOUR))"
        )
        rows = cur.fetchall()
        cur.close()
        db.close()

        best_match = None
        best_similarity = 0.0

        for row in rows:
            # Deserialize stored embedding
            # Note: We assume visitor embeddings are also 512-dim (MobileFaceNet)
            stored_embedding = np.frombuffer(
                row["face_encoding"], 
                dtype=np.float32
            )
            
            # Reshape if necessary (should be 512)
            if len(stored_embedding) != 512:
                continue
                
            # Compare
            similarity = compare_faces(face_embedding, stored_embedding)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = row

        # Return match if similarity exceeds threshold
        if best_match and best_similarity >= threshold:
            return {
                "visitor_id": best_match["id"],
                "full_name": f"{best_match['first_name']} {best_match['last_name']}",
                "confidence": best_similarity,
                "type": "visitor"
            }

        return None

    except Exception as e:
        print(f"Error finding matching visitor: {e}")
        return None

# ── Routes ────────────────────────────────────────────────────────────

@router.post("/upload-profile-photo")
async def upload_profile_photo(file: UploadFile = File(...), request: Request = None):
    """
    Upload student profile photo for facial feature extraction.
    Saves profile photo to disk and extracts 512-dim facial embedding.
    Returns face_id for registered biometrics.
    """
    if request:
        session = require_session(request)
        user_id = session["user_id"]
        if session.get("role") != "student":
            raise HTTPException(403, "Only students can upload profile photos")
    else:
        raise HTTPException(401, "Authentication required")

    # Read file bytes
    contents = await file.read()

    # Detect face and extract embedding
    face_embedding, cropped_face_bytes = detect_and_extract_face_embedding(contents)
    if face_embedding is None:
        raise HTTPException(
            400,
            "No face detected in image. Please upload a clear, frontal photo of your face."
        )

    # Save cropped profile photo to disk (not original)
    profile_photo_path = save_profile_photo(user_id, cropped_face_bytes)
    if not profile_photo_path:
        raise HTTPException(500, "Failed to save profile photo")

    # Store facial embedding and get face_id
    face_id = store_facial_features(user_id, face_embedding, profile_photo_path)
    if not face_id:
        raise HTTPException(500, "Failed to store facial features")

    return {
        "message": "Profile photo saved and facial features extracted successfully",
        "user_id": user_id,
        "face_id": face_id,
        "profile_photo_path": profile_photo_path,
        "embedding_dim": 512,
        "is_verified": True,
    }


@router.get("/my-facial-status")
async def get_facial_status(request: Request):
    """Check if student has facial features stored with face_id."""
    session = require_session(request)
    user_id = session["user_id"]

    db = get_db()
    cur = db.cursor(dictionary=True)

    try:
        cur.execute(
            "SELECT user_id, face_id, is_verified, embedding_dim FROM facial_features WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        cur.close()
        db.close()

        if not row:
            return {
                "user_id": user_id,
                "has_facial_features": False,
                "is_verified": False,
                "face_id": None,
                "embedding_dim": 0,
            }

        return {
            "user_id": user_id,
            "has_facial_features": True,
            "is_verified": bool(row["is_verified"]),
            "face_id": row["face_id"],
            "embedding_dim": row["embedding_dim"],
        }
    except Exception as e:
        print(f"Error getting facial status: {e}")
        return {
            "user_id": user_id,
            "has_facial_features": False,
            "is_verified": False,
            "face_id": None,
            "embedding_dim": 0,
        }


@router.post("/recognize")
async def recognize_face(file: UploadFile = File(...), subject_id: int | None = Form(None)):
    """
    Identify student from facial image (for gate/instructor).
    Uses InsightFace MobileFaceNet embedding matching.
    
    Returns matching student info if found.
    """
    contents = await file.read()

    # Extract face embedding
    face_embedding, _ = detect_and_extract_face_embedding(contents)
    if face_embedding is None:
        raise HTTPException(400, "No face detected in image")

    # Find matching student. If subject_id provided, limit to enrolled students for that subject.
    match = None
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        if subject_id is not None:
            # Get join_code for subject
            cur.execute("SELECT join_code FROM subjects WHERE id=%s", (subject_id,))
            s_row = cur.fetchone()
            if not s_row:
                cur.close(); db.close()
                raise HTTPException(404, "Subject not found")
            enroll_code = s_row['join_code']

            # Select only facial features for students enrolled in this subject
            cur.execute(
                "SELECT ff.user_id, ff.face_encoding, ff.embedding_dim, u.email, "
                "       p.first_name, p.last_name, p.student_id "
                "FROM facial_features ff "
                "JOIN users u ON u.id = ff.user_id "
                "LEFT JOIN user_profiles p ON p.user_id = u.id "
                "JOIN subject_enrollments e ON e.student_id = p.student_id AND e.status='enrolled' "
                "WHERE ff.is_verified = 1 AND e.enroll_code=%s",
                (enroll_code,)
            )
            rows = cur.fetchall()
            cur.close(); db.close()

            # Compare against provided rows
            best_match = None
            best_similarity = 0.0
            if rows:
                import numpy as np
                for row in rows:
                    stored_embedding = np.frombuffer(row["face_encoding"], dtype=np.float32).reshape(row["embedding_dim"])
                    similarity = compare_faces(face_embedding, stored_embedding)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = row
                if best_match and best_similarity >= 0.4:
                    match = {
                        "user_id": best_match["user_id"],
                        "email": best_match.get("email"),
                        "full_name": (f"{best_match.get('first_name','')} {best_match.get('last_name','')}".strip() or "Unknown"),
                        "student_id": best_match.get("student_id"),
                        "confidence": best_similarity,
                    }
                else:
                    match = None
        else:
            # No subject filter — use existing helper
            match = find_matching_student_for_face(face_embedding)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during recognition lookup: {e}")
        match = None
    if not match:
        return {
            "found": False,
            "message": "No matching student found",
        }

    return {
        "found": True,
        "user_id": match["user_id"],
        "name": match["full_name"],
        "email": match["email"],
        "student_id": match["student_id"],
        "confidence": match["confidence"],
    }


@router.delete("/delete-facial-data")
async def delete_facial_data(request: Request):
    """Delete facial features for account deletion/privacy."""
    session = require_session(request)
    user_id = session["user_id"]

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("DELETE FROM facial_features WHERE user_id = %s", (user_id,))
        db.commit()
        cur.close()
        db.close()

        return {"message": "Facial features deleted"}
    except Exception as e:
        print(f"Error deleting facial data: {e}")
        cur.close()
        db.close()
        raise HTTPException(500, "Failed to delete facial features")


# ── Debugging Route (Optional) ────────────────────────────────────────

@router.post("/debug-face-detection")
async def debug_face_detection(file: UploadFile = File(...)):
    """
    Debug endpoint: Returns face bounding box, detection info, and cropped face image.
    Useful for testing the square cropping and padding logic.
    """
    contents = await file.read()

    # Get bounding box and embedding
    embedding, cropped_bytes = detect_and_extract_face_embedding(contents)

    if embedding is None:
        return {
            "detected": False,
            "message": "No face detected in image",
        }

    # Get raw bounding box for debug info
    analyser = get_face_analyser()
    nparr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    with _face_lock:
        faces = analyser.get(image)
    face = faces[0]
    bbox = face.bbox.astype(int)
    
    x1, y1, x2, y2 = bbox
    face_width = x2 - x1
    face_height = y2 - y1
    img_h, img_w = image.shape[:2]

    # Convert cropped bytes to base64 for preview
    import base64
    cropped_base64 = base64.b64encode(cropped_bytes).decode('utf-8')

    return {
        "detected": True,
        "bounding_box": {
            "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
            "width": int(face_width), "height": int(face_height),
        },
        "image_dimensions": { "width": img_w, "height": img_h },
        "face_coverage_percentage": round((face_width * face_height) / (img_w * img_h) * 100, 2),
        "recommendation": (
            "Good" if face_width > 100 and face_height > 100
            else "Image too small - increase face size"
        ),
        "cropped_face_base64": cropped_base64,
        "embedding_sample": embedding.tolist()[:10]  # Return first 10 values as sample
    }


# ── Biometrics Endpoints ─────────────────────────────────────────

@router.get("/biometrics/{user_id}")
async def get_biometrics(user_id: int, request: Request):
    """
    Get student's registered biometrics (face_id, photo path, verification status).
    """
    session = require_session(request)
    
    # Only allow viewing own biometrics or admin viewing any
    if session.get("role") != "admin" and session["user_id"] != user_id:
        raise HTTPException(403, "Cannot view other users' biometrics")
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    try:
        cur.execute(
            "SELECT face_id, profile_photo_path, is_verified, created_at, updated_at "
            "FROM facial_features WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        cur.close()
        db.close()
        
        if not row:
            raise HTTPException(404, "No biometrics registered for this user")
        
        return {
            "user_id": user_id,
            "face_id": row["face_id"],
            "profile_photo_path": row["profile_photo_path"],
            "is_verified": bool(row["is_verified"]),
            "registered_at": str(row["created_at"]),
            "last_updated": str(row["updated_at"]),
        }
    except Exception as e:
        print(f"Error retrieving biometrics: {e}")
        raise HTTPException(500, f"Error: {str(e)}")


@router.get("/profile-photo/{user_id}")
async def get_profile_photo(user_id: int, request: Request):
    """
    Get student's profile photo (biometric photo).
    Returns file download.
    """
    session = require_session(request)
    
    # Only allow viewing own photo or admin viewing any
    if session.get("role") != "admin" and session["user_id"] != user_id:
        raise HTTPException(403, "Cannot view other users' photos")
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    try:
        cur.execute(
            "SELECT profile_photo_path FROM facial_features WHERE user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        cur.close()
        db.close()
        
        if not row or not row["profile_photo_path"]:
            raise HTTPException(404, "No profile photo found")
        
        # Build file path
        photo_path = row["profile_photo_path"]
        full_path = os.path.join(
            os.path.dirname(__file__),
            "public",
            photo_path
        )
        
        # Check if file exists
        if not os.path.exists(full_path):
            raise HTTPException(404, "Profile photo file not found")
        
        # Return file
        from fastapi.responses import FileResponse
        return FileResponse(full_path, media_type="image/jpeg")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving profile photo: {e}")
        raise HTTPException(500, f"Error: {str(e)}")
