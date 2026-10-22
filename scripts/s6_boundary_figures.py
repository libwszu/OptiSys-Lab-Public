"""Render publication-safe English-labeled figures from frozen S6-B CSVs."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20261021_024715_S6_P1"
DATA = ROOT / "runs" / RUN_ID / "s6_b_boundaries"
OUT = ROOT / "runs" / RUN_ID / "s6_b_figures"


def _read(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _sha(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h


def run() -> dict:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite figure QA output: {OUT}")
    OUT.mkdir()
    focus = _read("focus_plane_extended.csv")
    positions = _read("l2_position_extended.csv")
    warnings_seen: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig, ax = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)
        axr = ax.twinx()
        for design, label, color, marker in (("baseline125", "L2 z = 125 mm", "#2455a4", "o"),
                                              ("s5_position135", "L2 z = 135 mm", "#c43d32", "s")):
            data = sorted((r for r in focus if r["design_id"] == design),
                          key=lambda r: float(r["focus_offset_from_225_mm"]))
            x = [float(r["focus_offset_from_225_mm"]) for r in data]
            y = [float(r["capture_fraction_input"]) for r in data]
            r90 = [float(r["r90_all_plane_reachers_mm"]) for r in data]
            ax.plot(x, y, marker=marker, color=color, linewidth=2, label=f"{label} capture")
            axr.plot(x, r90, marker=marker, color=color, linestyle="--", alpha=0.8,
                     label=f"{label} all-plane r90")
        ax.set_xlabel("Target-plane offset from z = 225 mm")
        ax.set_ylabel("Capture fraction (all source weight)")
        axr.set_ylabel("All-plane r90 (mm)")
        ax.set_ylim(-0.03, 1.03); ax.grid(True, alpha=0.25)
        lines = ax.get_lines() + axr.get_lines()
        ax.legend(lines, [line.get_label() for line in lines], loc="best", fontsize=8)
        ax.set_title("S6-B1 focus-plane boundary scan (assumed P1, simulated)")
        f1 = OUT / "s6_focus_boundary_review.png"
        fig.savefig(f1, dpi=170); plt.close(fig)

        data = sorted(positions, key=lambda r: float(r["l2_principal_z_mm"]))
        x = [float(r["l2_principal_z_mm"]) for r in data]
        capture = [float(r["capture_fraction_input"]) for r in data]
        r90 = [float(r["r90_all_plane_reachers_mm"]) for r in data]
        fig, ax = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)
        axr = ax.twinx()
        ax.plot(x, capture, color="#2455a4", marker="o", linewidth=2,
                label="Capture fraction (all source weight)")
        axr.plot(x, r90, color="#d47a22", marker="s", linestyle="--", linewidth=2,
                 label="All-plane r90 (mm)")
        ax.axvline(135.0, color="#c43d32", alpha=0.65, linestyle=":", label="S5 fixed candidate: 135 mm")
        ax.set_xlabel("L2 principal-plane z (mm); target fixed at z = 225 mm")
        ax.set_ylabel("Capture fraction (all source weight)"); axr.set_ylabel("All-plane r90 (mm)")
        ax.grid(True, alpha=0.25)
        lines = ax.get_lines() + axr.get_lines()
        ax.legend(lines, [line.get_label() for line in lines], loc="best", fontsize=8)
        ax.set_title("S6-B2 L2-position boundary scan (assumed P1, simulated)")
        f2 = OUT / "s6_l2_position_boundary_review.png"
        fig.savefig(f2, dpi=170); plt.close(fig)
        warnings_seen = [str(item.message) for item in caught]
    record = {
        "schema": "optisys.s6.boundary_figure_rerender/1", "run_id": RUN_ID,
        "input_csv_sha256": {name: _sha(DATA / name) for name in
                              ("focus_plane_extended.csv", "l2_position_extended.csv")},
        "outputs": {f1.name: {"bytes": f1.stat().st_size, "sha256": _sha(f1)},
                    f2.name: {"bytes": f2.stat().st_size, "sha256": _sha(f2)}},
        "warnings": warnings_seen, "render_status": "PASS" if not warnings_seen else "QUALIFIED",
        "note": "First S6-B figure render used a font without Chinese glyphs; these reviewed English-labeled figures supersede that rendering while keeping the same source CSVs.",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (OUT / "figure_rerender.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


if __name__ == "__main__":
    run()
