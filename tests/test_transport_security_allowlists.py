"""
`server.py`'s `_transport_security_allowlists()` -- PURE (no network, no server).

WHY THIS EXISTS. #887 (A7 audit, 9 Oct): `allowed_origins` was reusing
`allowed_hosts`' own bare-hostname list. The MCP SDK compares a request's real
`Origin` header, which always carries a scheme (`https://mcp.statsmapped.com`),
against `allowed_origins` verbatim -- a bare hostname in that list can never
match a scheme-qualified origin. Confirmed live, a real 100% bug: EVERY
request carrying an Origin header (any browser-based MCP client) was refused
with 403 "Invalid Origin header", reproduced directly against production with
curl, including the exact correct origin itself (`https://mcp.statsmapped.com`,
still refused before this fix). Only requests with no Origin header at all
(stdio clients, most server-to-server callers) ever got through.

WHAT THIS CHECKS
----------------
1. `allowed_hosts` stays bare (no scheme) -- correct for Host-header matching,
   unchanged by this fix.
2. `allowed_origins` gets an `https://` scheme prefix -- the real shape a
   browser's Origin header always has, and the exact thing the old code got
   wrong.
3. Multiple comma-separated hosts each get their own scheme-qualified origin,
   not just the first.
4. An empty env var produces two empty lists, not a crash or a bogus
   `["https://"]` entry -- the SDK's own documented fail-closed behaviour
   (every request rejected) still applies when nothing is configured.
5. Whitespace around a comma-separated host is stripped, same as the
   pre-existing `allowed_hosts` behaviour this fix must not regress.

Run:
    python mcp-server/tests/test_transport_security_allowlists.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp.server import _transport_security_allowlists

failures: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + str(detail) if detail else ''}")


# ---- 1-2. The real production shape: one bare hostname. -------------------------------
hosts, origins = _transport_security_allowlists("mcp.statsmapped.com")
check("allowed_hosts stays bare, no scheme", hosts == ["mcp.statsmapped.com"], hosts)
check("allowed_origins gets an https:// scheme -- the real bug fix",
      origins == ["https://mcp.statsmapped.com"], origins)


# ---- 3. Multiple comma-separated hosts. ------------------------------------------------
hosts2, origins2 = _transport_security_allowlists("a.example.com,b.example.com")
check("multiple hosts stay bare in allowed_hosts",
      hosts2 == ["a.example.com", "b.example.com"], hosts2)
check("every host gets its own scheme-qualified origin, not just the first",
      origins2 == ["https://a.example.com", "https://b.example.com"], origins2)


# ---- 4. Empty env var -- fail-closed, not a bogus entry. --------------------------------
hosts3, origins3 = _transport_security_allowlists("")
check("an empty env var produces an empty allowed_hosts list (the SDK's own "
      "fail-closed default then applies)", hosts3 == [], hosts3)
check("an empty env var produces an empty allowed_origins list, never a bogus "
      "['https://'] entry", origins3 == [], origins3)


# ---- 5. Whitespace is stripped, matching the pre-existing allowed_hosts behaviour. -----
hosts4, origins4 = _transport_security_allowlists(" mcp.statsmapped.com , other.example.com ")
check("whitespace around a comma-separated host is stripped",
      hosts4 == ["mcp.statsmapped.com", "other.example.com"], hosts4)
check("the stripped host is what gets the scheme prefix, not the raw whitespace-padded one",
      origins4 == ["https://mcp.statsmapped.com", "https://other.example.com"], origins4)


if failures:
    print(f"FAILURES ({len(failures)}):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(
    "PASS: _transport_security_allowlists (#887) -- allowed_hosts stays bare, "
    "allowed_origins gets the https:// scheme every real Origin header carries "
    "(the real production bug this fixes), multiple hosts and whitespace are "
    "both handled correctly, and an empty env var produces two empty lists "
    "rather than a crash or a bogus entry. No network, no server."
)
