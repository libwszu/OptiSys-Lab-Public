"""Run the full G0 pipeline (thin wrapper around optisys.pipeline).

Usage:
    python scripts/run_g0.py --config configs/triangulation_v0.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from optisys.config import load_config  # noqa: E402
from optisys.pipeline import run_g0  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "triangulation_v0.yaml")
    parser.add_argument("--runs-dir", type=Path, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    context, metrics = run_g0(config, ROOT, runs_dir=args.runs_dir)
    print(f"RUN_DIR={context.directory}")
    print(f"MAX_ABS_U_ERROR_PX={metrics['chain']['max_abs_u_error_px']:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
