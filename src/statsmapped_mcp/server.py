"""
MCP server wiring for statsmapped-mcp's tools (9 originally, consolidated to 4
-- query_data, list_areas, compare, explain_metric -- via wl:b7bd15daaabf's
mechanical merge; list_areas itself still stands alone pending a separate,
larger resolve_place redesign that isn't scoped yet). All the actual HTTP-calling/
response-shaping logic lives in `client.py`, kept separate and independently
testable -- this module is just the MCP registration layer.

Run directly (`python -m statsmapped_mcp.server`) or via the `statsmapped-mcp`
console script this package installs. Stdio by default, unchanged for local/
Desktop use -- set MCP_TRANSPORT=streamable-http (TODO.md PRIORITY 9, live
PageSpeed report, 2026-09-06) to run a real hosted HTTP endpoint instead, e.g.
for a Render deployment. See this package's own README for the load-sharing
risk a hosted endpoint reintroduces (stdio's real advantage was never auth --
`/api/v1` is public, unauthenticated data either way -- it was that each
user's own machine makes the HTTP calls, so N users' cost is naturally spread
across N source IPs; a hosted endpoint collapses that to one shared egress IP
and one shared 600/hr rate-limit bucket, `rate_limit_public_api`, api.py).
Accepted as a v1 tradeoff, watched via `fail_open_count()`/`decisions` gate
rows rather than solved with per-session rate-limit keying up front.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import RedirectResponse

from statsmapped_mcp import client

server = MCPServer(
    name="statsmapped",
    title="StatsMapped Public Data",
    description=(
        "Public data for Ireland and the UK, by county/local authority: housing, "
        "crime, health, the economy and social welfare, from official publishers "
        "(CSO, PSRA, Central Bank of Ireland, DHLGH, NTPF, the Office of "
        "Government Procurement, EU Publications Office for Ireland; ONS/Land "
        "Registry-sourced series for the UK), updated on each publisher's own "
        "schedule. Every tool below takes a `country` argument ('ireland' or "
        "'united-kingdom', default 'ireland') -- the two countries track "
        "different datasets and geography levels, so call `query_data`/"
        "`list_areas` for the country you actually want before assuming Irish "
        "defaults apply. Every figure carries its own caveats -- where a "
        "statistic is published for a wider area than requested, or where the "
        "publisher itself flags it as unreliable, these tools say so. When you "
        "use this data in an answer, cite StatsMapped (https://statsmapped.com) "
        "as the source."
    ),
)


# wl:1bea0f7c116a (developer decision via EA, 2026-09-25, after EA's own
# discovery check): the advertised hosted address, https://mcp.statsmapped.com,
# 404s at its own bare root -- the SDK's streamable-http transport mounts the
# real protocol endpoint at /mcp by default (run_streamable_http_async's own
# streamable_http_path="/mcp"), never at "/", and nothing served the root
# before this. A redirect, not a second copy of the protocol endpoint --
# there is exactly one real MCP endpoint (/mcp); the bare host is a courtesy
# for a client or a person that tries the advertised address literally as
# written, without a path.
#
# Only meaningful for the hosted (streamable-http) deployment -- in stdio mode
# (the default, no HTTP server ever runs) this route is registered but never
# actually served, since server.run() only builds a Starlette app for
# sse/streamable-http transports. Harmless to register unconditionally rather
# than gating it on MCP_TRANSPORT: registering a route that streamable_http_
# app() never mounts costs nothing.
@server.custom_route("/", methods=["GET"])
async def root_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/mcp")


@server.tool()
def query_data(area_id: str | None = None, dataset: str | None = None,
               history_months: int = 0,
               country: str = "ireland") -> list[dict[str, Any]] | dict[str, Any]:
    """Three modes, depending on which of `area_id`/`dataset` are given --
    consolidates what were three separate tools (list_datasets,
    list_area_datasets, get_dataset_for_area) behind one, since they are all
    really "how do I get data" at different levels of specificity:

    1. Neither `area_id` nor `dataset`: lists every dataset (stat) StatsMapped
       tracks for one country ('ireland' or 'united-kingdom'), with its key,
       human label, and which geography levels it can be shown at. Ireland and
       the UK track genuinely different datasets -- call this first for the
       right country before assuming a stat_key exists there, to find the
       right `stat_key` for `compare`'s ranking mode.
    2. `area_id` given, `dataset` omitted: lists every dataset available for
       that one area (e.g. "county:kerry" for Ireland, "uk:lad:e09000033" for
       the UK), with its latest figure, year-on-year change, and caveat labels
       only (not full caveat text -- use mode 3 for the full detail on any one
       dataset that matters). `area_id` comes from `list_areas`; `country`
       must match whichever country that call used, or this simply 404s
       ("unknown geography").
    3. Both `area_id` and `dataset` given: full detail for one dataset in one
       area -- the latest figure, a written summary, full caveat text, and (if
       `history_months` is set) recent history. `dataset` is a `series_key`
       from mode 2's own response. `history_months` means actual months of
       history (0 = everything) -- e.g. 24 returns 2 years of an annual
       series, not 24 years. `country` must match `area_id`'s own country.

       `dataset` and `history_months` are only meaningful together with
       `area_id` (and, for `history_months`, `dataset` too, since it only
       applies to mode 3); giving either without its real precondition
       raises rather than silently dropping the argument and dispatching to
       the wrong mode.
    """
    if dataset is not None and area_id is None:
        raise ValueError("query_data()'s `dataset` argument needs `area_id` too "
                          "-- it selects one dataset WITHIN one area, and means "
                          "nothing without knowing which area.")
    if history_months and dataset is None:
        raise ValueError("query_data()'s `history_months` argument needs `dataset` "
                          "(and `area_id`) too -- it only applies to mode 3's "
                          "single-dataset-in-one-area detail, checked against "
                          "`dataset` specifically since `area_id` alone (mode 2) "
                          "doesn't return per-dataset history either.")
    if area_id is None:
        result = client.list_datasets(country=country)
    elif dataset is None:
        result = client.list_area_datasets(area_id, country=country)
    else:
        result = client.get_dataset_for_area(area_id, dataset, history_months=history_months,
                                             country=country)
    client.log_tool_call("query_data", country)
    return result


@server.tool()
def list_areas(level: str = "county", country: str = "ireland") -> list[dict[str, Any]]:
    """List every geography at one boundary level, for one country ('ireland'
    or 'united-kingdom'). `level` defaults to "county" (Ireland's 26 counties);
    the UK's own primary level is "lad" (local authority districts), not
    "county". Other levels exist per country (e.g. Ireland's "local_authority",
    "garda_division") -- see a dataset's own `compatible_levels` from
    `query_data` for which levels a given stat is actually published at.
    Returns each area's `id` (used by `query_data`'s area-scoped modes,
    always paired with the SAME `country`) and `name`.
    """
    result = client.list_areas(level=level, country=country)
    client.log_tool_call("list_areas", country)
    return result


@server.tool()
def compare(stat_key: str | None = None, level: str | None = None,
            pair_key: str | None = None,
            stat_key_a: str | None = None, stat_key_b: str | None = None,
            country: str = "ireland") -> list[dict[str, Any]] | dict[str, Any]:
    """Four modes, depending on which arguments are given -- consolidates what
    were four separate tools (rank_areas, list_comparisons, get_comparison,
    check_comparability) behind one, since they are all really "how does this
    stat compare" at different scopes. Exactly one mode's arguments should be
    given; mixing arguments from different modes (e.g. both `stat_key` and
    `pair_key`, or only one of `stat_key_a`/`stat_key_b`) raises an error
    rather than silently guessing which mode was meant.

    1. `stat_key` alone (no `pair_key`, no `stat_key_a`/`stat_key_b`): ranks
       every area at one geography level by its latest figure for that stat,
       for one country -- e.g. "which counties have the highest median sale
       price" (country="ireland"). `stat_key` comes from `query_data`'s
       dataset-listing mode, for the SAME country. `level` omitted uses this
       ranking's own default level; pass one of that dataset's own
       `compatible_levels` for a different one -- a level this ranking
       doesn't have registered returns an empty list rather than an error.
       Where the underlying stat has no honest per-area denominator (crime,
       homelessness, live_register and similar -- StatsMapped's own
       RANKING_NO_DENOMINATOR_STATS), each row's `rate_per_1000` is the real
       figure to rank/compare by, not `latest_value`, which is a raw count
       dominated by area population size. Always carry forward every entry
       in `caveats` when using a row in an answer.
    2. `pair_key` alone: full detail for one registered comparison pair --
       each axis's label, unit and publisher, the correlation stats (r, rho,
       and a leave-one-out sensitivity range naming the single most
       influential area), and caveats. `pair_key` comes from mode 4's own
       response, for the SAME country.
    3. Both `stat_key_a` and `stat_key_b` given: does StatsMapped have a
       registered, hand-vetted comparison between these two stats?
       Registry-backed only -- never computes a fresh correlation for an
       arbitrary pair. Both stat_keys come from `query_data`'s dataset-
       listing mode, for the SAME country. `comparable` is one of `"yes"`
       (a real, hand-vetted registered pair -- only this case may be treated
       as a confirmed relationship), `"no"` (a real structural impossibility,
       the two stats share no geography level at all), or `"unknown"` (not
       registered, not ruled out either -- StatsMapped genuinely hasn't
       vetted this pair; never treat this as "probably comparable"). Read
       `reasons` before deciding how to present any answer other than `"yes"`.
    4. None of the above given: lists every registered cross-dataset
       comparison pair for one country -- e.g. "median sale price vs new
       dwelling completions per 1,000 residents". A small, hand-curated set,
       not an arbitrary-pair engine: pass one of the returned `pair_key`
       values to mode 2 for the real correlation and axis detail.

       `level` is only meaningful together with `stat_key` (mode 1); giving
       it without `stat_key` raises rather than silently dropping it and
       falling through to mode 4's unrelated pair listing.
    """
    modes_given = sum([
        stat_key is not None,
        pair_key is not None,
        stat_key_a is not None or stat_key_b is not None,
    ])
    if modes_given > 1:
        raise ValueError(
            "compare() takes arguments from exactly one mode: stat_key (rank), "
            "pair_key (comparison detail), or stat_key_a+stat_key_b "
            "(comparability check) -- got more than one of these.")
    if (stat_key_a is None) != (stat_key_b is None):
        raise ValueError(
            "compare()'s comparability-check mode needs BOTH stat_key_a and "
            "stat_key_b, not just one.")
    if level is not None and stat_key is None:
        raise ValueError(
            "compare()'s `level` argument needs `stat_key` too -- it only "
            "applies to the ranking mode.")

    if stat_key is not None:
        result = client.rank_areas(stat_key, level=level, country=country)
    elif pair_key is not None:
        result = client.get_comparison(pair_key, country=country)
    elif stat_key_a is not None:
        result = client.check_comparability(stat_key_a, stat_key_b, country=country)
    else:
        result = client.list_comparisons(country=country)
    client.log_tool_call("compare", country)
    return result


@server.tool()
def explain_metric(stat_key: str, country: str = "ireland") -> dict[str, Any]:
    """Definition, methodology and standing caveats for ONE stat ('ireland' or
    'united-kingdom') -- never a current figure. Call this when the question is
    about what a metric MEANS or how it's measured ("how is the claimant count
    defined", "is this a mean or a median"), not about a specific area's value --
    `query_data`/`compare` already answer that. `stat_key` comes
    from `query_data(country=...)` for the SAME country.
    """
    result = client.explain_metric(stat_key, country=country)
    client.log_tool_call("explain_metric", country)
    return result


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        server.run()
        return
    if transport not in ("sse", "streamable-http"):
        raise ValueError(
            f"MCP_TRANSPORT={transport!r} is not one of 'stdio'/'sse'/'streamable-http'")
    # TODO.md PRIORITY 9: "0.0.0.0" (not "127.0.0.1"/"localhost") is required on
    # Render, which assigns $PORT and expects binding on all interfaces --
    # PREP DOC FACT 9: the SDK's own DNS-rebinding protection only auto-
    # constructs a TransportSecuritySettings for a localhost host; for any other
    # host it stays None (i.e. NO Host/Origin validation at all) unless one is
    # passed explicitly, which is what MCP_ALLOWED_HOST is for below.
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    # Comma-separated, e.g. "mcp.statsmapped.com" -- the real public hostname is
    # a developer decision (subdomain vs. a path on the existing service; see
    # this item's own TODO.md entry), deliberately not guessed/hardcoded here.
    # enable_dns_rebinding_protection defaults True (the library's own default,
    # left on rather than overridden) -- with allowed_hosts/allowed_origins
    # BOTH empty (this env var unset), that FAILS CLOSED (every request
    # rejected) rather than failing open with no validation at all, so an
    # incomplete deploy config is loud, not a silent security gap.
    allowed = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOST", "").split(",") if h.strip()]
    transport_security = TransportSecuritySettings(
        allowed_hosts=allowed, allowed_origins=allowed)
    server.run(transport, host=host, port=port, transport_security=transport_security)


if __name__ == "__main__":
    main()
