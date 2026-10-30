"""
#1677: the demand-log opt-out must be reachable by an MCP caller. The server's `X-No-Log: 1` header cannot be set by the agent (this process sends the beacon),
so the client honours STATSMAPPED_NO_LOG=1 and DO_NOT_TRACK=1: no request is made, no thread is started and no install id is written. Unset (or a false value),
the beacon is sent as before. No network: httpx.Client is patched to record any request.

Run:
    python mcp-server/tests/test_no_log_optout.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


class _Recorder:
    """Stands in for httpx.Client: records every post instead of sending it."""
    posts: list[str] = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **k):
        _Recorder.posts.append(url)


def _send_once(env: dict[str, str]) -> tuple[int, bool]:
    """Run one beacon with `env` applied; return (posts made, install id file created)."""
    _Recorder.posts = []
    with tempfile.TemporaryDirectory() as tmp:
        id_path = Path(tmp) / "install_id"
        client._install_id_cache, client._install_id_cache_read = None, False
        clean = {k: v for k, v in os.environ.items() if k not in client._OPT_OUT_VARS}
        with patch.dict(os.environ, {**clean, **env}, clear=True), \
                patch.object(client, "_INSTALL_ID_PATH", id_path), \
                patch.object(client.httpx, "Client", _Recorder):
            client._post_tool_call_event("notable_changes", "ireland", "success")
        return len(_Recorder.posts), id_path.exists()


def main() -> int:
    posts, wrote = _send_once({})
    check("no opt-out: the beacon is sent", posts == 1, str(posts))
    check("no opt-out: an install id is written", wrote)

    for env in ({"STATSMAPPED_NO_LOG": "1"}, {"DO_NOT_TRACK": "1"}, {"STATSMAPPED_NO_LOG": "true"}, {"DO_NOT_TRACK": " YES "}):
        posts, wrote = _send_once(env)
        check(f"{env}: no request is made", posts == 0, str(posts))
        check(f"{env}: no install id is written", not wrote)

    for env in ({"STATSMAPPED_NO_LOG": "0"}, {"DO_NOT_TRACK": ""}, {"STATSMAPPED_NO_LOG": "false"}):
        posts, _ = _send_once(env)
        check(f"{env}: a false value does not opt out", posts == 1, str(posts))

    # log_tool_call (the public entry point) must not even start the background thread when opted out
    with patch.dict(os.environ, {"STATSMAPPED_NO_LOG": "1"}), patch.object(client.threading, "Thread") as thread:
        client.log_tool_call("compare", "ireland", "success")
        check("log_tool_call starts no thread when opted out", not thread.called)
    with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in client._OPT_OUT_VARS}, clear=True), \
            patch.object(client.threading, "Thread") as thread:
        client.log_tool_call("compare", "ireland", "success")
        check("log_tool_call starts the thread when not opted out", thread.called)

    for f in failures:
        print("FAIL", f)
    print(f"test_no_log_optout: {'FAIL' if failures else 'PASS'} ({len(failures)} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
