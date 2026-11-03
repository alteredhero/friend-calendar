"""Password hashing for the group password (stdlib only: PBKDF2-HMAC-SHA256).

Stored format:  pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
"""
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 310_000


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${_derive(password, salt, ITERATIONS).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, hash_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        candidate = _derive(password, bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate, bytes.fromhex(hash_hex))
    except ValueError:  # malformed hash: treat as "no match" rather than crashing the login
        return False
