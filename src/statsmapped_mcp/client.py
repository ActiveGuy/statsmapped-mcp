"""
Pure HTTP-calling and response-shaping logic for the 7 MCP tools, kept separate
from `server.py`'s MCP/decorator wiring so it can be unit-tested as plain
functions (no MCP runtime needed) -- same "logic separate from framework
plumbing" split the parent StatsMapped project itself uses throughout
`databeat/api.py`.

Talks ONLY to StatsMapped's already-public, unauthenticated HTTPS API
(https://statsmapped.com/api/v1/*, documented at /openapi.json) -- this package
has no access to and no dependency on the StatsMapped repository's own database,
source code, or internals. It is a thin client an AI agent runs on the user's
own machine (stdio transport), calling the same API the site's own front end
does.

BASE_URL is overridable via the STATSMAPPED_MCP_BASE_URL environment variable --
mainly so this package's own tests can point at a local/staging instance rather
than hammering production on every test run, and so a user who ever needs to
point this at a different deployment (a future country, a self-hosted mirror)
can do so without a code change.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

BASE_URL = os.environ.get("STATSMAPPED_MCP_BASE_URL", "https://statsmapped.com")
TIMEOUT_SECONDS = 20.0
# Read from the installed package's own metadata rather than a hardcoded literal --
# a hardcoded string duplicating pyproject.toml's version drifts on the first release
# after this file stops being touched (api-product-consultant, 2026-09-19). Falls back
# to "dev" for an editable/uninstalled checkout rather than raising.
try:
    _PKG_VERSION = version("statsmapped-mcp")
except PackageNotFoundError:
    _PKG_VERSION = "dev"
USER_AGENT = f"statsmapped-mcp/{_PKG_VERSION} (+https://statsmapped.com)"

# 2026-08-30 (developer question -> api-product-consultant): nothing in this package
# told the calling LLM to credit StatsMapped when it uses this data in an answer.
# Plain text, not a markdown link -- the consultant's steer was that a link buried in
# a data field tends to get dropped in an LLM's own synthesis step, where a server-
# level instruction (this string, surfaced to the MODEL, not just the human reading
# raw JSON) is the mechanism actually likely to survive into a generated answer.
# One top-level field per response, not per-record -- today's own payload-size audit
# already flagged large unfiltered responses, and repeating this string per row in
# list_area_datasets' `available`/`not_comparable`/`national` arrays would add
# needless bytes for a fact that's true of the whole response, not any one row.
ATTRIBUTION = "Data from StatsMapped (https://statsmapped.com) -- cite as the source."


class StatsMappedAPIError(RuntimeError):
    """Raised on any non-2xx response, with the API's own error detail if it sent
    one -- so an agent calling a tool gets a legible reason (e.g. "unknown
    geography 'county:atlantis'") rather than a bare stack trace or HTTP status.

    `status_code` is carried as a real attribute (not just embedded in the
    message string) so a caller that needs to distinguish "not found" from
    "server error" -- rank_areas()'s own level-mismatch handling below is the
    first real consumer -- can check `exc.status_code == 404` rather than
    parsing this exception's own message text, which is meant for a human to
    read, not a program to pattern-match.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# todo:5858 (multi-agent-clearance triage, 2026-09-03): every call in this file used
# to hit the bare /api/v1/* path, which only ever reaches whichever country the
# SERVER happens to be booted as (Ireland, in production) -- there was no way for a
# tool caller to ask for UK data at all, not just a wording gap. `country` is now a
# real parameter on every tool/client function below, always resolved to the
# EXPLICIT /{country}/api/v1/* form -- confirmed on the parent site (StatsMapped's
# own /api landing page, 2026-09-03) that the bare and prefixed forms return
# byte-identical data for the same country, so defaulting to "ireland" here changes
# nothing for any existing caller that doesn't pass country.
VALID_COUNTRIES = {"ireland", "united-kingdom"}


def _api_path(suffix: str, country: str) -> str:
    if country not in VALID_COUNTRIES:
        raise StatsMappedAPIError(
            f"country must be one of {sorted(VALID_COUNTRIES)}, got {country!r}")
    return f"/{country}/api/v1{suffix}"


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    with httpx.Client(timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url, params=params or {})
    if resp.status_code >= 400:
        detail = None
        try:
            body = resp.json()
            detail = ((body.get("error") or {}).get("message")
                      or body.get("detail") or body)
        except ValueError:
            detail = resp.text[:300]
        raise StatsMappedAPIError(
            f"{resp.status_code} from {path}: {detail}", status_code=resp.status_code)
    return resp.json()


def list_datasets(country: str = "ireland") -> list[dict[str, Any]]:
    """Every stat StatsMapped tracks for one country -- key, label, which boundary
    levels it can be shown at. Ireland and the UK track different stats (18 vs.
    3 today), so this is genuinely per-country, not a shared catalogue filtered
    after the fact. Source: GET /{country}/api/v1/stats.
    """
    return _get(_api_path("/stats", country))


def list_areas(level: str = "county", country: str = "ireland") -> list[dict[str, Any]]:
    """Every geography StatsMapped knows about at one boundary level, for one
    country (default: Ireland's "county" -- the 26 counties; the UK's own
    primary level is "lad", its local authority districts). `with_boundary` is
    never requested: an agent needs the id/name to look datasets up by, not
    GeoJSON geometry. Source: GET /{country}/api/v1/geographies?level={level}.
    """
    rows = _get(_api_path("/geographies", country), params={"level": level})
    # Boundary/centroid are always absent already (with_boundary defaults to
    # false), but stripped explicitly in case that default ever changes --
    # this tool's whole point is staying small, not "small today".
    return [{k: v for k, v in row.items() if k not in ("boundary", "centroid")}
            for row in rows]


def _project_caveats(caveats: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Label + severity only, per this tool's own spec -- a caveat `body` can run
    to several sentences and this tool may return dozens of series for one area;
    an agent deciding WHETHER to look closer needs to know a caveat exists and
    how serious it is, not read the full text for every one up front. The full
    text is one `get_dataset_for_area` call away for whichever series turns out
    to matter.
    """
    return [{"label": c.get("label"), "severity": c.get("severity")}
            for c in (caveats or [])]


def _project_series_entry(entry: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "series_key": entry.get("series_key"),
        "display_name": entry.get("display_name"),
        "stat_key": entry.get("stat_key"),
        "unit": entry.get("unit"),
        "latest_period": entry.get("latest_period"),
        "latest_value": entry.get("latest_value"),
        "year_on_year_pct": entry.get("year_on_year_pct"),
        "caveats": _project_caveats(entry.get("caveats")),
    }
    if entry.get("geo_match") and entry["geo_match"] != "exact":
        # geo_match()'s own verdict -- an agent citing this figure for THIS area
        # needs to know it's actually published for a wider region, the same
        # disclosure the site's own pages carry (geographic_caveat()).
        projected["geo_match"] = entry["geo_match"]
        projected["geo_name"] = entry.get("geo_name")
    return projected


def list_area_datasets(area_id: str, country: str = "ireland") -> dict[str, Any]:
    """Every dataset available for one area, projected down to what an agent
    needs to decide which ones matter: name, latest figure, year-on-year change,
    and caveat labels/severity only (not full bodies -- see `_project_caveats`).
    Full detail for any ONE dataset is `get_dataset_for_area`, one call away.
    `country` must match whichever country `area_id` actually came from
    (`list_areas`' own `country` argument) -- an Irish area_id against
    country="united-kingdom" simply 404s, the API's own "unknown geography"
    behaviour, not a silently wrong answer.

    Source: GET /{country}/api/v1/geographies/{area_id}/series. Splits
    `available` from `not_comparable`/`national` exactly as the API itself does
    (architecture-design.md 4.8's own "a frontend cannot accidentally render
    them by ignoring a boolean" reasoning applies here too -- an agent should
    not accidentally cite a not-directly-comparable figure as this area's own).
    """
    data = _get(_api_path(f"/geographies/{area_id}/series", country))
    return {
        "attribution": ATTRIBUTION,
        "geography": data.get("geography"),
        "available": [_project_series_entry(e) for e in data.get("available", [])],
        "not_comparable": [_project_series_entry(e)
                           for e in data.get("not_comparable", [])],
        "national": [_project_series_entry(e) for e in data.get("national", [])],
    }


def get_dataset_for_area(area_id: str, dataset: str,
                         history_months: int = 0, country: str = "ireland") -> dict[str, Any]:
    """Full detail for ONE dataset in ONE area -- the drill-down tool, unlike
    `list_area_datasets`'s projection: full caveat bodies, full facet history if
    `history_months` is set. `dataset` is either a series `group_key` or a plain
    `series_key`, from `list_area_datasets`' own `series_key` field. `country`
    must match `area_id`'s own country, same as `list_area_datasets`.

    `history_months` (0 = full history) is passed straight through -- as of
    2026-08-30 the API converts it to this dataset's own PERIOD count
    (annual/quarterly/monthly) rather than a raw row count, so `history_months=24`
    correctly means "the last 2 years" on an annual series, not 24 years.

    Source: GET /{country}/api/v1/geographies/{area_id}/datasets/{dataset}.
    """
    params = {"history_months": history_months} if history_months else None
    result = _get(_api_path(f"/geographies/{area_id}/datasets/{dataset}", country),
                  params=params)
    result["attribution"] = ATTRIBUTION
    return result


def list_comparisons(country: str = "ireland") -> list[dict[str, Any]]:
    """Every registered cross-dataset comparison pair for one country -- e.g.
    "median sale price vs new dwelling completions per 1,000 residents". A small,
    hand-curated set (a handful of pairs per country), not an arbitrary-pair
    engine -- pass one of the `pair_key` values returned here to `get_comparison`
    for the real correlation and per-area scatter data.

    CONTRACT-PARITY item 4 remainder (TODO.md "CONTRACT PARITY (not primacy
    inversion)", developer-approved): this package had rank_areas but no
    equivalent for the comparison layer the parent site's own chat tool of the
    same name already exposes -- an agent asking "how does X relate to Y" had no
    way to discover a registered pair existed at all. Source: GET
    /{country}/api/v1/comparisons, added alongside this tool (item 2).
    """
    return _get(_api_path("/comparisons", country))


def get_comparison(pair_key: str, country: str = "ireland") -> dict[str, Any]:
    """Full detail for one registered comparison pair: each axis's label/unit/
    publisher, the correlation stats (r, rho, a leave-one-out sensitivity range),
    and caveats -- everything except the raw per-area scatter points, which this
    tool omits (they're the one part a text-answering agent has no use for, and
    the source route can return dozens of them). `pair_key` comes from
    `list_comparisons(country=...)`. Source: GET /{country}/api/v1/comparisons/
    {pair_key}.
    """
    result = _get(_api_path(f"/comparisons/{pair_key}", country))
    result.pop("points", None)
    result["attribution"] = ATTRIBUTION
    return result


def check_comparability(stat_key_a: str, stat_key_b: str,
                        country: str = "ireland") -> dict[str, Any]:
    """Does StatsMapped have a registered, hand-vetted comparison for these two
    stats? Registry-backed only -- this never computes a fresh correlation for an
    arbitrary pair, and says so plainly (`reason`) whichever way it answers.
    `comparable: false` is a normal, expected result for most stat_key pairs (the
    registry is small and hand-curated, a handful of pairs per country), not an
    error -- refusing tells you as much as confirming does: don't compute or
    imply a relationship between two stats StatsMapped hasn't vetted, even if the
    figures themselves are individually real. Source: GET /{country}/api/v1/
    comparisons/check?stat_key_a=...&stat_key_b=....
    """
    return _get(_api_path("/comparisons/check", country),
               params={"stat_key_a": stat_key_a, "stat_key_b": stat_key_b})


def explain_metric(stat_key: str, country: str = "ireland") -> dict[str, Any]:
    """Definition, methodology and standing caveats for ONE stat -- never a
    current figure (`get_dataset_for_area`/`rank_areas` already answer "what is
    this right now"; this answers "what does this even mean"). Useful before
    citing a figure at all, or when a reader's own question is about the metric
    itself ("how is the claimant count actually defined"), not a specific area's
    value. `stat_key` comes from `list_datasets(country=...)`. Source: GET
    /{country}/api/v1/stats/{stat_key}/explain.
    """
    result = _get(_api_path(f"/stats/{stat_key}/explain", country))
    result["attribution"] = ATTRIBUTION
    return result


def rank_areas(stat_key: str, level: str | None = None,
                country: str = "ireland") -> list[dict[str, Any]]:
    """Every area at one boundary level, ranked by its latest figure for one
    stat -- "which counties have the highest median sale price", "which local
    authorities award the most single-bid contracts". `stat_key` must be one
    this `country` actually tracks (see `list_datasets(country=...)`) -- Ireland
    and the UK have different catalogues. `level` omitted uses the ranking's own
    default level for this stat; pass one of `list_datasets`' own
    `compatible_levels` to see a different registered level.

    CONTRACT-PARITY FIX (TODO.md "CONTRACT PARITY (not primacy inversion)",
    developer-approved): this used to hand-roll its own join (raw
    `latest_value` sort over `/series`, filtered to `/geographies?level=`) --
    no rate normalisation and no caveats field at all, confirmed live to
    mis-rank every stat in the parent site's own RANKING_NO_DENOMINATOR_STATS
    (crime, live_register, homelessness, road_collisions, hospital_discharges,
    ntpf_op, ntpf_ipdc) by raw population size rather than the honest per-1,000
    rate the site's own /rankings pages and in-product chat both use. Now calls
    GET /{country}/api/v1/rankings/{slug} directly -- the SAME computation
    (_rankings_data(), api.py), so this tool can never rank an area differently
    from what a reader would see citing the matching StatsMapped page.

    `stat_key` -> ranking slug is resolved via `list_datasets(country=...)`'s
    own `ranking_link` field (the SAME field the site's own rail links and
    dataset pages use to build a "See the full ranking" link) -- never a
    second, hand-maintained translation table that could drift from it. A stat
    with no `ranking_link` (no ranking published at all) raises rather than
    silently returning an empty list, since that is a genuinely different case
    from "this stat has no ranking at the LEVEL you asked for" just below.

    A `level` this ranking doesn't have registered returns an empty list, not
    an error -- the ranking slug is already confirmed real by this point (the
    `ranking_link` lookup above), so a 404 here can only mean the level
    mismatch case (`_RankingsNotFound`'s own "has no {level} level" case,
    api.py) -- preserves this tool's long-standing contract (test_client.py):
    a stat/level mismatch is a legible empty result, not a crash.
    """
    stats = list_datasets(country=country)
    stat = next((s for s in stats if s.get("key") == stat_key), None)
    if stat is None:
        raise StatsMappedAPIError(f"{stat_key!r} is not a stat {country} tracks.")
    ranking_link = stat.get("ranking_link")
    if not ranking_link:
        raise StatsMappedAPIError(
            f"{stat_key!r} has no ranking published on StatsMapped for {country}.")
    try:
        data = _get(_api_path(f"/rankings/{ranking_link['slug']}", country),
                    params={"level": level} if level else None)
    except StatsMappedAPIError as exc:
        if exc.status_code == 404:
            return []
        raise
    return [
        {
            "rank": i + 1,
            "geography_id": row.get("geo_id"),
            "display_name": row.get("name"),
            "latest_value": row.get("value"),
            "latest_period": data.get("latest_period"),
            "year_on_year_pct": row.get("yoy"),
            "unit": data.get("unit"),
            # New in this fix, not in the old hand-rolled version: the honest
            # per-1,000 rate (when this ranking is rate-ranked -- see
            # data["rate_ranked"]/RankingsResponse.rate_ranked, api.py) and the
            # sample_size a small-base caveat depends on, plus the caveats
            # themselves -- exactly the two things the old version had no way
            # to surface at all.
            "rate_per_1000": row.get("rate_per_1000"),
            "sample_size": row.get("sample_size"),
            "caveats": _project_caveats(data.get("caveats")),
        }
        for i, row in enumerate(data.get("rows", []))
    ]
