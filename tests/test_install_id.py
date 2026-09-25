"""
`client._get_install_id()` -- PURE (no network, no real home directory
touched; monkeypatches `_INSTALL_ID_PATH` to a tmp dir for every check).

WHY THIS EXISTS. wl:205da906b6e3 (developer decision via EA, 2026-09-25):
a random UUID generated once and persisted locally, so the SAME install
reports the same id across separate stdio process launches (an MCP client
typically starts a fresh process per session) -- an in-memory-only id would
make every single invocation look like a new install, defeating the whole
point of a repeat-caller signal. This pins: a fresh path generates and
persists a real UUID; a second call (even a fresh module-level cache reset)
reads the SAME id back from disk rather than generating a new one; a
read/write failure (unwritable directory) degrades to None rather than
raising, matching this project's fail-safe discipline for every other
optional analytics signal.

Run:
    python -m pytest tests/test_install_id.py -v
or, dependency-free:
    python tests/test_install_id.py
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def _reset_cache() -> None:
    client._install_id_cache = None
    client._install_id_cache_read = False


def main() -> int:
    real_path = client._INSTALL_ID_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fresh_path = Path(tmp) / "nested" / "install_id"

            # ---- 1. A fresh path (parent dir doesn't exist yet) generates and
            #     persists a real, well-formed UUID. -------------------------------
            client._INSTALL_ID_PATH = fresh_path
            _reset_cache()
            got = client._get_install_id()
            check("a fresh path returns a non-None id", got is not None)
            if got is not None:
                check("the returned id parses as a real UUID",
                      str(uuid.UUID(got)) == got, f"got {got!r}")
            check("the id was actually persisted to disk",
                  fresh_path.exists())
            check("the persisted file's content matches the returned id",
                  fresh_path.read_text().strip() == got)

            # ---- 2. A second call, fresh cache, reads the SAME id back from disk
            #     rather than generating a new one -- the whole point (same
            #     install across separate process launches must report the same
            #     id). ---------------------------------------------------------
            _reset_cache()
            second = client._get_install_id()
            check("a second call (fresh cache, same path) returns the SAME id, "
                  "not a freshly generated one",
                  second == got, f"first {got!r}, second {second!r}")

            # ---- 3. Within one process, the cache means _get_install_id() never
            #     re-reads the file even if it's called many times. -------------
            fresh_path.write_text("tampered-value-should-not-be-seen")
            still_cached = client._get_install_id()
            check("a call within the same cache lifetime returns the cached "
                  "value, not a re-read of the (now different) file contents",
                  still_cached == got, f"expected cached {got!r}, got {still_cached!r}")

            # ---- 4. An unwritable location degrades to None, never raises. -----
            _reset_cache()
            # A path whose PARENT is a file, not a directory -- mkdir(parents=True)
            # must fail here, and _get_install_id() must swallow it.
            blocker_file = Path(tmp) / "blocker"
            blocker_file.write_text("not a directory")
            client._INSTALL_ID_PATH = blocker_file / "install_id"
            unwritable_result = client._get_install_id()
            check("an unwritable location (parent is a file, not a dir) "
                  "degrades to None rather than raising",
                  unwritable_result is None)
    finally:
        client._INSTALL_ID_PATH = real_path
        _reset_cache()

    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print(
        "PASS: _get_install_id -- 7 checks. A fresh path generates and persists "
        "a real UUID; a second call with a fresh cache reads the SAME id back "
        "from disk rather than generating a new one (the whole point -- one id "
        "per install, stable across separate process launches); the cache means "
        "a call within one process never re-reads the file; and an unwritable "
        "location degrades to None rather than raising. No network, no real "
        "home directory touched."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
