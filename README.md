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
so call `list_datasets`/`list_areas` for the country you actually want rather than assume
Ireland's defaults apply.

This is a thin client. It calls StatsMapped's already-public, unauthenticated HTTPS API
(documented at [statsmapped.com/openapi.json](https://statsmapped.com/openapi.json)); no API key
is needed for anything below. Runs on your own machine over stdio by default (the recommended way
to use it today) -- see [Why stdio](#why-stdio-not-a-hosted-server-by-default) for a hosted
`streamable-http` mode this package also supports, and the real tradeoff that comes with it.

## Install

Not yet published to PyPI. Once it is, install will be:

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

Every tool takes a `country` argument (`"ireland"` or `"united-kingdom"`, default `"ireland"`) —
Ireland and the UK track different datasets and geography levels, so call `list_datasets`/
`list_areas` for the country you want rather than assume Ireland's defaults apply.

- **`list_datasets(country="ireland")`** — every stat StatsMapped tracks for one country, with its
  key, label, and which geography levels it's published at. Start here.
- **`list_areas(level="county", country="ireland")`** — every geography at one boundary level.
  `level` defaults to Ireland's 26 counties; the UK's own primary level is `"lad"` (local
  authority districts), not `"county"` — other levels exist per country too (Ireland's
  `local_authority`/`garda_division` among them).
- **`list_area_datasets(area_id, country="ireland")`** — every dataset available for one area
  (e.g. `"county:kerry"` for Ireland, `"uk:lad:e09000033"` for the UK), with its latest figure
  and year-on-year change. Caveats are projected to label + severity only, not full text — the
  point is deciding which datasets matter before paying for the full detail on any one of them.
- **`get_dataset_for_area(area_id, dataset, history_months=0, country="ireland")`** — full detail
  on one dataset in one area: a written summary, full caveat text, and (optionally) recent
  history.
- **`rank_areas(stat_key, level="county", country="ireland")`** — every area at one level, ranked
  by its latest figure for one stat, highest first.
- **`list_comparisons(country="ireland")`** — every registered cross-dataset comparison pair for
  one country (e.g. "median sale price vs new dwelling completions per 1,000 residents"). A
  small, hand-curated set, not an arbitrary-pair engine.
- **`get_comparison(pair_key, country="ireland")`** — full detail for one registered pair: each
  axis's label/unit/publisher, the correlation stats (r, rho, a leave-one-out sensitivity range),
  and caveats. `pair_key` comes from `list_comparisons(country=...)` for the same country.
- **`check_comparability(stat_key_a, stat_key_b, country="ireland")`** — does StatsMapped have a
  registered, hand-vetted comparison between these two stats? Registry-backed only — never
  computes a fresh correlation for an arbitrary pair; `comparable: false` is a normal result for
  most pairs, not an error.
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
bucket rather than each getting their own. A StatsMapped-hosted endpoint is live at `https://mcp.statsmapped.com`
(Streamable HTTP) -- confirmed responding correctly, no separate install needed for a client
that speaks Streamable HTTP directly.

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
