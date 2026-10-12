"""Server-side AlienEdge accounts and opaque sessions."""
from __future__ import annotations
import base64, hashlib, hmac, os, secrets, sqlite3, time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("AUTH_DB_PATH", str(ROOT / "data" / "auth.sqlite3")))
SESSION_COOKIE = os.getenv("SESSION_COOKIE_NAME", "alienedge_session")
SESSION_TTL_SECONDS = max(300, int(os.getenv("SESSION_TTL_SECONDS", "604800")))
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 64
class AuthError(Exception): pass
class InvalidCredentials(AuthError): pass
class EmailAlreadyRegistered(AuthError): pass
@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    try: yield conn
    finally: conn.close()
def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,created_at INTEGER NOT NULL,disabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(user_id),created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
        CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT PRIMARY KEY,window_start INTEGER NOT NULL,request_count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS password_resets (token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(user_id),created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,used_at INTEGER);
        CREATE INDEX IF NOT EXISTS password_resets_user_idx ON password_resets(user_id);
        """)
    try: os.chmod(DB_PATH, 0o600)
    except OSError: pass
def _b64(raw: bytes) -> str: return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
def _unb64(value: str) -> bytes: return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12: raise ValueError("Password must be at least 12 characters.")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(derived)}"
def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = encoded.split("$", 5)
        if scheme != "scrypt": return False
        expected = _unb64(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt_b64), n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError): return False
def _normalize_email(email: str) -> str: return str(email or "").strip().lower()
def create_user(email: str, password: str) -> dict:
    init_db(); normalized = _normalize_email(email)
    if "@" not in normalized or len(normalized) > 254: raise ValueError("Enter a valid email address.")
    user_id, now = f"usr_{secrets.token_urlsafe(18)}", int(time.time())
    try:
        with _db() as conn:
            conn.execute("INSERT INTO users(user_id,email,password_hash,created_at) VALUES(?,?,?,?)", (user_id, normalized, hash_password(password), now))
    except sqlite3.IntegrityError as exc: raise EmailAlreadyRegistered() from exc
    return {"user_id": user_id, "email": normalized, "created_at": now}
def authenticate(email: str, password: str) -> dict:
    init_db()
    with _db() as conn: row = conn.execute("SELECT user_id,email,password_hash,created_at,disabled FROM users WHERE email=?", (_normalize_email(email),)).fetchone()
    if row is None or row["disabled"] or not verify_password(password, row["password_hash"]): raise InvalidCredentials()
    return {"user_id": row["user_id"], "email": row["email"], "created_at": row["created_at"]}
def _token_hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()
def create_session(user_id: str) -> str:
    init_db(); token, now = secrets.token_urlsafe(48), int(time.time())
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)", (_token_hash(token), user_id, now, now + SESSION_TTL_SECONDS))
    return token
def get_user_for_session(token: str | None) -> dict | None:
    if not token: return None
    init_db()
    with _db() as conn: row = conn.execute("SELECT u.user_id,u.email,u.created_at,s.expires_at FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0", (_token_hash(token), int(time.time()))).fetchone()
    return None if row is None else {"user_id": row["user_id"], "email": row["email"], "created_at": row["created_at"]}
def revoke_session(token: str | None) -> None:
    if token:
        init_db()
        with _db() as conn: conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
RESET_TOKEN_TTL_SECONDS = 3600  # 1 hour — short enough to limit exposure

# ── PASSWORD RESET (2026-10-12) ────────────────────────────────────────────
# Single-use, expiring, hashed-at-rest tokens. Only the SHA-256 of the token
# is stored, so a database leak cannot be replayed into a password change.
# A successful reset revokes EVERY session for that user: whoever asked for
# the reset is presumed to be the only person who should still be logged in.
def create_password_reset(email: str) -> str | None:
    """Issue a reset token for the account with this email. Returns the raw
    token (store it nowhere but the email), or None when no such account —
    the CALLER must treat both outcomes identically so the endpoint never
    reveals whether an email is registered."""
    init_db()
    normalized = _normalize_email(email)
    with _db() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE email=? AND disabled=0", (normalized,)).fetchone()
        if row is None:
            return None
        token, now = secrets.token_urlsafe(32), int(time.time())
        conn.execute("DELETE FROM password_resets WHERE user_id=?", (row["user_id"],))
        conn.execute("INSERT INTO password_resets(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                     (_token_hash(token), row["user_id"], now, now + RESET_TOKEN_TTL_SECONDS))
        return token


def consume_password_reset(token: str) -> str | None:
    """Validate a reset token and burn it. Returns the user_id on success,
    None when the token is unknown, expired, or already used. Burning
    happens in the same statement that validates, so a token can never be
    used twice — not even by two simultaneous requests."""
    if not token:
        return None
    init_db()
    now = int(time.time())
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT user_id FROM password_resets WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
                           (_token_hash(token), now)).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute("UPDATE password_resets SET used_at=? WHERE token_hash=?", (now, _token_hash(token)))
        conn.execute("COMMIT")
        return row["user_id"]


def set_password(user_id: str, password: str) -> None:
    """Replace the password hash and revoke every existing session for the
    user — a reset means every other device is presumed compromised."""
    init_db()
    new_hash = hash_password(password)  # raises ValueError if too short
    with _db() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE user_id=?", (new_hash, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def check_rate_limit(bucket: str, limit: int, window_seconds: int) -> bool:
    init_db(); now, key = int(time.time()), hashlib.sha256(bucket.encode()).hexdigest(); start = now - now % max(1, window_seconds)
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE"); row = conn.execute("SELECT window_start,request_count FROM rate_limits WHERE bucket=?", (key,)).fetchone()
        if row is None or row["window_start"] != start:
            conn.execute("INSERT INTO rate_limits(bucket,window_start,request_count) VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET window_start=excluded.window_start,request_count=1", (key, start)); allowed = True
        else:
            allowed = int(row["request_count"]) < limit
            if allowed: conn.execute("UPDATE rate_limits SET request_count=request_count+1 WHERE bucket=?", (key,))
        conn.execute("DELETE FROM rate_limits WHERE window_start < ?", (now - 86400,)); conn.execute("COMMIT")
    return allowed

