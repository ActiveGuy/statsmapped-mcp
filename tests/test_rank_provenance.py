"""#1204: rank_areas puts the ranking's publisher, licence and (rate rankings) denominator on the first row. Offline.

Run:
    python mcp-server/tests/test_rank_provenance.py
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
    data = {"permalink": "https://statsmapped.com/ireland/rankings/homelessness", "publisher": "DHLGH", "licence": "CC BY-SA 4.0", "attribution": "Source: DHLGH", "latest_period": "2026-07-01",
            "rate_ranked": True, "denominator": {"stat_key": "population", "label": "Population", "period": "2022-01-01",
                                                  "publisher": "CSO FY006B", "country": "ie"},
            "unit": "count", "caveats": [], "rows": [{"geo_id": "a", "name": "A", "value": 10, "rate_per_1000": 5.6},
                                                     {"geo_id": "b", "name": "B", "value": 5, "rate_per_1000": 2.0}]}
    p = client.ranking_provenance(data)
    check("publisher, licence, attribution and period are carried", p["publisher"] == "DHLGH" and p["licence"] == "CC BY-SA 4.0"
          and p["attribution"] == "Source: DHLGH" and p["latest_period"] == "2026-07-01", str(p))
    check("a rate ranking names its denominator, period and publisher (no stray keys)",
          p["denominator"] == {"label": "Population", "period": "2022-01-01", "publisher": "CSO FY006B"}, str(p))
    check("#1181: the ranking page's permalink rides in the provenance",
          p.get("permalink") == "https://statsmapped.com/ireland/rankings/homelessness", str(p))
    # #1327: Ireland's live_register is ordered by count but each row carries the rate, and the denominator is named
    shown = {**data, "rate_ranked": False, "rate_shown": True}
    ps = client.ranking_provenance(shown)
    check("#1327: a count-ordered ranking that shows the rate still names its denominator",
          ps.get("denominator") == {"label": "Population", "period": "2022-01-01", "publisher": "CSO FY006B"}, str(ps))
    check("a raw ranking with no rate shown has no denominator",
          "denominator" not in client.ranking_provenance({**data, "rate_ranked": False, "rate_shown": False}))
    check("a raw ranking has no denominator", "denominator" not in client.ranking_provenance({**data, "rate_ranked": False}))
    check("missing facts are omitted, never invented", client.ranking_provenance({"rows": []}) == {})

    real_list, real_get = client.list_datasets, client._get
    client.list_datasets = lambda country="ireland": [{"key": "homelessness", "ranking_link": {"slug": "homelessness"}}]
    client._get = lambda path, params=None: data
    try:
        rows = client.rank_areas("homelessness")
    finally:
        client.list_datasets, client._get = real_list, real_get
    check("the first row carries provenance, the others do not", "provenance" in rows[0] and "provenance" not in rows[1], str(rows))
    check("the rate is still there", rows[0]["rate_per_1000"] == 5.6)
    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_rank_provenance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
