"""#1328: rank_areas rows for a homeless-region ranking carry the counties the region contains; other rows do not get an empty key. Offline.

Run:
    python mcp-server/tests/test_rank_member_counties.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def main() -> int:
    data = {"unit": "count", "caveats": [], "latest_period": "2026-07-01", "rate_ranked": True,
            "rows": [{"geo_id": "homeless_region:southwest", "name": "South-West", "value": 100, "rate_per_1000": 1.0,
                      "member_counties": ["Cork", "Kerry"]},
                     {"geo_id": "homeless_region:dublin", "name": "Dublin", "value": 900, "rate_per_1000": 5.6}]}
    real_list, real_get = client.list_datasets, client._get
    client.list_datasets = lambda country="ireland": [{"key": "homelessness", "ranking_link": {"slug": "homelessness"}}]
    client._get = lambda path, params=None: data
    try:
        rows = client.rank_areas("homelessness")
    finally:
        client.list_datasets, client._get = real_list, real_get
    sw = next(r for r in rows if r["display_name"] == "South-West")
    dub = next(r for r in rows if r["display_name"] == "Dublin")
    check("a region row names its member counties (the S12 question: which region is Cork in)", sw.get("member_counties") == ["Cork", "Kerry"], str(sw))
    check("a row without members has no key (never an empty list posing as a fact)", "member_counties" not in dub, str(dub))
    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_rank_member_counties")
    return 0


if __name__ == "__main__":
    sys.exit(main())
