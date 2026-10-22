"""Re-run the G0 geometry gates against the current source tree.

Usage:
    python scripts/g0_regression_check.py <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from optisys.config import load_config  # noqa: E402
from optisys.evaluation.chain import boundary_cases, compare_chain  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "g0_regression.json"
    config = load_config(ROOT / "configs" / "triangulation_v0.yaml")
    comparison = compare_chain(config)
    boundaries = boundary_cases(config)
    payload = {
        "schema_version": "1.0",
        "gate": "G0",
        "config_sha256": config.sha256,
        "metrics": comparison.metrics,
        "gate_checks": comparison.gate_checks,
        "boundary_cases": boundaries,
        "all_pass": all(item["pass"] for item in comparison.gate_checks.values())
                    and all(item["pass"] for item in boundaries),
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"all_pass": payload["all_pass"],
                      "max_abs_u_error_px": comparison.metrics["max_abs_u_error_px"],
                      "max_Z_relative_error": comparison.metrics["max_Z_relative_error"]}))
    return 0 if payload["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
