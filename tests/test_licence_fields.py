"""#1372: the area listing carries publisher and licence_class (and attribution when stated); offline.

Run:
    python mcp-server/tests/test_licence_fields.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from statsmapped_mcp import client

failures: list[str] = []


def check(label, cond, detail=""):
    if not cond:
        failures.append(f"{label}{': ' + str(detail) if detail else ''}")


e = client._project_series_entry({"series_key": "a", "publisher": "HM Land Registry", "licence_class": "ogl",
                                  "attribution": "Contains HM Land Registry data.", "license": "https://x", "caveats": []})
check("publisher and licence_class are kept", e["publisher"] == "HM Land Registry" and e["licence_class"] == "ogl", e)
check("a stated attribution rides along", e.get("attribution") == "Contains HM Land Registry data.", e)
check("the long licence URL is not in the slim listing", "license" not in e)
e2 = client._project_series_entry({"series_key": "b", "publisher": "CSO", "licence_class": "cc-by", "caveats": []})
check("no attribution key when the publisher states none", "attribution" not in e2, e2)
e3 = client._project_series_entry({"series_key": "c", "caveats": []})
check("restriction tags ride along; an empty list when absent", client._project_series_entry({"series_key": "z", "licence_restrictions": ["attribution", "sharealike"], "caveats": []})["licence_restrictions"] == ["attribution", "sharealike"] and e3["licence_restrictions"] == [])
check("a missing publisher stays None, not an error", e3["publisher"] is None and e3["licence_class"] is None)
if failures:
    print("FAIL")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)
print("OK  test_licence_fields")
