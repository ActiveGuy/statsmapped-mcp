"""
`server.py`'s `query_data`/`compare` mode-dispatch logic -- PURE (no network;
monkeypatches `client`'s underlying functions to record which one got called
with what arguments, rather than hitting the real API).

WHY THIS EXISTS. wl:b7bd15daaabf: consolidated 9 tools down to 4 by merging
several single-purpose tools behind two mode-dispatching ones (`query_data`,
`compare`). `client.py`'s own granular functions (list_datasets,
list_area_datasets, get_dataset_for_area, rank_areas, list_comparisons,
get_comparison, check_comparability) are UNCHANGED and already covered by
test_client.py's real-API checks -- this file's job is narrower: does
`server.py`'s dispatch logic route each combination of arguments to the
RIGHT underlying function, and does it refuse an ambiguous combination
rather than silently guessing.

Run:
    python -m pytest tests/test_tool_consolidation.py -v
or, dependency-free:
    python tests/test_tool_consolidation.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import server

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def main() -> int:
    # ==== query_data ============================================================
    with patch.object(server.client, "list_datasets", return_value=["A"]) as m_ld, \
         patch.object(server.client, "list_area_datasets", return_value=["B"]) as m_lad, \
         patch.object(server.client, "get_dataset_for_area", return_value=["C"]) as m_gdfa, \
         patch.object(server.client, "log_tool_call"):

        # ---- 1. Neither area_id nor dataset -> list_datasets. ---------------------
        result = server.query_data(country="ireland")
        check("no area_id/dataset dispatches to list_datasets",
              m_ld.called and not m_lad.called and not m_gdfa.called)
        check("list_datasets is called with the right country",
              m_ld.call_args.kwargs.get("country") == "ireland")
        check("the result is list_datasets' own return value",
              result == ["A"])

        m_ld.reset_mock()

        # ---- 2. area_id given, dataset omitted -> list_area_datasets. -------------
        result = server.query_data(area_id="county:kerry", country="ireland")
        check("area_id alone dispatches to list_area_datasets",
              m_lad.called and not m_ld.called and not m_gdfa.called)
        check("list_area_datasets is called with the right area_id",
              m_lad.call_args.args[0] == "county:kerry"
              or m_lad.call_args.kwargs.get("area_id") == "county:kerry")
        check("the result is list_area_datasets' own return value",
              result == ["B"])

        m_lad.reset_mock()

        # ---- 3. Both area_id and dataset -> get_dataset_for_area. -----------------
        result = server.query_data(area_id="county:kerry", dataset="sale_price",
                                       history_months=24, country="ireland")
        check("area_id + dataset dispatches to get_dataset_for_area",
              m_gdfa.called and not m_ld.called and not m_lad.called)
        check("get_dataset_for_area is called with history_months forwarded",
              m_gdfa.call_args.kwargs.get("history_months") == 24)
        check("the result is get_dataset_for_area's own return value",
              result == ["C"])

    # ==== compare ================================================================
    with patch.object(server.client, "rank_areas", return_value=["R"]) as m_ra, \
         patch.object(server.client, "get_comparison", return_value=["G"]) as m_gc, \
         patch.object(server.client, "check_comparability", return_value=["K"]) as m_cc, \
         patch.object(server.client, "list_comparisons", return_value=["L"]) as m_lc, \
         patch.object(server.client, "log_tool_call"):

        # ---- 4. stat_key alone -> rank_areas. --------------------------------------
        result = server.compare(stat_key="sale_price", country="ireland")
        check("stat_key alone dispatches to rank_areas",
              m_ra.called and not any(m.called for m in (m_gc, m_cc, m_lc)))
        check("the result is rank_areas' own return value", result == ["R"])
        m_ra.reset_mock()

        # ---- 5. pair_key alone -> get_comparison. ----------------------------------
        result = server.compare(pair_key="sale_price_x_completions", country="ireland")
        check("pair_key alone dispatches to get_comparison",
              m_gc.called and not any(m.called for m in (m_ra, m_cc, m_lc)))
        check("the result is get_comparison's own return value", result == ["G"])
        m_gc.reset_mock()

        # ---- 6. stat_key_a + stat_key_b -> check_comparability. --------------------
        result = server.compare(stat_key_a="crime", stat_key_b="population",
                                    country="ireland")
        check("stat_key_a + stat_key_b dispatches to check_comparability",
              m_cc.called and not any(m.called for m in (m_ra, m_gc, m_lc)))
        check("the result is check_comparability's own return value", result == ["K"])
        m_cc.reset_mock()

        # ---- 7. None given -> list_comparisons. ------------------------------------
        result = server.compare(country="ireland")
        check("no mode arguments dispatches to list_comparisons",
              m_lc.called and not any(m.called for m in (m_ra, m_gc, m_cc)))
        check("the result is list_comparisons' own return value", result == ["L"])

    # ==== compare's error-on-ambiguity cases ====================================
    with patch.object(server.client, "rank_areas"), \
         patch.object(server.client, "get_comparison"), \
         patch.object(server.client, "check_comparability"), \
         patch.object(server.client, "list_comparisons"), \
         patch.object(server.client, "log_tool_call"):

        # ---- 8. stat_key AND pair_key both given -> raises, never silently picks one.
        raised = False
        try:
            server.compare(stat_key="sale_price", pair_key="some_pair")
        except ValueError:
            raised = True
        check("stat_key + pair_key together raises ValueError rather than "
              "silently picking one mode", raised)

        # ---- 9. Only stat_key_a given, stat_key_b omitted -> raises. ---------------
        raised = False
        try:
            server.compare(stat_key_a="crime")
        except ValueError:
            raised = True
        check("stat_key_a without stat_key_b raises ValueError rather than "
              "silently treating it as some other mode", raised)

        # ---- 10. Only stat_key_b given, stat_key_a omitted -> raises. --------------
        raised = False
        try:
            server.compare(stat_key_b="population")
        except ValueError:
            raised = True
        check("stat_key_b without stat_key_a raises ValueError", raised)

        # ---- 11. R1's finding: level given without stat_key -> raises rather than
        #      silently dropping it and falling through to list_comparisons. --------
        raised = False
        try:
            server.compare(level="lea")
        except ValueError:
            raised = True
        check("level without stat_key raises ValueError rather than silently "
              "dispatching to list_comparisons with level dropped", raised)

    # ==== R1's other two findings: query_data's own silent-argument-drop cases =
    with patch.object(server.client, "list_datasets", return_value=["A"]) as m_ld, \
         patch.object(server.client, "list_area_datasets", return_value=["B"]) as m_lad, \
         patch.object(server.client, "get_dataset_for_area", return_value=["C"]) as m_gdfa, \
         patch.object(server.client, "log_tool_call"):

        # ---- 12. dataset given without area_id -> raises rather than silently
        #      dropping dataset and returning mode 1's unrelated dataset list. -----
        raised = False
        try:
            server.query_data(dataset="sale_price")
        except ValueError:
            raised = True
        check("dataset without area_id raises ValueError rather than silently "
              "dropping it and returning the full dataset list", raised)
        check("no underlying client function was called on the raise",
              not any(m.called for m in (m_ld, m_lad, m_gdfa)))

        # ---- 13. history_months given without area_id (or dataset) -> raises. -----
        raised = False
        try:
            server.query_data(history_months=24)
        except ValueError:
            raised = True
        check("history_months without area_id raises ValueError rather than "
              "silently dispatching to list_datasets with it dropped", raised)

        # ---- 14. R1's residual finding (round 2): area_id + history_months, but
        #      dataset omitted -> must ALSO raise. The first fix checked
        #      history_months against area_id alone, which missed this exact case
        #      (area_id given, dataset not) -- silently dispatched to mode 2
        #      (list_area_datasets), dropping history_months. Confirmed live by
        #      R1 executing it, not just reading the code. -----------------------
        raised = False
        try:
            server.query_data(area_id="county:kerry", history_months=24)
        except ValueError:
            raised = True
        check("area_id + history_months WITHOUT dataset still raises -- the "
              "exact gap the first fix's area_id-only check missed",
              raised)
        check("no underlying client function was called on that raise either",
              not any(m.called for m in (m_ld, m_lad, m_gdfa)))

    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print(
        "PASS: query_data/compare dispatch -- 25 checks. query_data's 3 modes "
        "(list all / list for one area / full detail) each route to the right "
        "underlying client function with the right arguments; compare's 4 modes "
        "(rank / pair detail / comparability check / list all) do the same; and "
        "both refuse an ambiguous OR an incomplete/orphaned argument combination "
        "(mixed modes, a half-given pair, or a mode-specific argument given "
        "without its mode -- level without stat_key, dataset/history_months "
        "without area_id) with a clear error rather than silently dropping the "
        "argument and dispatching to the wrong mode (R1's review, 3 real cases). "
        "No network -- client's underlying functions are all mocked."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
