import cv2
import mediapipe as mp
import numpy as np

mp_face_detection = mp.solutions.face_detection
mp_face_mesh = mp.solutions.face_mesh

# --------------------------------------------------
# Utility Functions
# --------------------------------------------------

def eye_aspect_ratio(eye_landmarks):
    A = np.linalg.norm(eye_landmarks[1] - eye_landmarks[5])
    B = np.linalg.norm(eye_landmarks[2] - eye_landmarks[4])
    C = np.linalg.norm(eye_landmarks[0] - eye_landmarks[3])
    return (A + B) / (2.0 * C)

# --------------------------------------------------
# Main Face Processing Function
# --------------------------------------------------

def detect_face_crop_liveness(frame, prev_nose=None):
    h, w, _ = frame.shape
    liveness = False

    with mp_face_detection.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.7
    ) as face_detection, mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7
    ):

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        detections = face_detection.process(rgb)

        if not detections.detections:
            return None, False, prev_nose

        detection = detections.detections[0]
        bbox = detection.location_data.relative_bounding_box

        x1 = int(bbox.xmin * w)
        y1 = int(bbox.ymin * h)
        x2 = int((bbox.xmin + bbox.width) * w)
        y2 = int((bbox.ymin + bbox.height) * h)

        face_crop = frame[y1:y2, x1:x2].copy()

        # --- Face Mesh for Liveness ---
        mesh_results = mp_face_mesh.FaceMesh().process(rgb)
        if not mesh_results.multi_face_landmarks:
            return face_crop, False, prev_nose

        landmarks = mesh_results.multi_face_landmarks[0]

        def lm(idx):
            return np.array([
                landmarks.landmark[idx].x * w,
                landmarks.landmark[idx].y * h
            ])

        # Eye landmarks
        left_eye = [33, 160, 158, 133, 153, 144]
        right_eye = [362, 385, 387, 263, 373, 380]

        left_ear = eye_aspect_ratio([lm(i) for i in left_eye])
        right_ear = eye_aspect_ratio([lm(i) for i in right_eye])
        ear = (left_ear + right_ear) / 2

        blink_detected = ear < 0.22

        # Head movement (nose)
        nose = lm(1)
        head_moved = False
        if prev_nose is not None:
            movement = np.linalg.norm(nose - prev_nose)
            head_moved = movement > 3.5

        prev_nose = nose

        if blink_detected or head_moved:
            liveness = True

        return face_crop, liveness, prev_nose


cap = cv2.VideoCapture(0)
prev_nose = None

while True:
    ret, frame = cap.read()
    if not ret:
        break

    face, live, prev_nose = detect_face_crop_liveness(frame, prev_nose)

    if face is not None:
        label = "LIVE ✅" if live else "NOT LIVE ❌"
        cv2.putText(frame, label, (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1,
                    (0, 255, 0) if live else (0, 0, 255), 2)

    cv2.imshow("Face Liveness Detection", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
