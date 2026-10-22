"""Summarise a JUnit XML report into a compact JSON file.

Usage:
    python scripts/summarize_tests.py <junit.xml> <out.json>
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    xml_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    root = ET.parse(xml_path).getroot()

    modules: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0})
    failures: list[dict[str, str]] = []
    totals = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
    duration = 0.0

    for suite in root.iter("testsuite"):
        duration += float(suite.get("time", 0.0) or 0.0)

    for case in root.iter("testcase"):
        classname = case.get("classname", "unknown")
        parts = [part for part in classname.split(".") if part]
        # pytest emits the dotted module path, e.g. tests.unit.test_units
        module = "/".join(parts[-2:]) + ".py" if len(parts) >= 2 else classname
        totals["total"] += 1
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None or error is not None:
            totals["failed"] += 1
            modules[module]["failed"] += 1
            node = failure if failure is not None else error
            failures.append(
                {
                    "test": f"{classname}::{case.get('name', '')}",
                    "message": (node.get("message") or "")[:500],
                }
            )
        elif skipped is not None:
            totals["skipped"] += 1
            modules[module]["skipped"] += 1
        else:
            totals["passed"] += 1
            modules[module]["passed"] += 1

    payload = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": xml_path.name,
        "totals": totals,
        "duration_s": round(duration, 3),
        "modules": dict(sorted(modules.items())),
        "failures": failures,
        "not_run": [],
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
