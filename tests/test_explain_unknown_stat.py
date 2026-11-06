"""
#2406: `explain_metric` with a stat_key that is not published used to give the agent only "Error executing tool explain_metric". The reply must (a) be an
error the SDK does not treat as a crash, (b) name the key as unknown FOR THAT COUNTRY, and (c) point at the MCP tool that lists the valid keys
(`query_data` with no area_id or dataset), not at a REST path an MCP agent cannot call.

PURE: drives the real `server.server.call_tool()` in-process with the HTTP layer patched to answer 404 the way the API does, and the demand log stubbed.

Run:
    python mcp-server/tests/test_explain_unknown_stat.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError  # noqa: E402

from statsmapped_mcp import client, server  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def api_404(path, params=None):
    raise client.StatsMappedAPIError(
        f"404 from {path}: 'cpi' is not a stat StatsMapped publishes (see GET /api/v1/stats for the full list).", status_code=404)


def api_500(path, params=None):
    raise client.StatsMappedAPIError(f"500 from {path}: boom", status_code=500)


def error_text(args: dict) -> tuple[str, bool]:
    try:
        asyncio.run(server.server.call_tool("explain_metric", args))
    except UnexpectedToolError as exc:
        return str(exc), True
    except ToolError as exc:
        return str(exc), False
    return "(no error raised)", False


def main() -> int:
    with patch.object(client, "log_tool_call", lambda *a, **k: None):
        with patch.object(client, "_get", api_404):
            text, crashed = error_text({"stat_key": "cpi"})
            check("an unknown key is not treated as a crash", not crashed, text)
            check("the reply names the key", "cpi" in text, text)
            check("the reply says it is unknown for the country asked", "ireland" in text and "not a stat" in text, text)
            check("the reply points at the MCP tool that lists valid keys", "query_data" in text, text)
            check("the reply does not send an MCP agent to a REST path", "GET /api" not in text, text)
            text_uk, _ = error_text({"stat_key": "cpi", "country": "united-kingdom"})
            check("the country in the reply follows the country asked", "united-kingdom" in text_uk, text_uk)
        with patch.object(client, "_get", api_500):
            text, crashed = error_text({"stat_key": "sale_price"})
            check("a server fault stays a server fault, not reported as an unknown key", "unknown" not in text.lower() and "not a stat" not in text and "500" in text, text)

    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS: test_explain_unknown_stat (an unknown stat_key is named, scoped to its country, and points at query_data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
