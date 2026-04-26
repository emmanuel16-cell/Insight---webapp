"""
python/text_encrypt.py
Place this file at: python/text_encrypt.py
(Renamed from text_encrypt.py so Python can import it directly.)

AES-GCM encryption/decryption for user data dicts.
Requires TXT_ENCRYPT_KEY env var (base64-encoded 32-byte key).
"""

import os
import json
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_B64 = os.getenv("TXT_ENCRYPT_KEY")
if not KEY_B64:
    raise Exception("Missing TXT_ENCRYPT_KEY environment variable")

KEY = base64.b64decode(KEY_B64)
if len(KEY) != 32:
    raise Exception("TXT_ENCRYPT_KEY must decode to 32 bytes")

aesgcm = AESGCM(KEY)


def encrypt_user_data(user_dict: dict) -> bytes:
    if not isinstance(user_dict, dict):
        raise TypeError("Expected dictionary")
    nonce     = os.urandom(12)
    data      = json.dumps(user_dict).encode()
    encrypted = aesgcm.encrypt(nonce, data, None)
    return nonce + encrypted


def decrypt_user_data(encrypted_blob: bytes) -> dict:
    nonce      = encrypted_blob[:12]
    ciphertext = encrypted_blob[12:]
    decrypted  = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(decrypted.decode())