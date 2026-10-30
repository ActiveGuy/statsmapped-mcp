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
import time
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
        "'united-kingdom', default 'ireland') — the two countries track "
        "different datasets and geography levels, so call `query_data`/"
        "`list_areas` for the country you actually want before assuming Irish "
        "defaults apply. Every figure carries its own caveats — where a "
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
               country: str = "ireland",
               stat_key: str | None = None,
               council: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    """Use when you need to find which datasets exist, which exist for one area, or the figures and history
    for one area and dataset (or a council planning view). For what a metric means use `explain_metric`;
    for how areas rank use `compare`.

    Three modes, depending on which of `area_id`/`dataset` are given (plus a planning mode, `council`, described last) --
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
       dataset that matters). Pass `stat_key` (from mode 1) to list only that
       stat's series for the area: a full listing is tens of KB, one stat is a
       few hundred bytes. `area_id` comes from `list_areas`; `country`
       must match whichever country that call used, or this simply 404s
       ("unknown geography").
    3. Both `area_id` and `dataset` given: full detail for one dataset in one
       area -- the latest figure, a written summary, full caveat text, and (if
       `history_months` is set) recent history. `dataset` is a `series_key`
       from mode 2's own response. `history_months` means actual months of
       history (0 = everything) -- e.g. 24 returns 2 years of an annual
       series, not 24 years. `country` must match `area_id`'s own country. A stat key from mode 1 is also
       accepted as `dataset` when the area has exactly one series for it (the reply says `resolved_from_stat_key`);
       with several, the error names the series keys to use.
    4. `council` alone (an Irish council slug, e.g. "cork-city-council"; country "ireland" only; no other argument): that council's planning
       applications by year received -- count, grant and refusal share of decided applications, median days to a decision -- with source, licence,
       the last data date, a receipt, plain notes, and typed `absences` instead of zeros. A council the national planning feed has stopped carrying
       (for example Cork City, last record 2025-11-04) says `status: "stopped_reporting"`: a low recent figure is a feed gap, not fewer applications.
       Example: query_data(council="cork-city-council").

       `dataset` and `history_months` are only meaningful together with
       `area_id` (and, for `history_months`, `dataset` too, since it only
       applies to mode 3); giving either without its real precondition
       raises rather than silently dropping the argument and dispatching to
       the wrong mode.
    """
    _t0 = time.monotonic()
    # todo:bcea278f: the whole body, including the argument-shape checks just
    # below, is inside this try -- a malformed call is as real a "status" fact
    # as a downstream fetch failure, and EA's ask was "status", not "status of
    # the fetch specifically".
    try:
        if council is not None:
            if area_id is not None or dataset is not None or stat_key is not None or history_months:
                raise ValueError("query_data()'s `council` argument is its own mode: give it alone (no area_id, dataset, stat_key or history_months).")
            if country != "ireland":
                raise ValueError("query_data()'s `council` mode covers Ireland only (country='ireland').")
            result = client.get_planning_summary(council, country=country)
            client.log_tool_call("query_data", country, "success", client.demand_params(council=council), client.answer_type_for(result), int((time.monotonic() - _t0) * 1000))
            return result
        if dataset is not None and area_id is None:
            raise ValueError("query_data()'s `dataset` argument needs `area_id` too "
                              "— it selects one dataset WITHIN one area, and means "
                              "nothing without knowing which area.")
        if stat_key is not None and (area_id is None or dataset is not None):
            raise ValueError("query_data()'s `stat_key` argument filters mode 2's area listing: "
                             "it needs `area_id` and no `dataset` (a dataset already names one series).")
        if history_months and dataset is None:
            raise ValueError("query_data()'s `history_months` argument needs `dataset` "
                              "(and `area_id`) too — it only applies to mode 3's "
                              "single-dataset-in-one-area detail, checked against "
                              "`dataset` specifically since `area_id` alone (mode 2) "
                              "doesn't return per-dataset history either.")
        if area_id is None:
            result = client.list_datasets(country=country)
        elif dataset is None:
            result = (client.list_area_datasets(area_id, country=country, stat_key=stat_key)
                      if stat_key is not None else client.list_area_datasets(area_id, country=country))
        else:
            result = client.get_dataset_for_area(area_id, dataset, history_months=history_months,
                                                 country=country)
    except Exception as exc:
        client.log_tool_call("query_data", country, "error", client.demand_params(stat_key=stat_key, council=council, area_id=area_id, dataset=dataset, history_months=history_months), client.answer_type_for(exc=exc), int((time.monotonic() - _t0) * 1000))
        raise
    client.log_tool_call("query_data", country, "success", client.demand_params(stat_key=stat_key, council=council, area_id=area_id, dataset=dataset, history_months=history_months), client.answer_type_for(result), int((time.monotonic() - _t0) * 1000))
    return result


@server.tool()
def list_areas(level: str = "county", country: str = "ireland",
               include_parents: bool = False) -> list[dict[str, Any]]:
    """Use when you need the ids and names of the areas (counties, local authorities, districts) to pass to
    `query_data`.

    List every geography at one boundary level, for one country ('ireland'
    or 'united-kingdom'). `level` defaults to "county" (Ireland's 26 counties);
    the UK's own primary level is "lad" (local authority districts), not
    "county". Other levels exist per country (e.g. Ireland's "local_authority",
    "garda_division") -- see a dataset's own `compatible_levels` from
    `query_data` for which levels a given stat is actually published at.
    Returns each area's `id` (used by `query_data`'s area-scoped modes,
    always paired with the SAME `country`), `name` and `level`. Slim by default;
    `include_parents=True` adds each area's `parents` (the regions it sits in)
    and Irish-language name.
    """
    _t0 = time.monotonic()
    try:
        result = (client.list_areas(level=level, country=country, include_parents=True)
                  if include_parents else client.list_areas(level=level, country=country))
    except Exception as exc:
        client.log_tool_call("list_areas", country, "error", client.demand_params(level=level), client.answer_type_for(exc=exc), int((time.monotonic() - _t0) * 1000))
        raise
    client.log_tool_call("list_areas", country, "success", client.demand_params(level=level), client.answer_type_for(result), int((time.monotonic() - _t0) * 1000))
    return result


@server.tool()
def compare(stat_key: str | None = None, level: str | None = None,
            pair_key: str | None = None,
            stat_key_a: str | None = None, stat_key_b: str | None = None,
            country: str = "ireland") -> list[dict[str, Any]] | dict[str, Any]:
    """Use when the question is how areas rank or compare on a stat, or whether two stats can be compared
    fairly. For one area's own figures use `query_data`.

    Four modes, depending on which arguments are given -- consolidates what
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
       registered, hand-vetted comparison between these two stats? Registry-
       backed only -- never computes a fresh correlation for an arbitrary
       pair. Both stat_keys come from `query_data`'s dataset-listing mode,
       for the SAME country. `verdict` is one of `"SUPPORT"` (a real,
       hand-vetted registered pair with no open caveats -- may be treated as
       a confirmed relationship), `"QUALIFY"` (hand-vetted, but the evidence
       carries real caveats -- e.g. no robustness check for outliers, or an
       unverified geography-level join; read `uncertainty` and `reasons`
       before presenting it as confirmed), `"REJECT"` (a real structural
       impossibility or a human-vetted "no" -- the two stats share no
       geography level at all, or a reviewer rejected this exact pairing),
       or `"INSUFFICIENT"` (not registered, not ruled out either --
       StatsMapped genuinely hasn't vetted this pair; never treat this as
       "probably comparable"). `uncertainty` names 4 separate dimensions
       (data_quality, comparability, statistical_strength,
       causal_strength) -- `causal_strength` is always `"not_established"`,
       since no comparison here implies causation regardless of verdict.
       `comparable` (DEPRECATED, kept only for callers that haven't
       migrated) collapses `verdict` to the old 3-way yes/no/unknown --
       `"yes"` for both `SUPPORT` and `QUALIFY` (both mean "hand-vetted",
       the old `comparable` meaning this field has always carried; the
       caveats a `QUALIFY` pair carries live in `uncertainty`/`reasons`,
       not in demoting `comparable`), `"no"` for `REJECT`, `"unknown"` for
       `INSUFFICIENT`. Prefer `verdict` directly when you need to
       distinguish a fully-confirmed `SUPPORT` from a caveated `QUALIFY`.
       Read `reasons` before presenting any answer other than `"SUPPORT"`
       as unqualified.
    4. None of the above given: lists every registered cross-dataset
       comparison pair for one country -- e.g. "median sale price vs new
       dwelling completions per 1,000 residents". A small, hand-curated set,
       not an arbitrary-pair engine: pass one of the returned `pair_key`
       values to mode 2 for the real correlation and axis detail.

       `level` is only meaningful together with `stat_key` (mode 1); giving
       it without `stat_key` raises rather than silently dropping it and
       falling through to mode 4's unrelated pair listing.
    """
    _t0 = time.monotonic()
    # todo:bcea278f: whole body in the try, same "a malformed call is a real
    # status too" reasoning as query_data()'s own comment above.
    try:
        modes_given = sum([
            stat_key is not None,
            pair_key is not None,
            stat_key_a is not None or stat_key_b is not None,
        ])
        if modes_given > 1:
            raise ValueError(
                "compare() takes arguments from exactly one mode: stat_key (rank), "
                "pair_key (comparison detail), or stat_key_a+stat_key_b "
                "(comparability check) — got more than one of these.")
        if (stat_key_a is None) != (stat_key_b is None):
            raise ValueError(
                "compare()'s comparability-check mode needs BOTH stat_key_a and "
                "stat_key_b, not just one.")
        if level is not None and stat_key is None:
            raise ValueError(
                "compare()'s `level` argument needs `stat_key` too — it only "
                "applies to the ranking mode.")

        if stat_key is not None:
            result = client.rank_areas(stat_key, level=level, country=country)
        elif pair_key is not None:
            result = client.get_comparison(pair_key, country=country)
        elif stat_key_a is not None:
            result = client.check_comparability(stat_key_a, stat_key_b, country=country)
        else:
            result = client.list_comparisons(country=country)
    except Exception as exc:
        client.log_tool_call("compare", country, "error", client.demand_params(stat_key=stat_key, level=level, pair_key=pair_key, stat_key_a=stat_key_a, stat_key_b=stat_key_b), client.answer_type_for(exc=exc), int((time.monotonic() - _t0) * 1000))
        raise
    client.log_tool_call("compare", country, "success", client.demand_params(stat_key=stat_key, level=level, pair_key=pair_key, stat_key_a=stat_key_a, stat_key_b=stat_key_b), client.answer_type_for(result), int((time.monotonic() - _t0) * 1000))
    return result


@server.tool()
def explain_metric(stat_key: str, country: str = "ireland") -> dict[str, Any]:
    """Use when the question is what a metric means or how it is measured; for a figure use `query_data`.

    Definition, methodology and standing caveats for ONE stat ('ireland' or
    'united-kingdom') -- never a current figure. Call this when the question is
    about what a metric MEANS or how it's measured ("how is the claimant count
    defined", "is this a mean or a median"), not about a specific area's value --
    `query_data`/`compare` already answer that. `stat_key` comes
    from `query_data(country=...)` for the SAME country.
    """
    _t0 = time.monotonic()
    try:
        result = client.explain_metric(stat_key, country=country)
    except Exception as exc:
        client.log_tool_call("explain_metric", country, "error", client.demand_params(stat_key=stat_key), client.answer_type_for(exc=exc), int((time.monotonic() - _t0) * 1000))
        raise
    client.log_tool_call("explain_metric", country, "success", client.demand_params(stat_key=stat_key), client.answer_type_for(result), int((time.monotonic() - _t0) * 1000))
    return result


@server.tool()
def get_scene(scene_id: str = "ireland-builds", purpose: str = "analytical", vintage: str | None = None,
              country: str = "ireland") -> dict[str, Any]:
    """Use when asked for a chart, still or short clip of a figure you can cite: returns the data to DRAW one scene, nothing rendered.

    Today one scene exists, "ireland-builds" (Ireland's homes
    granted permission, with a commencement notice and completed, by quarter from 2018Q1). The licence DIFFERS BY STAGE (see `licence.stages`): a stage whose licence is unconfirmed or
    ShareAlike is withheld (its cells are absences, not zeros) and the licence line names its holder. You get rows, a table twin, alt text, notes, `absences` (a missing figure is a typed
    absence, never a zero), the licence block, `scene_hash`, a `receipt` and the canonical URL. YOU draw it, and the last frame must match the table. Print the `scene_hash` and the licence
    `line` in the first, middle and last frame, quote only numbers that are in `rows`, do not loop, and keep the "stages are not a cohort" note. `purpose` is "analytical" (default) or
    "promotional": a promotional use of a source whose licence forbids advertising is refused (licence_refused). `vintage` (ISO date) omitted = the current data; an earlier vintage is
    not stored and returns unknown_vintage. Example: get_scene(scene_id="ireland-builds").
    """
    _t0 = time.monotonic()
    try:
        if purpose not in ("analytical", "promotional"):
            raise ValueError("get_scene()'s `purpose` must be 'analytical' or 'promotional'.")
        result = client.get_scene(scene_id, purpose=purpose, vintage=vintage, country=country)
    except Exception as exc:
        client.log_tool_call("get_scene", country, "error", client.demand_params(scene_id=scene_id, purpose=purpose), client.answer_type_for(exc=exc), int((time.monotonic() - _t0) * 1000))
        raise
    client.log_tool_call("get_scene", country, "success", client.demand_params(scene_id=scene_id, purpose=purpose), client.answer_type_for(result), int((time.monotonic() - _t0) * 1000))
    return result


@server.tool()
def notable_changes(limit: int = 8, stat_key: str | None = None, geography_id: str | None = None,
                    country: str = "ireland") -> dict[str, Any]:
    """Use when the question is what changed lately, which figures moved most, or what is new; for one area's full history use `query_data`.
    Returns statistical movements databeat flagged as notable, not verdicts on what they mean; `limit` is 1 to 50 (default 8), and `stat_key` or `geography_id` narrows the list.

    Ireland and united-kingdom. Cite StatsMapped (https://statsmapped.com) as the source. Source: GET /{country}/api/v1/alerts/notable.
    """
    _t0 = time.monotonic()
    try:
        result = client.get_notable_changes(limit=limit, stat_key=stat_key, geography_id=geography_id, country=country)
    except Exception as exc:
        client.log_tool_call("notable_changes", country, "error", client.demand_params(stat_key=stat_key), client.answer_type_for(exc=exc), int((time.monotonic() - _t0) * 1000))
        raise
    client.log_tool_call("notable_changes", country, "success", client.demand_params(stat_key=stat_key), client.answer_type_for(result), int((time.monotonic() - _t0) * 1000))
    return result


def _transport_security_allowlists(raw_allowed_host: str) -> tuple[list[str], list[str]]:
    """(allowed_hosts, allowed_origins) from the comma-separated MCP_ALLOWED_HOST
    env var. #887 (A7 audit, 9 Oct): these must NOT be the same list -- the SDK
    compares a request's real `Origin` header, which always carries a scheme
    (e.g. "https://mcp.statsmapped.com"), against `allowed_origins` verbatim.
    Confirmed live: a bare hostname in that list can never match, so every
    request carrying an Origin header was refused with 403 "Invalid Origin
    header" -- reproduced directly against production with curl, including the
    server's OWN exact origin. Only requests with no Origin header at all (stdio
    clients, most server-to-server callers) ever got through.

    SCOPE, stated explicitly (#887 finding 2's decision, R2C review): this fixes
    ONLY the scheme mismatch, so the server's own origin
    (https://<MCP_ALLOWED_HOST>) now matches. Cross-origin BROWSER clients (a web
    MCP client hosted elsewhere sends its own Origin, e.g. https://claude.ai) are
    still refused with 403 and are OUT OF SCOPE: widening allowed_origins to
    third-party origins is a deliberate security decision for EA or the developer,
    not made here. `allowed_hosts` stays bare
    (correct for Host-header matching); `allowed_origins` gets the scheme this
    one variable's own real-world shape always uses -- MCP_ALLOWED_HOST is
    deployed as a single bare hostname today (render.yaml), never a
    scheme-qualified value, so prefixing "https://" here is the real public
    value, not a guess.
    """
    allowed = [h.strip() for h in raw_allowed_host.split(",") if h.strip()]
    allowed_origins = [f"https://{h}" for h in allowed]
    return allowed, allowed_origins


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
    allowed, allowed_origins = _transport_security_allowlists(
        os.environ.get("MCP_ALLOWED_HOST", ""))
    transport_security = TransportSecuritySettings(
        allowed_hosts=allowed, allowed_origins=allowed_origins)
    server.run(transport, host=host, port=port, transport_security=transport_security)


if __name__ == "__main__":
    main()
