"""
#2665: an argument error raised by a tool reaches the agent with its own text, not the SDK's generic
`Error executing tool <name>`.

WHY THIS EXISTS. mcp 2.x after 2.0 treats any exception other than `ToolError` (or `MCPError`) as a crash:
`MCPServer.call_tool()` re-raises it as `UnexpectedToolError("Error executing tool <name>")`, so the message is
dropped and the agent cannot tell what to fix. A1 saw exactly that on the hosted MCP (0.3.4) for
`query_data {"stat_key": "sale_price"}`. The tools' argument errors (`client.ArgumentError`) and API errors
(`client.StatsMappedAPIError`) are anticipated failures, so both subclass `ToolError` and keep their text, and
they still subclass `ValueError` / `RuntimeError` for every caller that already catches those.

PURE: drives the real `server.server.call_tool()` in-process. The cases below fail before any HTTP call,
and the demand log is stubbed.

Run:
    python tests/test_legible_tool_errors.py
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


def error_text(tool: str, args: dict) -> tuple[str, bool]:
    """The text the agent would read, and whether the SDK treated the failure as a crash."""
    try:
        asyncio.run(server.server.call_tool(tool, args))
    except UnexpectedToolError as exc:
        return str(exc), True
    except ToolError as exc:
        return str(exc), False
    return "(no error raised)", False


def main() -> int:
    with patch.object(client, "log_tool_call", lambda *a, **k: None):
        cases = [
            ("query_data", {"stat_key": "sale_price"}, "area_id"),                      # the A1 call (#2665 line 1)
            ("query_data", {"stat_key": "sale_price", "dataset": "sale_price"}, "area_id"),  # #2665 line 2
            ("query_data", {"history_months": 12}, "dataset"),
            ("compare", {"stat_key": "sale_price", "pair_key": "x"}, "exactly one mode"),
            ("compare", {"stat_key_a": "sale_price"}, "stat_key_b"),
            ("notable_changes", {"limit": 500}, "limit"),
        ]
        for tool, args, needle in cases:
            text, crashed = error_text(tool, args)
            check(f"{tool} {args}: not treated as a crash", not crashed, text)
            check(f"{tool} {args}: the reply names the problem ({needle!r})", needle in text, text)
            check(f"{tool} {args}: the reply is more than the generic text",
                  text.strip() != f"Error executing tool {tool}", text)

    arg_error = getattr(client, "ArgumentError", None)
    check("ArgumentError exists, is a ToolError, and is still a ValueError (existing callers catch that)",
          arg_error is not None and issubclass(arg_error, ValueError) and issubclass(arg_error, ToolError))
    check("StatsMappedAPIError is still a RuntimeError and now a ToolError",
          issubclass(client.StatsMappedAPIError, RuntimeError) and issubclass(client.StatsMappedAPIError, ToolError))

    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS: test_legible_tool_errors (argument and API errors reach the agent with their own text)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
