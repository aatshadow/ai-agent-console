"""
License verification — offline, HMAC-signed keys.

Key format: ``AAC1-<payload_b32>.<sig_b32>`` where
    payload = compact JSON ``{"email","tier","issued_at","expires_at"}``
    sig     = HMAC-SHA256(payload_bytes, SECRET) — first 16 bytes, base32

``expires_at`` may be null (perpetual) or an ISO-8601 date string (inclusive).

The verifier only needs the public pepper (``LICENSE_PEPPER`` bundled with the
installer) plus the signing secret (``LICENSE_SECRET``, kept on Alex's side and
in the installer build — never shipped to buyers). Verification is pure stdlib,
no network call.

Public API:
    verify(key: str) -> LicenseResult      # never raises on bad keys
    require_valid(key: str) -> dict         # raises LicenseError

CLI:
    python3 -m lib.license verify <key>
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

KEY_PREFIX = "AAC1-"
SIG_BYTES = 16  # 128 bits — plenty for HMAC-SHA256 truncation


class LicenseError(Exception):
    """Raised by ``require_valid`` when a key is missing, malformed, or expired."""


@dataclass
class LicenseResult:
    ok: bool
    reason: str
    payload: dict | None = None


# ── secret loading ──────────────────────────────────────────────────────────

def _load_secret() -> bytes:
    """Load LICENSE_SECRET from env or .env.local. Required for verification."""
    secret = os.getenv("LICENSE_SECRET")
    if not secret:
        env_file = PROJECT_ROOT / ".env.local"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("LICENSE_SECRET="):
                    secret = line.partition("=")[2].strip()
                    break
    if not secret:
        return b""
    return secret.encode("utf-8")


# ── encoding helpers ────────────────────────────────────────────────────────

def _b32(data: bytes) -> str:
    return base64.b32encode(data).rstrip(b"=").decode("ascii")


def _b32_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 8)
    return base64.b32decode(s + pad)


def _sign(payload: bytes, secret: bytes) -> bytes:
    return hmac.new(secret, payload, sha256).digest()[:SIG_BYTES]


# ── key issuance (used by tools/issue_key.py) ──────────────────────────────

def issue(email: str, *, tier: str = "standard", expires_at: str | None = None,
          secret: bytes | None = None) -> str:
    """Mint a new license key. ``secret`` defaults to env LICENSE_SECRET."""
    if secret is None:
        secret = _load_secret()
    if not secret:
        raise LicenseError("LICENSE_SECRET missing — cannot sign keys")
    payload = {
        "email": email.strip().lower(),
        "tier": tier,
        "issued_at": datetime.now(timezone.utc).date().isoformat(),
        "expires_at": expires_at,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = _sign(raw, secret)
    return f"{KEY_PREFIX}{_b32(raw)}.{_b32(sig)}"


# ── verification ────────────────────────────────────────────────────────────

def verify(key: str | None) -> LicenseResult:
    """Validate a key. Returns a result — never raises on bad input."""
    if not key or not isinstance(key, str):
        return LicenseResult(False, "no key provided")
    key = key.strip()
    if not key.startswith(KEY_PREFIX):
        return LicenseResult(False, f"key must start with {KEY_PREFIX}")
    body = key[len(KEY_PREFIX):]
    if "." not in body:
        return LicenseResult(False, "malformed key: missing separator")
    payload_b32, sig_b32 = body.split(".", 1)
    try:
        raw = _b32_decode(payload_b32)
        sig = _b32_decode(sig_b32)
    except Exception:
        return LicenseResult(False, "malformed key: base32 decode failed")
    secret = _load_secret()
    if not secret:
        return LicenseResult(False, "LICENSE_SECRET not set — cannot verify")
    expected = _sign(raw, secret)
    if not hmac.compare_digest(sig, expected):
        return LicenseResult(False, "signature mismatch — key invalid or tampered")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return LicenseResult(False, "payload not valid JSON")
    exp = payload.get("expires_at")
    if exp:
        try:
            exp_date = date.fromisoformat(exp)
        except ValueError:
            return LicenseResult(False, f"payload expires_at not a date: {exp!r}")
        if date.today() > exp_date:
            return LicenseResult(False, f"key expired on {exp}", payload)
    return LicenseResult(True, "ok", payload)


def require_valid(key: str | None) -> dict:
    """Strict wrapper: raises LicenseError if the key doesn't verify."""
    result = verify(key)
    if not result.ok:
        raise LicenseError(result.reason)
    return result.payload or {}


# ── startup gate helper ─────────────────────────────────────────────────────

def gate_or_exit(key: str | None, *, grace_seconds: int = 0) -> dict:
    """Call at agent/brain boot. On failure, print a clear message and exit.

    ``grace_seconds`` lets the operator run the wizard; set to 0 in production.
    """
    result = verify(key)
    if result.ok:
        return result.payload or {}
    sys.stderr.write(
        "\n──────────────────────────────────────────────\n"
        " License check failed.\n"
        f"   reason: {result.reason}\n"
        " Re-run the wizard or email support@blackwolfsec.io.\n"
        "──────────────────────────────────────────────\n\n"
    )
    if grace_seconds > 0:
        time.sleep(grace_seconds)
    sys.exit(2)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cli_verify(argv: list[str]) -> int:
    if not argv:
        print("usage: python3 -m lib.license verify <key>", file=sys.stderr)
        return 2
    result = verify(argv[0])
    print(json.dumps({
        "ok": result.ok,
        "reason": result.reason,
        "payload": result.payload,
    }, indent=2, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 -m lib.license <verify> [args]", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "verify":
        sys.exit(_cli_verify(sys.argv[2:]))
    print(f"unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)
