"""Rebuild the four G0 figures from a configuration, without a new run.

Usage:
    python scripts/make_figures.py --config configs/triangulation_v0.yaml --out <dir>
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from optisys.config import load_config  # noqa: E402
from optisys.evaluation.chain import U_TOLERANCE_PX, compare_chain  # noqa: E402
from optisys.reports.figures import build_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "triangulation_v0.yaml")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    comparison = compare_chain(config)
    paths = build_all(config, comparison, args.out, U_TOLERANCE_PX)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
