"""Create a fresh pytest basetemp without deleting any prior run directory."""

from __future__ import annotations

import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parent = ROOT / "artifacts" / "s6r" / "tests" / "basetemp"
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / f"run_{uuid.uuid4().hex}"
    target.mkdir(parents=False, exist_ok=False)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
