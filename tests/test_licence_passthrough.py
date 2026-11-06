"""#2638: MCP answers pass the API's licence fields through unchanged, and StatsMapped's own citation note no longer overwrites the publisher's
attribution: it goes in `attribution_note`, and `attribution` keeps the publisher's wording (falling back to the StatsMapped note only when the API sends
none). No network: `_get` is patched.

Run:
    python mcp-server/tests/test_licence_passthrough.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client

failures: list[str] = []
LIC = {"publisher": "NISRA", "license": "https://example.org/ogl", "licence_class": "ogl", "licence_restrictions": ["attribution"], "attribution": "Source: NISRA"}


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def main() -> int:
    calls = {
        "explain_metric": lambda: client.explain_metric("live_register"),
        "get_dataset_for_area": lambda: client.get_dataset_for_area("county:kerry", "x"),
        "get_comparison": lambda: client.get_comparison("a__b"),
    }
    for name, call in calls.items():
        with patch.object(client, "_get", return_value={"stat_key": "s", **LIC}):
            out = call()
        check(f"{name} keeps every licence field, including the publisher's attribution", all(out.get(k) == v for k, v in LIC.items()), str(out))
        check(f"{name} puts StatsMapped's note in attribution_note", out.get("attribution_note") == client.ATTRIBUTION, str(out))
        with patch.object(client, "_get", return_value={"stat_key": "s"}):
            bare = call()
        check(f"{name} with no publisher attribution falls back to the StatsMapped note", bare.get("attribution") == client.ATTRIBUTION, str(bare))

    with patch.object(client, "_get", return_value=[{"series_key": "k1", **LIC}]):
        nc = client.get_notable_changes(limit=1)
    item = (nc.get("alerts") or [{}])[0]
    check("notable_changes keeps every licence field on each alert", all(item.get(k) == v for k, v in LIC.items()), str(item))

    for f in failures:
        print("FAIL", f)
    print(f"test_licence_passthrough: {'FAIL' if failures else 'PASS'} ({len(failures)} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
