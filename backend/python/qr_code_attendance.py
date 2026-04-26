"""
qr_code_attendance.py - QR code generation for session attendance
Generates unique QR codes for sessions
"""

import base64
import io
import json
import qrcode
from typing import Tuple

def generate_session_qr(session_id: int, subject_id: int, session_code: str = None) -> Tuple[str, bytes]:
    """
    Generate QR code for a class session.
    
    Format: INSIGHT:SESSION:{session_id}:SUBJECT:{subject_id}:CODE:{session_code}
    
    Args:
        session_id: ID of the session
        subject_id: ID of the subject
        session_code: Optional unique code for session
    
    Returns:
        Tuple: (base64_encoded_qr, raw_bytes)
    """
    session_code = session_code or f"S{session_id}"
    qr_data = f"INSIGHT:SESSION:{session_id}:SUBJECT:{subject_id}:CODE:{session_code}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    raw_bytes = img_bytes.getvalue()
    
    # Convert to base64
    base64_img = base64.b64encode(raw_bytes).decode('utf-8')
    
    return base64_img, raw_bytes


def parse_session_qr(qr_data: str) -> dict:
    """Parse session QR code data."""
    parts = qr_data.split(':')
    if len(parts) >= 6 and parts[0] == 'INSIGHT' and parts[1] == 'SESSION':
        return {
            'type': 'session',
            'session_id': int(parts[2]),
            'subject_id': int(parts[4]),
            'code': parts[6] if len(parts) > 6 else None
        }
    return None
