"""Sirius API client — JWE envelope (RSA-OAEP-256 + A256GCM) reverse-engineered from the app.

Request envelope (compact JWE, RFC 7516):
  protected header = {"alg":"RSA-OAEP-256","enc":"A256GCM","typ":"newera-request+jwe","kid":"kex"}
  plaintext payload = {"v":1,"requestId":..,"method":..,"path":..,"query":..,"replyKey":b64url(16B),"body":<dto|null>}
  cek = 32 random bytes, iv = 12 random bytes, AAD = ASCII of the protected header b64
Endpoints are POST with body = the compact JWE, Content-Type: application/jose.
"""

import base64
import json
import os
import time
import uuid

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = "https://api.siriussrt.com"
UA = "okhttp/5.3.2"

# The API sets an `sl-session` cookie (Spring-session style) on every response.
# The registration flow is session-scoped, so cookies must persist across calls.
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

# RSA public key baked into the app (only the public half — used to encrypt the CEK).
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAxi0JLtTAK/6i5VXt85BG
R9ekx26sJhNSSzR+j6P3AP5Gz8RggSZ4vGrrUkncFc1FFvuBTZOv1oZ0p7cEglAR
m+Fm6zXMxl8zUlL0A3Axu0P4AqFzg4kMjgEgB0AOTOBB5q5JAe10f6w/8nMrMsfv
7/xF3u94GItZNmVsuHGcX+JcN+WaOtTWGQV5QkvSOKHsrUnQYr8ZKmRgoZ8gTF/I
I8nbsj6bm+0z5xLbtcFHht/R6SXXnmQPKd82r8q4kD4s51qNcmMcyfY3l7Ldf0zr
8AnZMxEnXUosl/E8gVqp+6FQ4pIkbKG91OIhi/312qYeV5VtMKTfSJSgd8BZwUlH
MPA346BjDleOron2XIurOy4YFPUPY9X32kqos3FdZ8mIWDZueBcG3U66lb4Aq1lW
7SAMaObQTmyifxfBO5pY6ox6G/KfUFdg2hJJcZDR8wqoHf2OxA2L8X0qhJOHlL2p
/1heJVbPPLEbkDgTlYJbDMcVXmytta7ZY8nLy1pR8OVxAgMBAAE=
-----END PUBLIC KEY-----"""

_pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def seal(method: str, path: str, body=None, query: str = "") -> tuple[str, str]:
    """Returns (compact_jwe, reply_key_b64).

    replyKey MUST be 32 bytes: the server answers with alg:"dir" A256GCM
    and decrypts the response envelope with exactly this key.
    """
    reply_key = os.urandom(32)
    header = {"alg": "RSA-OAEP-256", "enc": "A256GCM",
              "typ": "newera-request+jwe", "kid": "kex"}
    payload = {
        "v": 1,
        "requestId": str(uuid.uuid4()),
        "method": method.upper(),
        "path": path,
        "query": query,
        "replyKey": b64u(reply_key),
        "body": body,
    }
    hdr = json.dumps(header, separators=(",", ":")).encode()
    hdr_b64 = b64u(hdr)
    plain = json.dumps(payload, separators=(",", ":")).encode()

    cek = os.urandom(32)
    iv = os.urandom(12)
    ct_tag = AESGCM(cek).encrypt(iv, plain, hdr_b64.encode())  # ct || 16B tag
    ct, tag = ct_tag[:-16], ct_tag[-16:]

    ek = _pub.encrypt(cek, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                        algorithm=hashes.SHA256(), label=None))
    jwe = ".".join([hdr_b64, b64u(ek), b64u(iv), b64u(ct), b64u(tag)])
    return jwe, b64u(reply_key)


def open_envelope(text: str, reply_key: bytes):
    """Try to decrypt a response envelope. Returns dict or None."""
    parts = text.strip().split(".")
    if len(parts) != 5:
        return None
    hdr, ek, iv, ct, tag = parts
    ct_tag = unb64u(ct) + unb64u(tag)
    for key in (reply_key, __import__("hashlib").sha256(reply_key).digest()):
        for aad in (hdr.encode(), b""):
            try:
                plain = AESGCM(key).decrypt(unb64u(iv), ct_tag, aad)
                return json.loads(plain)
            except Exception:
                continue
    return None


def call(method: str, path: str, body=None, token: str = None,
         idempotency: str = None, query: str = "", extra_headers=None, timeout=30,
         turnstile: str = None):
    jwe, reply_key = seal(method, path, body, query)
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, application/jose, */*",
        "Accept-Encoding": "gzip",
    }
    data = None
    if method.upper() in ("GET", "DELETE"):
        # GET/DELETE carry no business body -> envelope rides in the header
        # and Content-Type must NOT be application/jose (the server then
        # insists on reading the body instead and fails).
        headers["X-Api-Envelope"] = jwe
    else:
        headers["Content-Type"] = "application/jose"
        data = jwe.encode()
    if token:
        headers["Authorization"] = "Bearer " + token
    if turnstile:
        headers["X-Turnstile-Token"] = turnstile
    if idempotency:
        headers["Idempotency-Key"] = idempotency
    if extra_headers:
        headers.update(extra_headers)

    url = BASE + path + (("?" + query) if query else "")
    r = SESSION.request(method, url, data=data, headers=headers, timeout=timeout)
    ct = r.headers.get("Content-Type", "")
    raw = r.text
    out = {"status": r.status_code, "content_type": ct}
    if "jose" in ct or (raw.count(".") >= 4 and "eyJ" in raw[:8]):
        dec = open_envelope(raw.strip(), unb64u(reply_key))
        out["payload"] = dec
        if isinstance(dec, dict) and "status" in dec:
            out["status"] = dec["status"]
        out["body"] = dec if dec is not None else raw[:400]
        out["raw"] = raw[:400]
    else:
        try:
            out["body"] = r.json()
        except Exception:
            out["body"] = raw[:600]
    return out
