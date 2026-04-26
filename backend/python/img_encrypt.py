import os
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# ---- LOAD KEY FROM ENV ----
IMG_ENCRYPT_KEY = os.getenv("IMG_ENCRYPT_KEY")

if not IMG_ENCRYPT_KEY:
    raise Exception("❌ Missing IMG_ENCRYPT_KEY in environment variables")

ENC_KEY = base64.b64decode(IMG_ENCRYPT_KEY)

if len(ENC_KEY) != 32:
    raise Exception("❌ IMG_ENCRYPT_KEY must decode to 32 bytes (base64 of 32 random bytes)")

IV_LENGTH = 12
AUTH_TAG_LENGTH = 16


# ---- ENCRYPT FUNCTION ----
# Returns bytes structured as:
# [IV (12 bytes)] [AUTH_TAG (16 bytes)] [CIPHERTEXT...]
def encrypt_image(buffer: bytes) -> bytes:
    if not isinstance(buffer, (bytes, bytearray)):
        raise TypeError("encrypt_image expects bytes")

    iv = os.urandom(IV_LENGTH)

    encryptor = Cipher(
        algorithms.AES(ENC_KEY),
        modes.GCM(iv),
        backend=default_backend()
    ).encryptor()

    ciphertext = encryptor.update(buffer) + encryptor.finalize()
    auth_tag = encryptor.tag

    return iv + auth_tag + ciphertext


# ---- DECRYPT FUNCTION ----
def decrypt_image(encrypted_buffer: bytes) -> bytes:
    if not isinstance(encrypted_buffer, (bytes, bytearray)):
        raise TypeError("decrypt_image expects bytes")

    if len(encrypted_buffer) < IV_LENGTH + AUTH_TAG_LENGTH + 1:
        raise Exception("Invalid encrypted buffer: too short")

    iv = encrypted_buffer[:IV_LENGTH]
    auth_tag = encrypted_buffer[IV_LENGTH:IV_LENGTH + AUTH_TAG_LENGTH]
    data = encrypted_buffer[IV_LENGTH + AUTH_TAG_LENGTH:]

    decryptor = Cipher(
        algorithms.AES(ENC_KEY),
        modes.GCM(iv, auth_tag),
        backend=default_backend()
    ).decryptor()

    decrypted = decryptor.update(data) + decryptor.finalize()
    return decrypted