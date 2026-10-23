"""
`query_data(council=...)`, the planning-summary mode (#1499, EA wl:823fb091ecbf): it dispatches to client.get_planning_summary, is additive (no existing call changes), refuses to be
mixed with the other modes or used for the UK, and every call is logged to the demand beacon with the right answer type (answered / empty / unsupported / error) and the council as a
closed-list parameter. The client function hits the planning-summary route and passes a stopped council's typed absences through untouched. No network: the HTTP layer is mocked.

Run:
    python mcp-server/tests/test_council_mode.py
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


STOPPED = {"council_id": "la:cork-city-council", "status": "stopped_reporting", "absences": [{"period": "2026", "value": None, "absent": True, "absence": {"type": "FEED_SILENT"}}],
           "receipt": "dr1-abc", "years": [], "notes": ["no planning records after 2025-11-04"]}


def main() -> int:
    logged = []
    with patch.object(server.client, "get_planning_summary", return_value=STOPPED) as m_ps, \
         patch.object(server.client, "list_datasets", return_value=["A"]) as m_ld, \
         patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
        r = server.query_data(council="cork-city-council")
        check("council alone dispatches to get_planning_summary with the slug and country", m_ps.called and m_ps.call_args.args[0] == "cork-city-council" and m_ps.call_args.kwargs.get("country") == "ireland" and not m_ld.called)
        check("the answer is returned untouched, with the typed absence and the receipt", r is STOPPED and r["absences"][0]["absence"]["type"] == "FEED_SILENT" and r["receipt"] == "dr1-abc")
        check("the call is logged as success / answered with the council as a closed-list parameter",
              logged and logged[-1][0] == "query_data" and logged[-1][2] == "success" and logged[-1][3] == {"council": "cork-city-council"} and logged[-1][4] == "answered", logged[-1:] if logged else logged)

        server.query_data(country="ireland")
        check("no existing call changes: with no council the old dispatch (list_datasets) still runs", m_ld.called)

        for label, kwargs in (("area_id", {"area_id": "county:kerry"}), ("dataset", {"area_id": "county:kerry", "dataset": "sale_price"}), ("stat_key", {"stat_key": "cpi"}), ("history_months", {"history_months": 12})):
            logged.clear()
            try:
                server.query_data(council="cork-city-council", **kwargs)
                check(f"council mixed with {label} is refused", False)
            except ValueError:
                check(f"council mixed with {label} is refused and logged as unsupported", logged and logged[-1][4] == "unsupported", str(logged[-1:]))
        logged.clear()
        try:
            server.query_data(council="kerry-county-council", country="united-kingdom")
            check("council for the UK is refused", False)
        except ValueError:
            check("council for the UK is refused and logged as unsupported", logged and logged[-1][4] == "unsupported", str(logged[-1:]))

    with patch.object(server.client, "get_planning_summary", return_value={"status": "no_records", "years": []}), patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
        logged.clear()
        server.query_data(council="nowhere-council")
        check("a council with no records at all is logged as empty", logged and logged[-1][4] == "empty", str(logged[-1:]))
    with patch.object(server.client, "get_planning_summary", side_effect=client.StatsMappedAPIError("Unknown council.")), patch.object(server.client, "log_tool_call", side_effect=lambda *a, **k: logged.append(a)):
        logged.clear()
        try:
            server.query_data(council="not-a-council")
            check("an unknown council raises", False)
        except client.StatsMappedAPIError:
            check("an unknown council raises and is logged as error", logged and logged[-1][4] == "error", str(logged[-1:]))

    # ---- the client function
    seen = {}
    with patch.object(client, "_get", side_effect=lambda path, *a, **k: seen.setdefault("path", path) and dict(STOPPED)):
        out = client.get_planning_summary("cork-city-council")
    check("the client calls /ireland/api/v1/planning_summary/{council}", seen.get("path") == "/ireland/api/v1/planning_summary/cork-city-council", str(seen))
    try:
        client.get_planning_summary("x", country="united-kingdom")
        check("the client raises for the UK", False)
    except ValueError:
        pass
    check("council is on the closed parameter list, and a no_records answer counts as empty", "council" in client.DEMAND_PARAM_KEYS and client.answer_type_for({"status": "no_records"}) == "empty" and client.answer_type_for(out) == "answered")
    check("the tool description gives an example", 'query_data(council="cork-city-council")' in (server.query_data.__doc__ or ""))
    doc = (Path(server.__file__).read_text(encoding="utf-8"))
    check("the source documents the council mode with an example and the stopped-reporting meaning", 'query_data(council="cork-city-council")' in doc and "stopped_reporting" in doc)

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_council_mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
