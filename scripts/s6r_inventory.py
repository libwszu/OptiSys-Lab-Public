"""Create the immutable S6-R intake map and pre-change hash snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20261021_024715_S6_P1"
OUT = ROOT / "docs" / "s6r"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tree_inventory(rel_dir: str) -> dict[str, Any]:
    base = ROOT / rel_dir
    if not base.is_dir():
        return {"status": "MISSING_SOURCE", "path": rel_dir, "files": [], "tree_sha256": None}
    rows = []
    for p in sorted((x for x in base.rglob("*") if x.is_file()), key=lambda x: x.relative_to(ROOT).as_posix()):
        rel = p.relative_to(ROOT).as_posix()
        rows.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256(p)})
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(row["sha256"].encode("ascii"))
        digest.update(b"\n")
    return {"status": "PRESENT", "path": rel_dir, "file_count": len(rows), "bytes": sum(x["bytes"] for x in rows), "tree_sha256": digest.hexdigest(), "files": rows}


def git(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def collect_manifest_entries(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("path"), str) and isinstance(node.get("sha256"), str):
                out.append({"path": node["path"], "sha256": node["sha256"], "bytes": node.get("bytes")})
            for key, child in node.items():
                # The S6 amendment/freeze files use path -> {bytes, sha256} maps.
                if key not in {"path", "sha256", "bytes"} and isinstance(child, dict) and isinstance(child.get("sha256"), str):
                    out.append({"path": key, "sha256": child["sha256"], "bytes": child.get("bytes")})
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    unique = {(x["path"], x["sha256"]): x for x in out}
    return list(unique.values())


def verify_freeze_manifest(path: Path) -> dict[str, Any]:
    rel_manifest = path.relative_to(ROOT).as_posix()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # preserve evidence of malformed manifests
        return {"manifest": rel_manifest, "status": "MANIFEST_READ_ERROR", "error": str(e), "verified": [], "failures": []}
    verified, failures = [], []
    for item in collect_manifest_entries(payload):
        raw = Path(item["path"])
        target = raw if raw.is_absolute() else ROOT / raw
        if not target.is_file():
            failures.append({**item, "reason": "MISSING_SOURCE"})
            continue
        actual_size = target.stat().st_size
        actual_hash = sha256(target)
        if actual_hash != item["sha256"] or (item.get("bytes") is not None and actual_size != item["bytes"]):
            failures.append({**item, "actual_bytes": actual_size, "actual_sha256": actual_hash, "reason": "HASH_OR_SIZE_MISMATCH"})
        else:
            verified.append(item["path"])
    status = "PASS" if not failures else "PARTIAL"
    return {"manifest": rel_manifest, "status": status, "entries_declared": len(verified) + len(failures), "entries_verified": len(verified), "verified": verified, "failures": failures}


def main() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"Refusing to overwrite existing S6-R records: {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)
    rel_paths = [
        "runs/" + RUN_ID,
        "docs/s6",
        "RELEASE_CANDIDATE_V2",
    ]
    trees = {p: tree_inventory(p) for p in rel_paths}
    freeze_paths = sorted(
        p for p in (ROOT / "docs").rglob("*.json")
        if any(token in p.name.lower() for token in ("freeze", "baseline_hash"))
    )
    freeze_records = [verify_freeze_manifest(p) for p in freeze_paths]
    historical_archives = []
    for p in sorted((ROOT / "_AUDIT").rglob("*.zip")) if (ROOT / "_AUDIT").exists() else []:
        historical_archives.append({"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)})
    status = git("status", "--porcelain=v1") or ""
    try:
        import psutil  # type: ignore
        mem = psutil.virtual_memory()
        ram = {"total_gib": round(mem.total / (1024**3), 2), "available_gib": round(mem.available / (1024**3), 2)}
        cpu = psutil.cpu_count(logical=True)
        related = []
        for proc in psutil.process_iter(["pid", "name", "create_time", "exe", "cmdline"]):
            try:
                args = " ".join(proc.info.get("cmdline") or [])
                if any(term in args.lower() for term in ("<PROJECT_ROOT>", "optisys", "streamlit run", "pytest")):
                    related.append({"pid": proc.info["pid"], "name": proc.info["name"], "created": proc.info["create_time"], "exe": proc.info.get("exe")})
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
    except ImportError:
        ram, cpu, related = None, None, None

    manifests = [
        {"path": x["manifest"], "status": x["status"], "entries_verified": x.get("entries_verified", 0), "entries_declared": x.get("entries_declared", 0), "failures": x.get("failures", [])}
        for x in freeze_records
    ]
    baseline = {
        "schema": "optisys.s6r.baseline_hashes/1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": {"root": str(ROOT), "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"), "remotes": git("remote", "-v"), "status_porcelain": status.splitlines()},
        "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(), "logical_cpu_count": cpu, "memory": ram, "project_related_processes": related},
        "immutable_trees": trees,
        "historical_freeze_manifests": manifests,
        "historical_audit_archives": historical_archives,
    }
    missing = []
    def add_required(path: str, description: str) -> None:
        target = ROOT / path
        if not target.exists():
            missing.append({"path": path, "description": description, "status": "MISSING_SOURCE"})

    required = {
        "docs/s6/S6_ACCEPTANCE_CRITERIA.md": "Frozen S6 acceptance criteria",
        "docs/s6/S6_PRE_REGISTRATION.md": "Requested standalone S6 preregistration text",
        f"runs/{RUN_ID}/s6_c_assemblies/p1_assembly_samples.csv": "Original full S6-C sample table",
        f"runs/{RUN_ID}/s6_c_assemblies/paired_assembly_comparison.csv": "Original paired assembly comparison",
        f"runs/{RUN_ID}/s6_c_assemblies/assembly_bootstrap_replicates.csv": "Original bootstrap replicates",
        f"runs/{RUN_ID}/s6_c_assemblies/failure_breakdown.csv": "Original failure breakdown",
        f"runs/{RUN_ID}/s6_c_assemblies/assembly_manifest.csv": "Original assembly manifest",
        f"runs/{RUN_ID}/s6_c_assemblies/assembly_robustness_plot_data.csv": "Original plot data",
        f"runs/{RUN_ID}/s6_c_assemblies/assembly_statistics_programmatic.json": "Original programmatic stats",
        f"runs/{RUN_ID}/s6_c_assemblies/assembly_statistics.json": "Original rendered stats",
        f"runs/{RUN_ID}/s6_c_assemblies/S6_ASSEMBLY_SCIENTIFIC_AUDIT_FINAL.md": "Original final S6-C report",
        "RELEASE_CANDIDATE_V2/README.md": "Original V2 draft README",
        "RELEASE_CANDIDATE_V2/DEMO_CAPTURE_CHECKLIST.md": "Original V2 capture checklist",
        "RELEASE_CANDIDATE_V2/screenshot_evidence/browser_e2e.json": "Existing browser evidence record",
        "RELEASE_CANDIDATE_V2/evidence/s6/released_demo": "Claimed S6 release demonstration evidence directory",
    }
    for path, description in required.items():
        add_required(path, description)
    required_present = [{"path": p, "description": d, "status": "PRESENT"} for p, d in required.items() if (ROOT / p).exists()]
    inputs = {
        "schema": "optisys.s6r.input_map/1",
        "captured_at_utc": baseline["captured_at_utc"],
        "run_id": RUN_ID,
        "source_map": {
            "historical_design_pdf": "OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf",
            "s6_documents": "docs/s6/",
            "s6_run_root": f"runs/{RUN_ID}/",
            "s6_c_original_evidence": f"runs/{RUN_ID}/s6_c_assemblies/",
            "s6_a_b_release_copy": "RELEASE_CANDIDATE_V2/evidence/s6/",
            "release_draft": "RELEASE_CANDIDATE_V2/",
            "historical_g4_audit_zip": "_AUDIT/20261020_133555_G4_ec3e2813_0e48/OptiSysLab_G4_20261020_133555_G4_ec3e2813_0e48_GPT_AUDIT.zip",
            "historical_s5_audit_zip": "_AUDIT/20261020_210201_S5_HNA/OptiSysLab_S5_20261020_210201_S5_HNA_GPT_AUDIT.zip",
        },
        "required_present": required_present,
        "missing_sources": missing,
        "existing_s6_audit_zip": [x for x in historical_archives if RUN_ID in x["path"]],
    }
    (OUT / "BASELINE_HASHES.json").write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "S6R_INPUT_MAP.json").write_text(json.dumps(inputs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    plan = f"""# S6-R Recovery Plan

Captured on {baseline['captured_at_utc']} from `{ROOT}` at commit `{baseline['repository']['head']}` on branch `{baseline['repository']['branch']}`.

## Preservation boundary

- Preserve the original S6 run tree hash in `BASELINE_HASHES.json`; do not modify `runs/{RUN_ID}/` or `docs/s6/` frozen source files.
- The existing `RELEASE_CANDIDATE_V2/` is an unverified draft. Its initial file hashes are recorded for an audit trail; corrections go into `RELEASE_CANDIDATE_V2_VERIFIED/`.
- Record all new diagnostics, test outputs, and the GPT audit package under new S6-R paths.
- G0–G4/S5 historical artifacts remain read-only. See the freeze-manifest verification records in `BASELINE_HASHES.json`.

## Work order

1. R0: finish intake hash checks, record missing sources, and correct only the verified release copy's claims.
2. R1: independently recompute S6-C pairing, weight ledger, percentiles, and paired cluster bootstrap from original per-assembly records; compare to frozen criteria and Amendment 03 while retaining original automatic status.
3. R2: run the isolated Python 3.11.9 install/CLI reports, six-page AppTest, clean-basetemp full pytest, and real Streamlit server smoke with captured exit codes and logs.
4. R3: build a linked and internally consistent verified release copy; attempt browser evidence only if the active browser URL can be verified safely.
5. R4/R5: package the complete required science and run evidence, verify hashes after clean extraction, and prove tamper/deletion rejection before recording the final state.

## Initial environment

- Python 3.11.9 is available at `<PROJECT_ROOT>\\.venv_s6_release_check\\Scripts\\python.exe`.
- The host has 12 logical CPUs, 31.41 GiB RAM, and approximately 14.38 GiB free at intake.
- No process command line identified an OptiSys, Streamlit, or pytest task at intake; unrelated Python and browser processes were present.
- No Git remote is configured. The GitHub account has multiple unrelated optical repositories, so no remote is selected yet.
"""
    (OUT / "RECOVERY_PLAN.md").write_text(plan, encoding="utf-8")
    issue_doc = """# Issues Before S6-R Fixes

| ID | Priority | Finding at intake | Evidence | Handling |
|---|---|---|---|---|
| R0-01 | P0 | V2 README claims S6 browser captures and a GPT audit ZIP were delivered at paths that do not exist. | `RELEASE_CANDIDATE_V2/README.md`; `S6R_INPUT_MAP.json` marks the claimed path `MISSING_SOURCE`. | Preserve the draft hash; create a corrected verified release copy and retain the old draft unchanged. |
| R0-02 | P0 | V2 capture checklist marks Edge E2E done, while its only browser record is S5 run `20261020_210201_S5_HNA` and points to historical S5 screenshots. | `RELEASE_CANDIDATE_V2/DEMO_CAPTURE_CHECKLIST.md`; `screenshot_evidence/browser_e2e.json`. | Do not count the old record as S6 browser proof. Attempt a safe current-session check only after validating localhost URL; otherwise mark `NOT_RUN_POLICY_BLOCKED`. |
| R0-03 | P0 | Draft release manifest declares S5 browser E2E and audit status as if they described the S6 release. | `RELEASE_CANDIDATE_V2/release_candidate_manifest.json`. | Replace in verified copy with separate engineering, science, media, and audit statuses backed by actual evidence. |
| R0-04 | P1 | The named standalone S6 preregistration file is absent. Existing acceptance criteria, run freeze and holdout freeze are present. | `S6R_INPUT_MAP.json`. | Record `MISSING_SOURCE`; use only located frozen rules and preserve any limitation in the adjudication. |
| R0-05 | P1 | No Git remote is configured and available account repositories are unrelated educational optical repositories. | `BASELINE_HASHES.json`; GitHub repository inventory. | Do not push to an unrelated repo. Confirm or establish an explicitly selected repository after the final files are reviewable. |
| R0-06 | P1 | `.venv_s6_release_check/` is currently untracked and not covered by `.gitignore`. | Intake `git status`; `.gitignore`. | Add a narrow ignore rule before preparing any upload, and exclude local environments from release manifests. |
| R0-07 | P2 | Browser E2E and new S6 screenshots have not yet been proven; video, remote CI, GPU and empirical optics remain undeclared. | V2 evidence map and S6 prompt. | Preserve honest status unless this turn produces direct evidence. |

No frozen G0–G4/S5/S6 source file was edited to create this issue register.
"""
    (OUT / "ISSUES_BEFORE_FIX.md").write_text(issue_doc, encoding="utf-8")
    print(json.dumps({"output": str(OUT), "trees": {k: {"status": v["status"], "file_count": v.get("file_count"), "bytes": v.get("bytes"), "tree_sha256": v.get("tree_sha256")} for k, v in trees.items()}, "freeze_manifests": manifests, "historical_archives": historical_archives, "missing_sources": missing}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
