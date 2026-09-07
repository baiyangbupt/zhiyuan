#!/usr/bin/env python3
"""Minimal binding echo fixture used by the App Server PoC."""

from __future__ import annotations

import json
import sys


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        if method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "echo_binding",
                        "description": "Return trusted binding metadata.",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }
        elif method == "tools/call":
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "binding": "trusted",
                                "model_identity_override": "ignored",
                                "revoked": "denied",
                            }
                        ),
                    }
                ],
                "isError": False,
            }
        else:
            result = {}
        if "id" in request:
            sys.stdout.write(
                json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()
