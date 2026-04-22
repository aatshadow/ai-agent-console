#!/usr/bin/env python3
"""Issue license keys for ai-agent-console.

Requires LICENSE_SECRET in the environment (or `.env.local`). Never commit
the secret. Until the Whop webhook is wired, run this by hand when someone
buys a key.

Usage:
    LICENSE_SECRET=... python3 tools/issue_key.py <email> [--tier pro] [--expires 2027-01-01]
    LICENSE_SECRET=... python3 tools/issue_key.py --verify <KEY>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / ".claude" / "skills" / "agent-console" / "lib"))

import license as lic  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Issue / verify ai-agent-console keys.")
    p.add_argument("email_or_key", nargs="?", help="email to issue a key for")
    p.add_argument("--tier", default="standard", help="tier label (standard|pro|...)")
    p.add_argument("--expires", default=None, help="expiry date ISO (YYYY-MM-DD); omit = perpetual")
    p.add_argument("--verify", metavar="KEY", help="verify a key instead of issuing")
    args = p.parse_args()

    if args.verify:
        result = lic.verify(args.verify)
        print(f"ok      : {result.ok}")
        print(f"reason  : {result.reason}")
        if result.payload:
            print(f"payload : {result.payload}")
        return 0 if result.ok else 1

    if not args.email_or_key:
        p.error("email is required to issue a key")

    try:
        key = lic.issue(args.email_or_key, tier=args.tier, expires_at=args.expires)
    except lic.LicenseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
