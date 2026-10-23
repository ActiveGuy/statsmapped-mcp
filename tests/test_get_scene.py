"""
`get_scene` (#1711, EA wl:3671222e21ba): the fifth MCP tool. It calls client.get_scene, logs every call to the demand beacon with the right answer type and only closed-list parameters,
refuses a bad purpose and a non-Irish country before any request, and the client function hits /ireland/api/v1/scenes/{scene_id} with purpose (and vintage when given). No network.

Run:
    python mcp-server/tests/test_get_scene.py
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


BUNDLE = {"scene_id": "ireland-builds", "scene_hash": "ab" * 32, "receipt": "sr1-" + "ab" * 12, "rows": [{"quarter": "2018Q1", "permitted": 1, "commenced": 1, "completed": 1}], "licence": {"line": "Source: CSO."}}


def main() -> int:
    logged = []
    with patch.object(server.client, "get_scene", return_value=BUNDLE) as m, patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
        r = server.get_scene()
        check("defaults call client.get_scene for ireland-builds, analytical, current vintage", m.call_args.args[0] == "ireland-builds" and m.call_args.kwargs == {"purpose": "analytical", "vintage": None, "country": "ireland"}, str(m.call_args))
        check("the bundle is returned untouched", r is BUNDLE)
        check("logged as get_scene / success / answered with closed-list params only", logged[-1][0] == "get_scene" and logged[-1][2] == "success" and logged[-1][3] == {"scene_id": "ireland-builds", "purpose": "analytical"} and logged[-1][4] == "answered", str(logged[-1]))
        logged.clear()
        calls_before = m.call_count
        try:
            server.get_scene(purpose="viral")
            check("a bad purpose is refused", False)
        except ValueError:
            check("a bad purpose is refused before any request and logged as unsupported", m.call_count == calls_before and logged and logged[-1][4] == "unsupported", str(logged[-1:]))
    with patch.object(server.client, "get_scene", side_effect=client.StatsMappedAPIError("licence_refused")), patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
        logged.clear()
        try:
            server.get_scene(purpose="promotional")
            check("a licence refusal raises", False)
        except client.StatsMappedAPIError:
            check("a licence refusal raises and is logged as error", logged and logged[-1][4] == "error", str(logged[-1:]))
    seen = {}
    with patch.object(client, "_get", side_effect=lambda path, params=None: seen.update(path=path, params=params) or dict(BUNDLE)):
        client.get_scene("ireland-builds", purpose="promotional", vintage="2026-10-01")
    check("the client calls /ireland/api/v1/scenes/{id} with purpose and vintage", seen == {"path": "/ireland/api/v1/scenes/ireland-builds", "params": {"purpose": "promotional", "vintage": "2026-10-01"}}, str(seen))
    try:
        client.get_scene(country="united-kingdom")
        check("the client refuses the UK", False)
    except ValueError:
        pass
    check("scene_id and purpose are closed-list demand parameters", "scene_id" in client.DEMAND_PARAM_KEYS and "purpose" in client.DEMAND_PARAM_KEYS)
    doc = server.get_scene.__doc__ or ""
    check("the tool description gives an example, the hash/licence instruction and the refusal", 'get_scene(scene_id="ireland-builds")' in doc and "scene_hash" in doc and "licence_refused" in doc)

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_get_scene")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
