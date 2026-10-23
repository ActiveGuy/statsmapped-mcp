"""#1202: slim MCP replies. Offline (fake `_get`), plus the dispatch of the new arguments.

Run:
    python mcp-server/tests/test_slim_replies.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client, server

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def main() -> int:
    rows = [{"country": "ie", "id": "county:carlow", "level": "county", "name": "Carlow", "name_ga": "Ceatharlach",
             "publishable": True, "vintage": "2019", "source_note": "x" * 200, "boundary": None, "centroid": {"lon": 1},
             "parents": [{"id": "province:leinster", "name": "Leinster"}], "slug": "carlow"}]
    slim = client.slim_areas(rows)
    check("default is id, name, level only", slim == [{"id": "county:carlow", "name": "Carlow", "level": "county"}], str(slim))
    full = client.slim_areas(rows, include_parents=True)
    check("include_parents adds parents and name_ga, never boundary or centroid",
          set(full[0]) == {"id", "name", "level", "name_ga", "parents"}, str(full[0].keys()))
    check("the slim reply is much smaller", len(json.dumps(slim)) * 5 < len(json.dumps(rows)))

    data = {"geography": {"id": "county:dublin"},
            "available": [{"series_key": "a", "stat_key": "rppi", "caveats": [{"label": "L", "severity": "info"}]},
                          {"series_key": "b", "stat_key": "crime"}],
            "national": [{"series_key": "c", "stat_key": "rppi"}, {"series_key": "d", "stat_key": "cpi"}],
            "not_comparable": []}
    real = client._get
    client._get = lambda path, params=None: data
    try:
        allr = client.list_area_datasets("county:dublin")
        one = client.list_area_datasets("county:dublin", stat_key="rppi")
        none = client.list_area_datasets("county:dublin", stat_key="nope")
    finally:
        client._get = real
    check("no filter keeps everything", len(allr["available"]) == 2 and len(allr["national"]) == 2)
    check("stat_key keeps only that stat in every bucket",
          [e["series_key"] for e in one["available"]] == ["a"] and [e["series_key"] for e in one["national"]] == ["c"], str(one))
    check("an unknown stat gives empty buckets, not an error", none["available"] == [] and none["national"] == [])

    # #1279: the API's real key for the bucket is "not_county_comparable"
    real_shape = {"geography": {"id": "county:dublin"}, "available": [], "national": [],
                  "not_county_comparable": [{"series_key": "nc1", "stat_key": "cattle"}, {"series_key": "nc2", "stat_key": "rppi"}]}
    client._get = lambda path, params=None: real_shape
    try:
        nc = client.list_area_datasets("county:dublin")
        nc_one = client.list_area_datasets("county:dublin", stat_key="cattle")
        listing_keys = client.series_keys_for_stat(nc, "cattle")
    finally:
        client._get = real
    check("#1279: the API's not_county_comparable bucket is returned under not_comparable",
          [e["series_key"] for e in nc["not_comparable"]] == ["nc1", "nc2"], str(nc))
    check("#1279: the stat_key filter applies to it too", [e["series_key"] for e in nc_one["not_comparable"]] == ["nc1"], str(nc_one))
    check("#1279: a stat only present in that bucket now resolves", listing_keys == ["nc1"], str(listing_keys))
    client._get = lambda path, params=None: {"available": [], "national": [], "not_comparable": [{"series_key": "old1", "stat_key": "x"}]}
    try:
        old_shape = client.list_area_datasets("county:dublin")
    finally:
        client._get = real
    check("#1279: the old key name is still tolerated", [e["series_key"] for e in old_shape["not_comparable"]] == ["old1"], str(old_shape))
    check("the filtered reply is smaller", len(json.dumps(one)) < len(json.dumps(allr)))

    with patch.object(server.client, "list_area_datasets", return_value={"ok": 1}) as m, \
         patch.object(server.client, "log_tool_call"):
        server.query_data(area_id="county:dublin", stat_key="rppi")
        check("query_data passes stat_key through", m.call_args.kwargs.get("stat_key") == "rppi", str(m.call_args))
        server.query_data(area_id="county:dublin")
        check("without stat_key the call is unchanged", "stat_key" not in m.call_args.kwargs, str(m.call_args))
        for bad in (dict(stat_key="rppi"), dict(area_id="county:dublin", dataset="x", stat_key="rppi")):
            try:
                server.query_data(**bad)
                check(f"stat_key misuse {bad} is refused", False)
            except ValueError:
                pass
    with patch.object(server.client, "list_areas", return_value=[]) as m, patch.object(server.client, "log_tool_call"):
        server.list_areas()
        check("list_areas default does not ask for parents", "include_parents" not in m.call_args.kwargs, str(m.call_args))
        server.list_areas(include_parents=True)
        check("include_parents is passed through", m.call_args.kwargs.get("include_parents") is True)
    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_slim_replies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
