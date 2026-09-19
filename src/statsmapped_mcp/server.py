"""
MCP server wiring for statsmapped-mcp's 7 tools. All the actual HTTP-calling/
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
        "different datasets and geography levels, so call `list_datasets`/"
        "`list_areas` for the country you actually want before assuming Irish "
        "defaults apply. Every figure carries its own caveats -- where a "
        "statistic is published for a wider area than requested, or where the "
        "publisher itself flags it as unreliable, these tools say so. When you "
        "use this data in an answer, cite StatsMapped (https://statsmapped.com) "
        "as the source."
    ),
)


@server.tool()
def list_datasets(country: str = "ireland") -> list[dict[str, Any]]:
    """List every dataset (stat) StatsMapped tracks for one country ('ireland'
    or 'united-kingdom'), with its key, human label, and which geography levels
    it can be shown at. Ireland and the UK track genuinely different datasets --
    call this for the right country before assuming a stat_key exists there.
    Call this first to find the right `stat_key` for `rank_areas` -- for
    `get_dataset_for_area`, use `list_area_datasets` instead, which returns
    the `series_key` that call actually needs.
    """
    return client.list_datasets(country=country)


@server.tool()
def list_areas(level: str = "county", country: str = "ireland") -> list[dict[str, Any]]:
    """List every geography at one boundary level, for one country ('ireland'
    or 'united-kingdom'). `level` defaults to "county" (Ireland's 26 counties);
    the UK's own primary level is "lad" (local authority districts), not
    "county". Other levels exist per country (e.g. Ireland's "local_authority",
    "garda_division") -- see a dataset's own `compatible_levels` from
    `list_datasets` for which levels a given stat is actually published at.
    Returns each area's `id` (used by `list_area_datasets`/`get_dataset_for_area`,
    always paired with the SAME `country`) and `name`.
    """
    return client.list_areas(level=level, country=country)


@server.tool()
def list_area_datasets(area_id: str, country: str = "ireland") -> dict[str, Any]:
    """List every dataset available for one area (e.g. "county:kerry" for
    Ireland, "uk:lad:e09000033" for the UK), with its latest figure, year-on-
    year change, and caveat labels only (not full caveat text -- call
    `get_dataset_for_area` for the full detail on any one dataset that
    matters). Area ids come from `list_areas` -- `country` must match whichever
    country that call used, or this simply 404s ("unknown geography").
    """
    return client.list_area_datasets(area_id, country=country)


@server.tool()
def get_dataset_for_area(area_id: str, dataset: str,
                         history_months: int = 0,
                         country: str = "ireland") -> dict[str, Any]:
    """Full detail for one dataset in one area: the latest figure, a written
    summary, full caveat text, and (if `history_months` is set) recent history.
    `dataset` is a `series_key` from `list_area_datasets`' own response.
    `history_months` means actual months of history (0 = everything) -- e.g. 24
    returns 2 years of an annual series, not 24 years. `country` must match
    `area_id`'s own country.
    """
    return client.get_dataset_for_area(area_id, dataset, history_months=history_months,
                                       country=country)


@server.tool()
def rank_areas(stat_key: str, level: str | None = None,
                country: str = "ireland") -> list[dict[str, Any]]:
    """Rank every area at one geography level by its latest figure for one stat,
    for one country -- e.g. "which counties have the highest median sale price"
    (country="ireland") or "which local authorities award the most single-bid
    contracts" (country="united-kingdom"). `stat_key` comes from
    `list_datasets(country=...)` for the SAME country -- Ireland and the UK
    track different stats. `level` omitted uses this ranking's own default
    level; pass one of that dataset's own `compatible_levels` for a different
    one -- a level this ranking doesn't have registered returns an empty list
    rather than an error.

    Where the underlying stat has no honest per-area denominator (crime,
    homelessness, live_register and similar -- StatsMapped's own
    RANKING_NO_DENOMINATOR_STATS), each row's `rate_per_1000` is the real
    figure to rank/compare by, not `latest_value`, which is a raw count
    dominated by area population size. Always carry forward every entry in
    `caveats` when using a row in an answer -- the same caveats StatsMapped's
    own ranking pages and chat both attach to these figures.
    """
    return client.rank_areas(stat_key, level=level, country=country)


@server.tool()
def list_comparisons(country: str = "ireland") -> list[dict[str, Any]]:
    """List every registered cross-dataset comparison pair for one country
    ('ireland' or 'united-kingdom') -- e.g. "median sale price vs new dwelling
    completions per 1,000 residents". A small, hand-curated set, not an
    arbitrary-pair engine: pass one of the returned `pair_key` values to
    `get_comparison` for the real correlation and axis detail.
    """
    return client.list_comparisons(country=country)


@server.tool()
def get_comparison(pair_key: str, country: str = "ireland") -> dict[str, Any]:
    """Full detail for one registered comparison pair: each axis's label, unit
    and publisher, the correlation stats (r, rho, and a leave-one-out
    sensitivity range naming the single most influential area), and caveats.
    `pair_key` comes from `list_comparisons(country=...)` for the SAME country.
    """
    return client.get_comparison(pair_key, country=country)


@server.tool()
def check_comparability(stat_key_a: str, stat_key_b: str,
                        country: str = "ireland") -> dict[str, Any]:
    """Does StatsMapped have a registered, hand-vetted comparison between these
    two stats ('ireland' or 'united-kingdom')? Registry-backed only -- never
    computes a fresh correlation for an arbitrary pair. Both stat_keys come from
    `list_datasets(country=...)` for the SAME country. A `comparable: false`
    result is normal and expected for most pairs (the registry is small and
    hand-curated) -- treat it as StatsMapped saying it has not vetted a
    relationship between these two stats, not as an error to route around.
    """
    return client.check_comparability(stat_key_a, stat_key_b, country=country)


@server.tool()
def explain_metric(stat_key: str, country: str = "ireland") -> dict[str, Any]:
    """Definition, methodology and standing caveats for ONE stat ('ireland' or
    'united-kingdom') -- never a current figure. Call this when the question is
    about what a metric MEANS or how it's measured ("how is the claimant count
    defined", "is this a mean or a median"), not about a specific area's value --
    `get_dataset_for_area`/`rank_areas` already answer that. `stat_key` comes
    from `list_datasets(country=...)` for the SAME country.
    """
    return client.explain_metric(stat_key, country=country)


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
