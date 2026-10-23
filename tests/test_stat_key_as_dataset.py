"""#1201: query_data / get_dataset_for_area accept a STAT key as `dataset` (3 of 10 pilot runs failed first). Offline: `_get` is replaced,
so no network.

Run:
    python mcp-server/tests/test_stat_key_as_dataset.py
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
    listing = {"available": [{"series_key": "weekly_earnings_median_dublin", "stat_key": "weekly_earnings_median"},
                              {"series_key": "x_a", "stat_key": "multi"}, {"series_key": "x_b", "stat_key": "multi"}],
               "national": [{"series_key": "x_a", "stat_key": "multi"}], "not_comparable": []}
    check("series_keys_for_stat: one", client.series_keys_for_stat(listing, "weekly_earnings_median") == ["weekly_earnings_median_dublin"])
    check("series_keys_for_stat: several, no repeats, in order", client.series_keys_for_stat(listing, "multi") == ["x_a", "x_b"])
    check("series_keys_for_stat: none", client.series_keys_for_stat(listing, "nope") == [])

    calls: list[str] = []

    def fake_get(path, params=None):
        calls.append(path)
        if path.endswith("/series"):
            return {"geography": {"id": "county:dublin"}, **listing}
        key = path.rsplit("/", 1)[1]
        if key in ("weekly_earnings_median_dublin", "x_a"):
            return {"series_key": key, "latest_value": 1}
        raise client.StatsMappedAPIError(f"404 from {path}: unknown dataset", status_code=404)

    real = client._get
    client._get = fake_get
    try:
        out = client.get_dataset_for_area("county:dublin", "weekly_earnings_median")
        check("a stat key with one series resolves to it and says so",
              out.get("series_key") == "weekly_earnings_median_dublin" and out.get("resolved_from_stat_key") == "weekly_earnings_median", str(out))
        check("a real series key still goes straight through (no listing call)",
              (calls.clear() or client.get_dataset_for_area("county:dublin", "x_a")) and not any(c.endswith("/series") for c in calls))
        try:
            client.get_dataset_for_area("county:dublin", "multi")
            check("several series for the stat is an error naming them", False)
        except client.StatsMappedAPIError as exc:
            check("the error names the series keys to use", "x_a" in str(exc) and "x_b" in str(exc), str(exc))
        try:
            client.get_dataset_for_area("county:dublin", "nope")
            check("an unknown key keeps the original error", False)
        except client.StatsMappedAPIError as exc:
            check("original 404 stands", "unknown dataset" in str(exc), str(exc))
    finally:
        client._get = real

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("OK  test_stat_key_as_dataset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
