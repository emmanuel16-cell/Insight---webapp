"""
worker.py  –  Background worker that consumes RabbitMQ tasks.

Run with: `python worker.py` (ensure RABBITMQ_URL, GMAIL_ADDRESS, GMAIL_PASSWORD set)

This worker listens to the `email` queue and processes `send_email` tasks.
"""

import os
import json
import asyncio
import smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


import aio_pika
import cv2
import numpy as np
from ultralytics import YOLO
load_dotenv()
from auth import get_db, init_db
from facial_features import detect_and_extract_face_embedding, find_matching_student_for_face


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
GMAIL_FROM = os.getenv("GMAIL_ADDRESS", "")
GMAIL_PASS = os.getenv("GMAIL_PASSWORD", "")


def send_email_sync(to_email: str, subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_FROM, GMAIL_PASS)
        s.sendmail(GMAIL_FROM, to_email, msg.as_string())


async def handle_message(message: aio_pika.IncomingMessage):
    async with message.process():
        try:
            body = message.body.decode()
            data = json.loads(body)
            task = data.get("task")
            payload = data.get("payload", {})

            if task == "send_email":
                to_email = payload.get("to_email")
                subject = payload.get("subject")
                html = payload.get("html")
                await asyncio.to_thread(send_email_sync, to_email, subject, html)
                print(f"Email sent to {to_email}")
            else:
                print(f"Unknown task: {task}")
        except Exception as e:
            print(f"Worker error processing message: {e}")
            raise


async def handle_camera_message(message: aio_pika.IncomingMessage):
    async with message.process():
        try:
            headers = message.headers or {}
            cam_id = None
            meta = None
            try:
                if headers.get('cam_id') is not None:
                    cam_id = int(headers.get('cam_id'))
            except Exception:
                cam_id = None

            if headers.get('meta'):
                try:
                    meta = json.loads(headers.get('meta'))
                except Exception:
                    meta = None

            contents = message.body
            # Convert to OpenCV image
            try:
                nparr = np.frombuffer(contents, np.uint8)
                image_cv2 = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception:
                image_cv2 = None

            if image_cv2 is None:
                print("Camera ingest: invalid image payload")
                return

            # Face recognition
            face_embedding, _ = detect_and_extract_face_embedding(contents)
            match = None
            if face_embedding is not None:
                try:
                    match = find_matching_student_for_face(face_embedding)
                except Exception:
                    match = None

            # Uniform/ID detection
            has_uniform = False
            has_id_card = False
            try:
                # Load YOLO model lazily if available
                global _yolo_model
                if '_yolo_model' not in globals():
                    MODEL_PATH = os.path.join(os.path.dirname(__file__), "public", "model", "best.pt")
                    try:
                        _yolo_model = YOLO(MODEL_PATH)
                    except Exception as e:
                        _yolo_model = None
                        print(f"Worker YOLO load error: {e}")

                if '_yolo_model' in globals() and _yolo_model is not None:
                    results = _yolo_model.predict(image_cv2, conf=0.5, verbose=False)
                    for result in results:
                        if result.boxes is not None:
                            for box in result.boxes:
                                class_id = int(box.cls[0])
                                class_name = _yolo_model.names.get(class_id, "unknown").lower()
                                if "uniform" in class_name or "shirt" in class_name:
                                    has_uniform = True
                                if "id" in class_name or "card" in class_name:
                                    has_id_card = True
            except Exception as e:
                print(f"Worker YOLO detection error: {e}")

            # Get gate rules
            rules = {
                "require_uniform": True,
                "require_id_card": True,
                "allow_late": True,
                "min_confidence": 0.75,
            }
            try:
                db = get_db()
                cur = db.cursor(dictionary=True)
                cur.execute("SELECT * FROM gate_rules WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
                r = cur.fetchone()
                cur.close(); db.close()
                if r:
                    rules = dict(r)
            except Exception:
                pass

            status = 'allowed'
            reasons = []
            if not match:
                status = 'denied'
                reasons.append('Student not recognized')
            elif match and match.get('confidence', 0.0) < rules.get('min_confidence', 0.75):
                status = 'warning'
                reasons.append(f"Low face confidence: {match.get('confidence', 0.0):.2f}")

            if rules.get('require_uniform') and not has_uniform:
                if status != 'denied':
                    status = 'warning'
                reasons.append('No uniform detected')

            if rules.get('require_id_card') and not has_id_card:
                if status != 'denied':
                    status = 'warning'
                reasons.append('No ID card detected')

            # Log to gate_logs — only for recognized students, with dedup by last event/camera
            try:
                if match and match.get('user_id'):
                    db = get_db()
                    cur = db.cursor(dictionary=True)
                    camera_id = cam_id
                    position = None
                    if camera_id:
                        try:
                            cur.execute("SELECT position FROM cameras WHERE id=%s", (camera_id,))
                            crow = cur.fetchone()
                            if crow:
                                position = crow.get('position') if isinstance(crow, dict) else crow[0]
                        except Exception:
                            position = None

                    event_type = 'check_in'
                    if position and str(position).lower().strip() == 'exit':
                        event_type = 'check_out'

                    try:
                        cur.execute(
                            "SELECT id, event_type, camera_id, has_uniform, has_id_card FROM gate_logs WHERE student_id=%s ORDER BY timestamp DESC LIMIT 1",
                            (match['user_id'],)
                        )
                        last = cur.fetchone()
                    except Exception:
                        last = None

                    # Deduplication logic
                    is_duplicate = False
                    if last:
                        if event_type == 'check_in':
                            if last.get('event_type') == 'check_in' and last.get('camera_id') == camera_id:
                                is_duplicate = True
                                last_u = bool(last.get('has_uniform'))
                                last_id = bool(last.get('has_id_card'))
                                if (has_uniform and not last_u) or (has_id_card and not last_id):
                                    is_duplicate = False
                        else:
                            # For exit: ALWAYS allow re-logging to update check-out time
                            is_duplicate = False

                    if not is_duplicate:
                        try:
                            # snapshot profile name at time of detection
                            fname = None
                            lname = None
                            try:
                                cur.execute("SELECT first_name, last_name FROM user_profiles WHERE user_id=%s", (match['user_id'],))
                                pr = cur.fetchone()
                                if pr:
                                    if isinstance(pr, dict):
                                        fname = pr.get('first_name')
                                        lname = pr.get('last_name')
                                    else:
                                        try:
                                            fname = pr[0]
                                            lname = pr[1]
                                        except Exception:
                                            fname = None; lname = None
                            except Exception:
                                pass

                            cur.execute(
                                """
                                INSERT INTO gate_logs
                                (user_id, student_id, camera_id, event_type, method, timestamp, face_confidence, has_uniform, has_id_card, first_name, last_name, overall_status)
                                VALUES (%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s,%s,%s)
                                """,
                                (
                                    match['user_id'],
                                    match['user_id'],
                                    camera_id,
                                    event_type,
                                    'face',
                                    match.get('confidence', 0.0),
                                    int(bool(has_uniform)),
                                    int(bool(has_id_card)),
                                    fname,
                                    lname,
                                    status,
                                )
                            )
                            db.commit()
                            # Removed gate_daily logic - aggregate from gate_logs instead
                            pass
                        except Exception as e:
                            print(f"Worker failed to log gate entry: {e}")
                    cur.close(); db.close()
            except Exception as e:
                print(f"Worker failed to log gate entry: {e}")

            print(f"Camera ingest processed cam={cam_id} status={status} match={bool(match)}")

        except Exception as e:
            print(f"Worker error processing camera message: {e}")
            raise


async def main():
    connection = None

    # Ensure DB tables exist before starting
    try:
        init_db()
        print("DB init complete")
    except Exception as e:
        print(f"DB init failed: {e}")

    # Try to connect with exponential backoff so worker keeps retrying if RabbitMQ isn't ready
    backoff = 2
    while True:
        try:
            print(f"Connecting to RabbitMQ at {RABBITMQ_URL}...")
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            print("Connected to RabbitMQ")
            break
        except Exception as e:
            print(f"RabbitMQ connection failed: {e}")
            print("Ensure RabbitMQ is running (docker run -p 5672:5672 -p 15672:15672 rabbitmq:3-management), or set RABBITMQ_URL in .env")
            print(f"Retrying in {backoff} seconds...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    try:
        channel = await connection.channel()

        exchange = await channel.declare_exchange("insight", aio_pika.ExchangeType.DIRECT, durable=True)
        queue = await channel.declare_queue("email", durable=True)
        await queue.bind(exchange, routing_key="email")

        # Camera ingest queue
        camera_q = await channel.declare_queue("camera_ingest", durable=True)
        await camera_q.bind(exchange, routing_key="camera_ingest")

        await queue.consume(handle_message)
        await camera_q.consume(handle_camera_message)

        print("Worker started, waiting for messages (email + camera_ingest)...")
        await asyncio.Future()  # run forever
    finally:
        if connection:
            try:
                await connection.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Worker stopped")
