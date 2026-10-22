"""Collect the G3 baseline hash snapshot before any source change.

Writes ``docs/g3/G3_BASELINE_HASHES.json``.  Read-only with respect to every
frozen run directory: the script only hashes files, never writes into ``runs/``
or ``_AUDIT/``.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

G0_RUN = ROOT / "runs" / "20261019_130948_G0_78fa364f"
G1_RUN = ROOT / "runs" / "20261019_145702_G1_54c9e3fb"
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"
G2_ZIP = (ROOT / "_AUDIT" / "20261019_191117_G2_52369787"
          / "OptiSysLab_G2_20261019_191117_G2_52369787_GPT_AUDIT.zip")

KEY_SOURCES = [
    "src/optisys/cli.py",
    "src/optisys/config.py",
    "src/optisys/config_g2.py",
    "src/optisys/gates/g2.py",
    "src/optisys/gates/g1.py",
    "src/optisys/optics/psf_or_footprint.py",
    "src/optisys/optics/optical_image_contract.py",
    "src/optisys/optimization/constraints.py",
    "src/optisys/calibration/assembly_strategies.py",
    "src/optisys/evaluation/paired_comparison.py",
    "src/optisys/reports/report_g2.py",
    "configs/triangulation_g2_l1.yaml",
    "docs/g2/G2_PRE_REGISTRATION.md",
    "pyproject.toml",
    "requirements.lock.txt",
]

TREE_SUBDIRS = ["src", "tests", "app", "scripts"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(base: Path) -> tuple[str, int, int]:
    """Deterministic digest plus file count and byte total for a subtree."""

    if not base.is_dir():
        return "ABSENT", 0, 0
    files = sorted(p for p in base.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts
                   and p.suffix != ".pyc")
    digest = hashlib.sha256()
    total = 0
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
        total += path.stat().st_size
    return digest.hexdigest(), len(files), total


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout.strip()
    except OSError:
        return "GIT_UNAVAILABLE"


def main() -> int:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "gate": "G3",
        "snapshot_kind": "pre_change_baseline",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(ROOT),
        "git_head": git("rev-parse", "HEAD"),
        "git_working_tree_dirty": bool(git("status", "--porcelain=v1")),
        "git_status_line_count": len(
            [line for line in git("status", "--porcelain=v1").splitlines() if line]
        ),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "source_pdf": {
            "path": "OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf",
            "sha256": sha256_file(ROOT / "OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf"),
            "expected": "25d0a727fbf047e8b399be8bd1ab670149b4a32377ff8edcef63e41ca4e6319d",
        },
        "g2_audit_zip": {
            "path": str(G2_ZIP.relative_to(ROOT)),
            "sha256": sha256_file(G2_ZIP),
            "bytes": G2_ZIP.stat().st_size,
            "expected": "08a7b57e3e3ab62162ccef2d7d6c1a339a61c286dac2fef4446e38f4647ba6af",
        },
        "g2_config": {
            "path": "configs/triangulation_g2_l1.yaml",
            "sha256": sha256_file(ROOT / "configs" / "triangulation_g2_l1.yaml"),
            "expected": "52369787c0e7f1dab7363a19132135a012dbe0fd9aa732e96a000d5a2e46e30c",
        },
        "frozen_runs": {},
        "key_sources": {},
        "trees": {},
        "g2_complete_samples": {},
    }

    for gate, run_dir in (("G0", G0_RUN), ("G1", G1_RUN), ("G2", G2_RUN)):
        entry: dict[str, object] = {"path": str(run_dir.relative_to(ROOT))}
        status_path = run_dir / "run_status.json"
        if status_path.is_file():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            entry["run_status_sha256"] = sha256_file(status_path)
            entry["status"] = status.get("status")
            entry["gate"] = status.get("gate")
            entry["frozen"] = status.get("frozen")
            entry["finished_at_utc"] = status.get("finished_at_utc")
        digest, count, total = tree_manifest(run_dir)
        entry["tree_digest"] = digest
        entry["file_count"] = count
        entry["total_bytes"] = total
        payload["frozen_runs"][gate] = entry  # type: ignore[index]

    for rel in KEY_SOURCES:
        path = ROOT / rel
        payload["key_sources"][rel] = (  # type: ignore[index]
            sha256_file(path) if path.is_file() else "ABSENT"
        )

    for sub in TREE_SUBDIRS:
        digest, count, total = tree_manifest(ROOT / sub)
        payload["trees"][sub] = {  # type: ignore[index]
            "digest": digest, "file_count": count, "total_bytes": total,
        }

    samples = G2_RUN / "independent_validation" / "sampled_results.csv"
    if samples.is_file():
        with samples.open(encoding="utf-8") as handle:
            n_rows = sum(1 for _ in handle) - 1
        payload["g2_complete_samples"] = {
            "path": str(samples.relative_to(ROOT)),
            "sha256": sha256_file(samples),
            "bytes": samples.stat().st_size,
            "data_rows": n_rows,
        }

    payload["verdicts"] = {
        "source_pdf_matches_task_book": None,
        "g2_zip_matches_task_book": None,
        "g2_config_matches_task_book": None,
    }
    verdicts = payload["verdicts"]  # type: ignore[assignment]
    verdicts["source_pdf_matches_task_book"] = (
        payload["source_pdf"]["sha256"] == payload["source_pdf"]["expected"]  # type: ignore[index]
    )
    verdicts["g2_zip_matches_task_book"] = (
        payload["g2_audit_zip"]["sha256"] == payload["g2_audit_zip"]["expected"]  # type: ignore[index]
    )
    verdicts["g2_config_matches_task_book"] = (
        payload["g2_config"]["sha256"] == payload["g2_config"]["expected"]  # type: ignore[index]
    )

    out = ROOT / "docs" / "g3" / "G3_BASELINE_HASHES.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, indent=2))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())