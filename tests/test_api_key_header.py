"""#1489: the MCP package sends an optional STATSMAPPED_API_KEY as X-API-Key on data calls only, never in the usage beacon or an error message; offline.

Run:
    python mcp-server/tests/test_api_key_header.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client

failures: list[str] = []


def check(label, cond, detail=""):
    if not cond:
        failures.append(f"{label}{': ' + str(detail) if detail else ''}")


SECRET = "k-secret-123"
saved = os.environ.get("STATSMAPPED_API_KEY")
try:
    os.environ.pop("STATSMAPPED_API_KEY", None)
    check("no env var: no key header, just the user agent", "X-API-Key" not in client._request_headers() and "User-Agent" in client._request_headers())
    os.environ["STATSMAPPED_API_KEY"] = f"  {SECRET}  "
    check("env var set: sent as X-API-Key, trimmed", client._request_headers().get("X-API-Key") == SECRET)
    os.environ["STATSMAPPED_API_KEY"] = "   "
    check("a blank value sends nothing", "X-API-Key" not in client._request_headers())

    os.environ["STATSMAPPED_API_KEY"] = SECRET
    seen = {}

    class Fake:
        def __init__(self, *a, headers=None, **k):
            seen.setdefault("headers", []).append(dict(headers or {}))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            class R:
                status_code = 401
                text = "unauthorised"

                def json(self):
                    return {"error": {"message": "That API key is not recognised."}}
            return R()

        def post(self, url, json=None):
            seen.setdefault("posts", []).append(json)

    real = client.httpx.Client
    client.httpx.Client = Fake
    try:
        try:
            client._get("/ireland/api/v1/stats")
        except client.StatsMappedAPIError as exc:
            check("the key is not in the error message", SECRET not in str(exc), str(exc))
        check("the data call carried the key", seen["headers"][0].get("X-API-Key") == SECRET)
        client._post_tool_call_event("query_data", "ireland", "success")
        beacon_headers = seen["headers"][1]
        check("the usage beacon never carries the key (header or payload)", "X-API-Key" not in beacon_headers and SECRET not in str(seen.get("posts")), (beacon_headers, seen.get("posts")))
    finally:
        client.httpx.Client = real
finally:
    if saved is None:
        os.environ.pop("STATSMAPPED_API_KEY", None)
    else:
        os.environ["STATSMAPPED_API_KEY"] = saved
if failures:
    print("FAIL")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)
print("OK  test_api_key_header")
