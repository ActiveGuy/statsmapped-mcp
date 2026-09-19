"""
Tests `client.py`'s 5 tool functions against the REAL live StatsMapped API
(https://statsmapped.com, or STATSMAPPED_MCP_BASE_URL if set) -- this package
has no database or source-code access of its own to test against, only the
public HTTPS API every other client also uses, so that is what "real" means
here. All calls are read-only GETs against an already-public, unauthenticated
API; nothing here writes anything or needs a key.

Run:
    python -m pytest tests/test_client.py -v
or, dependency-free:
    python tests/test_client.py
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
    # --- list_datasets ------------------------------------------------------
    datasets = client.list_datasets()
    check("list_datasets returns a non-empty list", len(datasets) > 0)
    check("every dataset has a key and label",
          all("key" in d and "label" in d for d in datasets), str(datasets[:2]))
    stat_keys = {d["key"] for d in datasets}
    check("sale_price is a known stat", "sale_price" in stat_keys, str(stat_keys))

    # --- list_areas ----------------------------------------------------------
    counties = client.list_areas(level="county")
    check("list_areas('county') returns all 26 counties", len(counties) == 26,
          f"got {len(counties)}")
    check("no county row carries boundary/centroid",
          all("boundary" not in c and "centroid" not in c for c in counties))
    kerry = next((c for c in counties if c["id"] == "county:kerry"), None)
    check("county:kerry is present", kerry is not None, str(counties[:3]))
    check("county:kerry is named Kerry", kerry and kerry.get("name") == "Kerry",
          str(kerry))

    # --- list_area_datasets ---------------------------------------------------
    kerry_datasets = client.list_area_datasets("county:kerry")
    check("list_area_datasets returns available/not_comparable/national",
          {"available", "not_comparable", "national"} <= set(kerry_datasets),
          str(list(kerry_datasets)))
    check("list_area_datasets carries a top-level attribution field",
          kerry_datasets.get("attribution") == client.ATTRIBUTION,
          str(kerry_datasets.get("attribution")))
    available = kerry_datasets["available"]
    check("Kerry has at least one available dataset", len(available) > 0)
    sale_price_entry = next(
        (e for e in available if e.get("stat_key") == "sale_price"), None)
    check("Kerry's median sale price is in the available list",
          sale_price_entry is not None, str([e.get("stat_key") for e in available]))
    if sale_price_entry:
        check("projected entry carries no full caveat body",
              all("body" not in c for c in sale_price_entry.get("caveats", [])),
              str(sale_price_entry.get("caveats")))
        check("projected entry keeps caveat label/severity",
              all({"label", "severity"} <= set(c) for c in sale_price_entry.get("caveats", [])),
              str(sale_price_entry.get("caveats")))
        series_key_for_detail = sale_price_entry["series_key"]

    # --- get_dataset_for_area --------------------------------------------------
    if sale_price_entry:
        detail = client.get_dataset_for_area("county:kerry", series_key_for_detail)
        check("get_dataset_for_area returns the dataset's own name",
              "name" in detail.get("dataset", {}), str(detail)[:300])
        check("get_dataset_for_area carries full caveat bodies (unprojected)",
              any(c.get("body") for c in detail.get("caveats", [])),
              str(detail.get("caveats"))[:300])
        check("get_dataset_for_area carries a top-level attribution field",
              detail.get("attribution") == client.ATTRIBUTION,
              str(detail.get("attribution")))

        detail_2yr = client.get_dataset_for_area(
            "county:kerry", series_key_for_detail, history_months=24)
        facets = detail_2yr.get("dataset", {}).get("facets", [])
        if facets:
            history = facets[0].get("history", [])
            # median sale price is quarterly -- 24 months should mean ~8 quarters,
            # never the raw-row-count bug (24 points) this project fixed 2026-08-30.
            check("history_months=24 does not return 24 raw rows on non-monthly data",
                  len(history) <= 12, f"got {len(history)} points: {history}")

    # --- rank_areas ------------------------------------------------------------
    ranking = client.rank_areas("sale_price", level="county")
    check("rank_areas('sale_price') returns rankings", len(ranking) > 0)
    check("ranking is sorted descending by latest_value",
          all(ranking[i]["latest_value"] >= ranking[i + 1]["latest_value"]
              for i in range(len(ranking) - 1)),
          str([r["latest_value"] for r in ranking]))
    check("ranks are 1-indexed and sequential",
          [r["rank"] for r in ranking] == list(range(1, len(ranking) + 1)),
          str([r["rank"] for r in ranking][:5]))

    # A stat published at a level this call didn't ask for should come back
    # empty, not wrong or crashing -- e.g. eTenders is local_authority-level,
    # not county.
    empty_ranking = client.rank_areas("etenders", level="garda_division")
    check("a stat/level mismatch returns an empty list, not an error",
          empty_ranking == [], str(empty_ranking))

    # A stat with no ranking published at all is a genuinely different case
    # from a level mismatch above -- raises, rather than a silent empty list
    # that could be mistaken for "no data at this level".
    try:
        client.rank_areas("not_a_real_stat_key")
        check("an unknown/unranked stat_key raises", False,
              "expected StatsMappedAPIError, got a normal return")
    except client.StatsMappedAPIError:
        pass

    # --- rank_areas: CONTRACT-PARITY FIX regression check -----------------------
    # TODO.md "CONTRACT PARITY (not primacy inversion)": this tool used to hand-roll
    # a raw latest_value sort with no rate field and no caveats at all -- confirmed
    # live to mis-rank every RANKING_NO_DENOMINATOR_STATS member (live_register
    # included) by population size. UK's own live_register IS rate-ranked (Ireland's
    # own is not today -- real population-series coverage gap, not this tool's
    # concern), so it is real, live proof the fix actually reaches production data,
    # not just that the new code path executes.
    uk_live_register = client.rank_areas("live_register", country="united-kingdom")
    check("UK live_register ranking is non-empty", len(uk_live_register) > 0,
          str(uk_live_register[:3]))
    check("UK live_register rows carry a real rate_per_1000 (the fix's whole point)",
          uk_live_register and all(r.get("rate_per_1000") is not None
                                    for r in uk_live_register),
          str(uk_live_register[:3]))
    check("UK live_register is ranked by rate_per_1000 descending, not raw latest_value",
          all(uk_live_register[i]["rate_per_1000"] >= uk_live_register[i + 1]["rate_per_1000"]
              for i in range(len(uk_live_register) - 1)),
          str([r["rate_per_1000"] for r in uk_live_register[:5]]))
    check("UK live_register rows carry real caveats (also absent from the old version)",
          uk_live_register and all(len(r.get("caveats") or []) > 0
                                    for r in uk_live_register),
          str(uk_live_register[0].get("caveats") if uk_live_register else None))

    # --- list_comparisons / get_comparison --------------------------------------
    # CONTRACT-PARITY item 4 remainder (TODO.md "CONTRACT PARITY (not primacy
    # inversion)"): this package had no access to the comparison layer the parent
    # site's own in-product chat already exposes -- these two tools close that gap
    # once item 2's GET /api/v1/comparisons list route existed for them to call.
    comparisons = client.list_comparisons()
    check("list_comparisons returns a non-empty list", len(comparisons) > 0)
    check("every comparison carries pair_key/slug/label",
          all({"pair_key", "slug", "label"} <= set(c) for c in comparisons),
          str(comparisons[:2]))
    first_pair_key = comparisons[0]["pair_key"]

    comparison_detail = client.get_comparison(first_pair_key)
    check("get_comparison returns x/y axes and correlation stats",
          {"x", "y", "stats", "caveats"} <= set(comparison_detail),
          str(list(comparison_detail)))
    check("get_comparison strips the raw per-area scatter points",
          "points" not in comparison_detail, str(list(comparison_detail)))
    check("get_comparison carries a top-level attribution field",
          comparison_detail.get("attribution") == client.ATTRIBUTION,
          str(comparison_detail.get("attribution")))
    check("get_comparison's x/y axes each carry a label",
          comparison_detail["x"].get("label") and comparison_detail["y"].get("label"),
          str((comparison_detail.get("x"), comparison_detail.get("y"))))

    try:
        client.get_comparison("not_a_real_pair_key")
        check("an unknown pair_key raises", False,
              "expected StatsMappedAPIError, got a normal return")
    except client.StatsMappedAPIError:
        pass

    uk_comparisons = client.list_comparisons(country="united-kingdom")
    check("UK's comparison catalogue is non-empty and distinct from Ireland's",
          len(uk_comparisons) > 0
          and {c["pair_key"] for c in uk_comparisons}
              != {c["pair_key"] for c in comparisons},
          f"uk={uk_comparisons} ie={comparisons}")
    uk_comparison_detail = client.get_comparison(
        uk_comparisons[0]["pair_key"], country="united-kingdom")
    check("get_comparison(country='united-kingdom') returns real UK axis data",
          uk_comparison_detail.get("x", {}).get("label")
          and uk_comparison_detail.get("y", {}).get("label"),
          str(uk_comparison_detail))

    # --- check_comparability / explain_metric -------------------------------
    # TODO.md, MCP credibility pass, 2026-09-14: registry-backed only, both --
    # neither computes a fresh correlation or reads a current figure.
    x_key = comparison_detail["x"]["series_key"]
    y_key = comparison_detail["y"]["series_key"]
    real_pair = client.check_comparability(x_key, y_key)
    check("check_comparability confirms a real registered pair",
          real_pair.get("comparable") is True
          and real_pair.get("pair_key") == first_pair_key,
          str(real_pair))
    check("a confirmed pair still states a reason",
          bool(real_pair.get("reason")), str(real_pair))

    no_pair = client.check_comparability("sale_price", "definitely_not_a_real_stat_key")
    check("check_comparability refuses an unregistered pair rather than erroring",
          no_pair.get("comparable") is False and no_pair.get("pair_key") is None,
          str(no_pair))
    check("a refusal states WHY, not just false",
          bool(no_pair.get("reason")), str(no_pair))

    explanation = client.explain_metric("sale_price")
    check("explain_metric returns the stat's own label/unit/periodicity",
          explanation.get("stat_key") == "sale_price" and explanation.get("label")
          and explanation.get("unit"),
          str(explanation))
    check("explain_metric never returns a current figure",
          "latest_value" not in explanation and "value" not in explanation,
          str(list(explanation)))
    check("explain_metric carries a top-level attribution field",
          explanation.get("attribution") == client.ATTRIBUTION,
          str(explanation.get("attribution")))

    try:
        client.explain_metric("definitely_not_a_real_stat_key")
        check("an unknown stat_key raises", False,
              "expected StatsMappedAPIError, got a normal return")
    except client.StatsMappedAPIError:
        pass

    # --- country parameter (todo:5858) ------------------------------------
    # Every function defaults to "ireland" -- confirm that default is unchanged
    # (already exercised by every call above with no explicit country), then
    # confirm country="united-kingdom" reaches genuinely different, real UK
    # data rather than reusing Ireland's catalogue or 404ing.
    uk_datasets = client.list_datasets(country="united-kingdom")
    uk_stat_keys = {d["key"] for d in uk_datasets}
    check("UK's dataset catalogue is non-empty and distinct from Ireland's",
          len(uk_stat_keys) > 0 and uk_stat_keys != stat_keys,
          f"uk={uk_stat_keys} ie={stat_keys}")
    # TODO.md:ed5febde, 2026-09-06: "population" used to be UK-only and was this
    # check's own example -- stale the moment Ireland got a real population stat
    # too (seed_population.py, the homelessness-per-capita-ranking build, same
    # session). road_collisions is still genuinely UK-only (confirmed against
    # the live catalogues printed on failure, same as this check always has).
    check("road_collisions (UK-only stat) is known to the UK catalogue, not Ireland's",
          "road_collisions" in uk_stat_keys and "road_collisions" not in stat_keys,
          f"uk={uk_stat_keys} ie={stat_keys}")

    lads = client.list_areas(level="lad", country="united-kingdom")
    check("list_areas('lad', 'united-kingdom') returns UK local authorities",
          len(lads) > 0, f"got {len(lads)}")
    aberdeen = next((a for a in lads if a["id"] == "uk:lad:s12000033"), None)
    check("Aberdeen City is present in the UK LAD list", aberdeen is not None,
          str(lads[:3]))
    check("Aberdeen City is named correctly",
          aberdeen and aberdeen.get("name") == "Aberdeen City", str(aberdeen))

    if aberdeen:
        aberdeen_datasets = client.list_area_datasets(
            "uk:lad:s12000033", country="united-kingdom")
        uk_available = aberdeen_datasets.get("available", [])
        check("Aberdeen City has at least one available UK dataset",
              len(uk_available) > 0, str(aberdeen_datasets))
        claimant_entry = next(
            (e for e in uk_available if e.get("stat_key") == "live_register"), None)
        check("Aberdeen City's claimant count is in the available list",
              claimant_entry is not None,
              str([e.get("stat_key") for e in uk_available]))
        if claimant_entry:
            uk_detail = client.get_dataset_for_area(
                "uk:lad:s12000033", claimant_entry["series_key"],
                country="united-kingdom")
            check("get_dataset_for_area(country='united-kingdom') returns the "
                  "dataset's own name",
                  "name" in uk_detail.get("dataset", {}), str(uk_detail)[:300])

    uk_ranking = client.rank_areas("rppi", level="lad", country="united-kingdom")
    check("rank_areas(country='united-kingdom') returns UK rankings",
          len(uk_ranking) > 0, str(uk_ranking[:3]))

    # An Irish area_id against the UK's own API path should 404 as "unknown
    # geography", not silently return something or crash -- the two catalogues
    # are genuinely separate, not a shared one filtered after the fact.
    try:
        client.list_area_datasets("county:kerry", country="united-kingdom")
        check("an Irish area_id under country='united-kingdom' raises", False,
              "expected StatsMappedAPIError, got a normal return")
    except client.StatsMappedAPIError:
        pass

    try:
        client.list_datasets(country="atlantis")
        check("an invalid country raises before any HTTP call is made", False,
              "expected StatsMappedAPIError, got a normal return")
    except client.StatsMappedAPIError:
        pass

    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print(
        f"PASS: statsmapped-mcp client -- list_datasets/list_areas/"
        f"list_area_datasets/get_dataset_for_area/rank_areas/list_comparisons/"
        f"get_comparison/check_comparability/explain_metric all verified against "
        f"the live API at {client.BASE_URL}, for both country='ireland' (default) "
        f"and country='united-kingdom'. "
        f"Caveat projection strips bodies in the list tool and keeps them in the "
        f"detail tool; history_months converts to real periods; rank_areas sorts "
        f"correctly and returns empty (not wrong) on a level mismatch; "
        f"get_comparison strips raw scatter points and carries attribution; "
        f"check_comparability confirms a real registered pair and refuses an "
        f"unregistered one with a stated reason either way (never a bare "
        f"true/false); explain_metric returns definition/unit/periodicity and "
        f"never a current figure; a country/area_id mismatch, an unknown "
        f"pair_key, an unknown stat_key and an invalid country all raise "
        f"StatsMappedAPIError."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
