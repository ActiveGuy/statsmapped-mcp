"""Every MCP tool's description opens with "Use when" (#1796 item 3, the AI-crawler consultant's
finding: an agent choosing between tools reads the first sentence, so it must say WHEN to use the
tool, and where a sibling tool is the better answer, name it).

Reads the registered tools from the FastMCP registry, so a new tool that forgets the opening fails
here. Pure: no network.

Run:
    python mcp-server/tests/test_tool_docstrings.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import server

failures: list[str] = []
FIRST_SENTENCE_MAX = 330        # the whole opening sentence pair an agent reads first
# A tool that was added by a PR still open when this test landed (#1756, get_scene) may open another
# way until that PR is in master. NOT a standing exemption: the test FAILS if a listed tool already
# opens with "Use when" (delete it from this set then), so the list can only shrink, and the follow-up
# that rewords the tool removes the entry in the same change. Landing order of the two PRs is then free
# (R1's hazard on #1841), and the landing bot re-arms auto-merge whatever a hold says.
PENDING_REWORD = {"get_scene"}


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def main() -> int:
    tools = server.server._tool_manager.list_tools()
    check("the registry lists tools", len(tools) >= 4, f"{len(tools)} tools")
    for t in tools:
        desc = (t.description or "").strip()
        if t.name in PENDING_REWORD:
            check(f"{t.name}: listed in PENDING_REWORD but already opens 'Use when' -- delete the entry",
                  not desc.startswith("Use when"), desc[:80])
        else:
            check(f"{t.name}: description opens with 'Use when'", desc.startswith("Use when"), desc[:80])
        opening = " ".join(desc.split("\n\n")[0].split())
        check(f"{t.name}: the opening paragraph is short enough to read first",
              len(opening) <= FIRST_SENTENCE_MAX, f"{len(opening)} chars")
        check(f"{t.name}: has an input schema", bool(t.parameters.get("properties")), "no properties")
    names = {t.name for t in tools}
    by_name = {t.name: (t.description or "") for t in tools}
    # Where a sibling is the better answer, the opening names it.
    if {"query_data", "explain_metric", "compare"} <= names:
        check("query_data points to explain_metric and compare",
              "`explain_metric`" in by_name["query_data"].split("\n\n")[0]
              and "`compare`" in by_name["query_data"].split("\n\n")[0])
        check("compare points to query_data", "`query_data`" in by_name["compare"].split("\n\n")[0])
    if failures:
        print(f"FAILED {len(failures)} checks:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: every one of the {len(tools)} registered tools opens with 'Use when', stays short, and "
          f"carries an input schema; query_data and compare name their sibling tool")
    return 0


if __name__ == "__main__":
    sys.exit(main())
