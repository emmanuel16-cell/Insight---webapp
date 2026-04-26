

# AGENTS.md

This file provides the structural and logic guidance for development, maintenance, and AI-assisted coding within the **InSight** repository.

## 1. Project Overview
**InSight** is a high-speed, integrated AI gate security and multi-subject attendance system. It automates the verification of identity, school attire, and scheduling using a FastAPI backend and a vanilla frontend.

### Core Philosophy
- **Security First:** Immediate identification of blacklisted individuals.
- **Speed:** Automatic verification of temporary passes if physical IDs are missing.
- **Compliance:** Automated reporting on problematic uniform concerns.
- **Privacy:** AES-GCM encryption for all sensitive text and image data.

---

## 2. Detailed System Flow
The system processes every entry through a multi-stage pipeline:

1.  **Detection (MediaPipe):** Scans the camera stream for face landmarks and crops the face for recognition.
2.  **Identity (InsightFace):** Generates a 512-dim embedding.
    *   **Blacklist Check:** If a match is found in the `blacklist` table, a high-priority notification is sent to the Security Staff UI.
    *   **Enrollment Check:** Determines if the person is a student or staff.
3.  **Schedule Check (Logic Gate):**
    *   Checks the `subjects` and `schedules` tables.
    *   If a student is enrolled but has no classes today, they are logged as a **"Visitor"**.
4.  **Compliance Scan (YOLO):** Scans the full-body image for two specific classes: `school_uniform` and `physical_id_card`.
5.  **ID Fallback Logic:**
    *   If YOLO detects a **physical ID**: Access verified.
    *   If YOLO **fails** to detect a physical ID: The system immediately queries the `temporary_passes` database to see if the Admin has issued a digital pass.
    *   If no pass is found: Logged as a "Missing ID" violation.
6.  **Data Logging:** Stores a face crop, a full-body violation frame (if applicable), and a timestamped record.
    *   *Note: Physical gate hardware (opening/closing) and 3D Prototypes are planned for Future Phases.*

---

## 3. UI Functionalities by User Role

### **Admin Dashboard**
- **User Management:** Onboard students/instructors and manage face enrollments.
- **Blacklist:** Add/remove restricted individuals.
- **Temporary Pass Issuance:** Issue digital passes to students who lost their physical IDs (automatically verified by the gate).
- **Reporting:** Generate specific "Problematic Uniform Concern" reports and attendance analytics.

### **Security Staff UI**
- **Live Feed:** Real-time stream with bounding boxes (Green=Pass, Yellow=Temp Pass, Red=Violation/Blacklist).
- **Alerts:** Instant push notifications for blacklisted entries.
- **Visitor Logs:** Review and verify general visitor check-ins.

### **Instructor Portal**
- **Attendance Tracking:** View real-time gate-in logs for students enrolled in their subjects.
- **Compliance View:** See which students in their section are entering without proper attire.

### **Student Portal**
- **Personal Records:** View personal attendance history and uniform violation logs.
- **Digital Pass:** View the status/QR of their Admin-issued temporary pass.

### **Visitor Interface (Kiosk)**
- **Registration:** Enter name, purpose, and capture a temporary face image for tracking.

---

## 4. Technical Architecture

### **Stack**
- **Backend:** FastAPI (Python 3.11/3.12)
- **Database:** MySQL (Raw `mysql-connector-python`)
- **AI Models:**
    - `InsightFace (buffalo_sc)`: 512-dim face embeddings.
    - `YOLO (best.pt)`: Uniform and ID card detection.
    - `MediaPipe`: Browser-side face detection via WASM.
- **Frontend:** Vanilla HTML/JS/CSS (No build tools).

### **Module Responsibility**
| File | Responsibility |
|---|---|
| `gate_security.py` | Implementation of the recognition + YOLO + ID fallback logic. |
| `admin.py` | Management of subjects, enrollments, and uniform reports. |
| `auth.py` | Role-based sessions, OTP, and encryption logic. |
| `facial_features.py` | Embedding generation and similarity matching (threshold 0.4). |
| `qrcode_manager.py` | QR generation for temporary IDs. |

### **Environment Variables (`.env`)**
```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=yourpassword
DB_NAME=insight_db
TXT_ENCRYPT_KEY=base64_32_byte_key
IMG_ENCRYPT_KEY=base64_32_byte_key
GMAIL_ADDRESS=example@gmail.com
GMAIL_PASSWORD=app_password
```

---

## 5. Commands

### Setup
```powershell
# Create and activate venv
python -m venv .venv
.venv\Scripts\activate.ps1

# Install requirements
pip install -r requirements.txt

# Create Admin account
python create_admin.py
```

### Execution
```powershell
# Start FastAPI Server
python app.py

# Start Background Worker (Emails/Async Tasks)
python worker.py
```

---

## 6. Key Constraints for Development
- **Database:** No ORM allowed. All tables must use `CREATE TABLE IF NOT EXISTS` inside `init_db()` functions.
- **Images:** All log images must be encrypted using `python/img_encrypt.py` before being stored in `public/logs/`.
- **Latency:** The ID fallback check must happen in sub-200ms to ensure the gate flow remains "Fast-Pass."
- **Attendance Logic:** Attendance is derived; it is NOT a separate check-in. It is calculated by comparing `gate_logs` timestamps against `schedules`.