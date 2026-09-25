# statsmapped-mcp

An [MCP](https://modelcontextprotocol.io) server exposing [StatsMapped](https://statsmapped.com)'s
public API as tools for AI agents (Claude Desktop, Cursor, and any other MCP client).

StatsMapped tracks public data for Ireland (by county) and the UK (by local authority) — housing,
crime, health, the economy and social welfare — from official publishers (CSO, PSRA, Central Bank
of Ireland, DHLGH, NTPF, the Office of Government Procurement, EU Publications Office for Ireland;
ONS/HM Land Registry/Nomis/DfE/DfT for the UK), each figure carrying its own caveats. This
package lets an agent query that data directly as tool calls instead of crawling and parsing
web pages. Every tool below takes a `country` argument (`"ireland"` or `"united-kingdom"`,
default `"ireland"`) — the two countries track genuinely different datasets and geography levels,
so call `query_data`/`list_areas` for the country you actually want rather than assume
Ireland's defaults apply.

This is a thin client. It calls StatsMapped's already-public, unauthenticated HTTPS API
(documented at [statsmapped.com/openapi.json](https://statsmapped.com/openapi.json)); no API key
is needed for anything below. Runs on your own machine over stdio by default (the recommended way
to use it today) -- see [Why stdio](#why-stdio-not-a-hosted-server-by-default) for a hosted
`streamable-http` mode this package also supports, and the real tradeoff that comes with it.

## Install

Published on PyPI as `statsmapped-mcp` (confirmed live: https://pypi.org/project/statsmapped-mcp/):

```bash
pip install statsmapped-mcp
```

## Configure

Add to your MCP client's config (for Claude Desktop, `claude_desktop_config.json`; Cursor uses an
equivalent `mcp.json`):

```json
{
  "mcpServers": {
    "statsmapped": {
      "command": "statsmapped-mcp"
    }
  }
}
```

## Tools

4 tools (consolidated from an original 9 -- `query_data` and `compare` are each one tool with a
few modes, chosen by which arguments you give, rather than several near-identical single-purpose
ones). Every tool takes a `country` argument (`"ireland"` or `"united-kingdom"`, default
`"ireland"`) — Ireland and the UK track different datasets and geography levels, so call
`query_data`/`list_areas` for the country you want rather than assume Ireland's defaults apply.

- **`query_data(area_id=None, dataset=None, history_months=0, country="ireland")`** — three modes:
  - neither `area_id` nor `dataset`: every stat StatsMapped tracks for one country, with its key,
    label, and which geography levels it's published at. Start here.
  - `area_id` given, `dataset` omitted: every dataset available for one area (e.g.
    `"county:kerry"` for Ireland, `"uk:lad:e09000033"` for the UK), with its latest figure and
    year-on-year change. Caveats are projected to label + severity only, not full text — the point
    is deciding which datasets matter before paying for the full detail on any one of them.
  - both `area_id` and `dataset` given: full detail on one dataset in one area — a written
    summary, full caveat text, and (optionally, via `history_months`) recent history.
- **`list_areas(level="county", country="ireland")`** — every geography at one boundary level.
  `level` defaults to Ireland's 26 counties; the UK's own primary level is `"lad"` (local
  authority districts), not `"county"` — other levels exist per country too (Ireland's
  `local_authority`/`garda_division` among them).
- **`compare(stat_key=None, level=None, pair_key=None, stat_key_a=None, stat_key_b=None, country="ireland")`**
  — four modes, exactly one set of arguments at a time (mixing them raises an error):
  - `stat_key` alone: every area at one level, ranked by its latest figure for that stat, highest
    first.
  - `pair_key` alone: full detail for one registered comparison pair — each axis's
    label/unit/publisher, the correlation stats (r, rho, a leave-one-out sensitivity range), and
    caveats. `pair_key` comes from the no-argument mode below.
  - both `stat_key_a` and `stat_key_b`: does StatsMapped have a registered, hand-vetted comparison
    between these two stats? Registry-backed only — never computes a fresh correlation for an
    arbitrary pair. `comparable` is a **string, not a bool**: `"yes"` (a registered, hand-vetted
    pair; `pair_key` names it), `"no"` (the two stats share no geography level at all), or
    `"unknown"` (not registered, but not ruled out: treat as "ask a human", not "probably yes").
    `"unknown"` is the normal result for most pairs. Compare the value explicitly
    (`result["comparable"] == "yes"`); a truthiness test is true for all three. `reasons` (a list)
    always explains the answer.
  - none of the above: every registered cross-dataset comparison pair for one country (e.g.
    "median sale price vs new dwelling completions per 1,000 residents"). A small, hand-curated
    set, not an arbitrary-pair engine.
- **`explain_metric(stat_key, country="ireland")`** — definition, methodology and standing caveats
  for one stat, never a current figure. Use this when the question is about what a metric means or
  how it's measured, not about one area's value.

## Why stdio, not a hosted server, by default

StatsMapped runs on a single free-tier instance. A remote MCP endpoint hosted there would let an
agent's own multi-area query pattern (calling the same tool once per area, in a loop) reproduce
exactly the load pattern that has already caused timeouts on that instance under a large
geography fan-out. Running over stdio means every call goes through your own network connection
to the same public HTTPS API this package's tools call directly, with no shared bottleneck --
each user's own machine makes the HTTP calls, so N users' traffic is naturally spread across N
source IPs, not funnelled through one.

`server.py` also supports a real hosted `streamable-http` mode (`MCP_TRANSPORT=streamable-http`)
for a deployment that accepts that tradeoff -- StatsMapped's public API is itself rate-limited
per source IP (600 requests/hour), but a hosted MCP endpoint proxies every remote user's calls
through ONE shared egress IP, so all remote users of a hosted endpoint would share that one
bucket rather than each getting their own. A StatsMapped-hosted endpoint is live at
`https://mcp.statsmapped.com/mcp` (Streamable HTTP) -- confirmed responding correctly, no
separate install needed for a client that speaks Streamable HTTP directly. The bare host
(`https://mcp.statsmapped.com`, no path) redirects to the same endpoint as a courtesy.

## Development

```bash
cd mcp-server
pip install -e .
python tests/test_client.py
```

The test suite runs against the real live API (`https://statsmapped.com` by default, or
`STATSMAPPED_MCP_BASE_URL` if set) — read-only GETs only, nothing here writes any data or needs
a key.

## Licence

MIT for this package. The underlying data keeps each publisher's own licence — see
[statsmapped.com/ireland/sources](https://statsmapped.com/ireland/sources) for Ireland's own
publisher/licence detail before reusing any figure outside of querying it through an agent (a UK
equivalent page doesn't exist yet — check each UK tool response's own `caveats`/`sources` fields
in the meantime).
