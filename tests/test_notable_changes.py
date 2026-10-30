"""
`notable_changes` (#1796): the sixth MCP tool. It calls client.get_notable_changes, logs every call to the demand beacon with the right answer type and only closed-list
parameters, refuses a limit outside 1..50 before any request, and the client function hits /{country}/api/v1/alerts/notable with only the params that were given,
wrapping the list under "alerts". No network.

Run:
    python mcp-server/tests/test_notable_changes.py
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


ALERTS = [{"stat_key": "median_sale_price", "geography_id": "county:kerry", "period": "2026Q2", "direction": "up"}]


def main() -> int:
    names = [t.name for t in server.server._tool_manager.list_tools()]
    check("notable_changes is registered as an MCP tool", "notable_changes" in names, str(names))

    doc = server.notable_changes.__doc__ or ""
    check("the tool docstring opens with 'Use when'", doc.strip().startswith("Use when"), doc[:40])
    first_two = " ".join(doc.split())
    check("the first two docstring sentences are under 330 characters", len(first_two.split(". ")[0] + ". " + first_two.split(". ")[1]) < 330)

    logged: list = []
    with patch.object(server.client, "get_notable_changes", return_value={"alerts": ALERTS, "count": 1}) as m, \
            patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
        r = server.notable_changes()
        check("a default call routes to client.get_notable_changes with the defaults",
              m.call_args.kwargs == {"limit": 8, "stat_key": None, "geography_id": None, "country": "ireland"}, str(m.call_args))
        check("logged as notable_changes / success / answered",
              logged[-1][0] == "notable_changes" and logged[-1][2] == "success" and logged[-1][4] == "answered", str(logged[-1]))
        check("the client's result is returned untouched", r == {"alerts": ALERTS, "count": 1})

    # limit 0 and 51 are refused before any request is made (the real client runs, _get is patched to catch any request)
    for bad in (0, 51):
        logged = []
        with patch.object(client, "_get", return_value=[]) as get_mock, \
                patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
            try:
                server.notable_changes(limit=bad)
                check(f"limit={bad} is refused", False)
            except ValueError:
                check(f"limit={bad} is logged as unsupported", logged and logged[-1][2] == "error" and logged[-1][4] == "unsupported", str(logged[-1:]))
            check(f"limit={bad} makes no request", get_mock.call_count == 0)

    # client-level behaviour, with _get patched so nothing hits the network
    seen: dict = {}

    def fake_get(path, params=None):
        seen.update(path=path, params=params)
        return list(ALERTS)

    with patch.object(client, "_get", side_effect=fake_get):
        out = client.get_notable_changes(limit=3, stat_key="median_sale_price", geography_id="county:kerry", country="ireland")
    check("the client calls /ireland/api/v1/alerts/notable with the given params",
          seen == {"path": "/ireland/api/v1/alerts/notable",
                   "params": {"limit": 3, "stat_key": "median_sale_price", "geography_id": "county:kerry"}}, str(seen))
    check("the list is wrapped under 'alerts' with a count and the attribution note",
          out.get("alerts") == ALERTS and out.get("count") == 1 and out.get("attribution_note") == client.ATTRIBUTION, str(out))

    seen.clear()
    with patch.object(client, "_get", side_effect=fake_get):
        client.get_notable_changes(country="united-kingdom")
    check("only the given params are sent (default limit, no stat_key or geography_id)",
          seen == {"path": "/united-kingdom/api/v1/alerts/notable", "params": {"limit": 8}}, str(seen))

    for bad in (0, 51):
        try:
            client.get_notable_changes(limit=bad)
            check(f"client refuses limit={bad}", False)
        except ValueError:
            pass

    # a client exception is logged as error and re-raised
    logged = []
    with patch.object(server.client, "get_notable_changes", side_effect=client.StatsMappedAPIError("500 from /ireland/api/v1/alerts/notable")), \
            patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
        try:
            server.notable_changes()
            check("a client exception is re-raised", False)
        except client.StatsMappedAPIError:
            check("a client exception is logged as error", logged and logged[-1][0] == "notable_changes" and logged[-1][2] == "error" and logged[-1][4] == "error", str(logged[-1:]))

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_notable_changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
