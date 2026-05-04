#!/usr/bin/env python3
"""Create a real backend chat session for fresh-session validation.

Usage:
  ./.venv/bin/python examples/create_real_session.py \
      --tk <LOGIN_TOKEN> \
      --pf WEB \
      --payload-file /path/to/create_session_req.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.util.internal_client import create_chat_session


def _load_payload(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("payload file must contain a JSON object")
    return data


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Create a real backend chat session.")
    parser.add_argument("--tenant-id", default="1", help="backend tenant id")
    parser.add_argument("--tk", required=True, help="authenticated login token used by backend login interceptor")
    parser.add_argument(
        "--pf",
        default="WEB",
        help="platform enum name expected by backend login interceptor, e.g. WEB / APP / WECHAT_MP",
    )
    parser.add_argument("--payload-file", required=True, help="JSON file containing CreateSessionReq payload")
    args = parser.parse_args()

    payload = _load_payload(args.payload_file)
    response = await create_chat_session(
        args.tenant_id,
        payload,
        tk=args.tk,
        pf=args.pf,
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))

    session_id = (((response or {}).get("data") or {}).get("id"))
    if session_id is not None:
        print(f"\nchatSessionId={session_id}")


if __name__ == "__main__":
    asyncio.run(_main())
