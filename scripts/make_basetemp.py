"""Create a fresh, empty ``--basetemp`` directory for a pytest run.

Why this is a script and not a one-liner
----------------------------------------
pytest deletes and recreates its ``--basetemp`` at session start.  On this host a
bulk delete is refused by the sandbox guard once the tree holds more than ~50
entries, so pointing ``--basetemp`` at a stale directory turns *every* test into
a setup error:

    ERROR at setup of test_validate_rejects_unknown_field
    ...
    346 passed, 79 errors in 42.31s      <- looks like a code regression, isn't

That failure mode is expensive to diagnose next time, so the workaround is
captured here.  Each run gets a brand-new empty directory under
``artifacts/g3/tests/_bt_run/``; pytest has nothing to wipe, and the guard is
never involved.

Usage::

    .venv\\Scripts\\python.exe scripts/make_basetemp.py
    -> artifacts/g3/tests/_bt_run/run_<epoch>
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "artifacts" / "g3" / "tests" / "_bt_run"

#: Keep only the newest N run directories so this never grows without bound.
KEEP = 3


def make_basetemp() -> Path:
    PARENT.mkdir(parents=True, exist_ok=True)

    existing = sorted(
        (p for p in PARENT.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in existing[KEEP - 1:]:
        shutil.rmtree(stale, ignore_errors=True)

    target = PARENT / f"run_{int(time.time() * 1000)}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def main() -> int:
    target = make_basetemp()
    # printed bare so a shell can capture it:
    #   BASE=$(python scripts/make_basetemp.py)
    print(str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())