"""
`get_scene` for "county-in-motion" (#3292 item 8): the client calls the BARE Ireland-only route /api/v1/scenes/county-in-motion with purpose, county (default county:dublin) and terms,
refuses a bad terms or county before any request, and "ireland-builds" still hits /ireland/api/v1/scenes/ireland-builds unchanged. No network.

Run:
    python mcp-server/tests/test_get_scene_county_in_motion.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client, server

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def call(*args, **kwargs):
    seen: dict = {}
    with patch.object(client, "_get", side_effect=lambda path, params=None: seen.update(path=path, params=params) or {"ok": True}):
        client.get_scene(*args, **kwargs)
    return seen


def refused(label: str, **kwargs) -> None:
    seen: dict = {}
    with patch.object(client, "_get", side_effect=lambda path, params=None: seen.update(path=path) or {}):
        try:
            client.get_scene("county-in-motion", **kwargs)
            check(label, False, "no error raised")
        except client.ArgumentError:
            check(label + " (no request made)", not seen, str(seen))


def main() -> int:
    s = call("county-in-motion", county="county:cork", terms="nominal", purpose="promotional")
    check("county-in-motion uses the bare path with county, terms, purpose", s == {"path": "/api/v1/scenes/county-in-motion", "params": {"purpose": "promotional", "county": "county:cork", "terms": "nominal"}}, str(s))
    s = call("county-in-motion")
    check("county defaults to county:dublin, terms to real", s.get("params") == {"purpose": "analytical", "county": "county:dublin", "terms": "real"} and s.get("path") == "/api/v1/scenes/county-in-motion", str(s))
    refused("a bad terms is refused", terms="adjusted")
    refused("a county without the county: prefix is refused", county="cork")
    refused("an empty county slug is refused", county="county:")
    refused("a county with a bad slug is refused", county="county:Cork City!")
    s = call("ireland-builds", purpose="promotional", vintage="2026-10-01")
    check("ireland-builds is unchanged", s == {"path": "/ireland/api/v1/scenes/ireland-builds", "params": {"purpose": "promotional", "vintage": "2026-10-01"}}, str(s))
    try:
        client.get_scene("county-in-motion", country="united-kingdom")
        check("county-in-motion stays Ireland-only", False)
    except ValueError:
        pass
    with patch.object(server.client, "get_scene", return_value={}) as m, patch.object(server.client, "log_tool_call"):
        server.get_scene(scene_id="county-in-motion", county="county:cork", terms="nominal")
        check("the server tool passes county and terms through", m.call_args.kwargs.get("county") == "county:cork" and m.call_args.kwargs.get("terms") == "nominal", str(m.call_args))
    doc = server.get_scene.__doc__ or ""
    check("the tool description names both scenes", "ireland-builds" in doc and "county-in-motion" in doc and "county:" in doc)

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_get_scene_county_in_motion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
