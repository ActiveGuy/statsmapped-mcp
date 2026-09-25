"""
`server.py`'s root_redirect route -- PURE (no network; builds the real
Starlette app in-process via `server.streamable_http_app()` and drives it
with Starlette's own TestClient, no uvicorn/socket involved).

WHY THIS EXISTS. wl:1bea0f7c116a (developer decision via EA, 2026-09-25):
the advertised hosted address, https://mcp.statsmapped.com, 404'd at its own
bare root because the SDK's streamable-http transport only ever mounts the
real protocol endpoint at /mcp. This pins that the bare root now redirects
there, rather than trusting the route registration alone -- a
`@server.custom_route` decorator call that never actually gets exercised by
a real request would look identical in a diff to one that works.

Run:
    python -m pytest tests/test_root_redirect.py -v
or, dependency-free:
    python tests/test_root_redirect.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from starlette.testclient import TestClient

from statsmapped_mcp.server import server

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def main() -> int:
    app = server.streamable_http_app()
    client = TestClient(app, follow_redirects=False)

    # ---- 1. The bare root redirects, rather than 404ing. -----------------------
    resp = client.get("/")
    check("GET / does not 404 (the exact bug this route exists to fix)",
          resp.status_code != 404, f"got {resp.status_code}")
    check("GET / returns a redirect status (3xx)",
          300 <= resp.status_code < 400, f"got {resp.status_code}")

    # ---- 2. It redirects specifically to /mcp, not somewhere else. -------------
    location = resp.headers.get("location", "")
    check("the redirect Location header points at /mcp",
          location == "/mcp" or location.endswith("/mcp"),
          f"got Location: {location!r}")

    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print(
        "PASS: root_redirect -- 3 checks. GET / on the real streamable-http "
        "Starlette app returns a 3xx redirect to /mcp rather than 404ing. "
        "No network, no uvicorn/socket -- Starlette's own in-process TestClient."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
