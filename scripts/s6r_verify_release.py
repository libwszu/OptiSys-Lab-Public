"""Check release-candidate links, image assets, commands and S6-R claims."""

from __future__ import annotations

import hashlib
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    release_dir = root / "RELEASE_CANDIDATE_V2"
    broken = []
    links_seen = []
    markdown = sorted(release_dir.rglob("*.md"))
    for doc in markdown:
        text = doc.read_text(encoding="utf-8", errors="replace")
        for raw in LINK_RE.findall(text):
            target = raw.strip().split()[0].strip("<>")
            if not target or target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            path_text = unquote(target.split("#", 1)[0]).replace("\\", "/")
            target_path = (doc.parent / path_text).resolve()
            ok = target_path.exists()
            links_seen.append({"document": doc.relative_to(root).as_posix(), "target": target, "exists": ok})
            if not ok:
                broken.append({"document": doc.relative_to(root).as_posix(), "target": target})

    images = []
    for doc in markdown:
        for raw in IMAGE_RE.findall(doc.read_text(encoding="utf-8", errors="replace")):
            target = raw.strip().split()[0].strip("<>")
            path_text = unquote(target.split("#", 1)[0]).replace("\\", "/")
            target_path = (doc.parent / path_text).resolve()
            images.append({"document": doc.relative_to(root).as_posix(), "target": target, "exists": target_path.is_file()})

    readme = (release_dir / "README.md").read_text(encoding="utf-8")
    checklist = (release_dir / "DEMO_CAPTURE_CHECKLIST.md").read_text(encoding="utf-8")
    s6_index = (release_dir / "evidence" / "s6" / "README.md").read_text(encoding="utf-8")
    manifest = json.loads((release_dir / "release_candidate_manifest.json").read_text(encoding="utf-8"))
    manifest_files = manifest.get("files", [])
    missing_manifest_files = []
    hash_mismatches = []
    for item in manifest_files:
        path = release_dir / item["path"]
        if not path.is_file():
            missing_manifest_files.append(item["path"])
            continue
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != item.get("bytes") or actual_sha != item.get("sha256"):
            hash_mismatches.append(item["path"])
    claims = {
        "s6_browser_claim_has_real_record": "浏览器 E2E" in readme and "S6R_BROWSER_E2E.json" in readme,
        "new_s6_screenshots_not_claimed_delivered": "NOT_DELIVERED" in readme and "NOT_DELIVERED" in checklist and "NOT_DELIVERED" in s6_index,
        "video_not_claimed_delivered": "NOT_DELIVERED" in readme and "NOT_DELIVERED" in checklist,
        "audit_not_claimed_before_build": manifest.get("gpt_audit") in {"NOT_BUILT", "PASS"},
        "historical_s5_browser_record_separated": manifest.get("historical_evidence", {}).get("s5_browser_status") == "PASS_HISTORICAL_ONLY",
        "empirical_validation_not_claimed": manifest.get("empirical_validation") == "NOT_AVAILABLE",
        "release_science_scope_has_assumed_p1_limitation": "假设 P1" in readme and "不代表实测" in readme,
        "release_manifest_files_present_and_hashed": not missing_manifest_files and not hash_mismatches,
    }
    commands = []
    for line in readme.splitlines():
        stripped = line.strip()
        if stripped.startswith(".\\.venv_s6r_release\\Scripts\\python.exe") or stripped.startswith("py -3.11 -m venv"):
            commands.append(stripped)
    expected_cmd_fragments = [
        "py -3.11 -m venv .venv_s6r_release",
        ".\\.venv_s6r_release\\Scripts\\python.exe -m pip install -e \".[dev,ui,optics]\"",
        ".\\.venv_s6r_release\\Scripts\\python.exe -m streamlit run app/main.py",
        ".\\.venv_s6r_release\\Scripts\\python.exe -m optisys g3-demo",
        ".\\.venv_s6r_release\\Scripts\\python.exe -m optisys pump976",
    ]
    commands_ok = all(any(expected in command for command in commands) for expected in expected_cmd_fragments)
    all_images_ok = all(x["exists"] for x in images)
    result = {
        "schema": "optisys.s6r.release_verification/1",
        "release_dir": "RELEASE_CANDIDATE_V2",
        "markdown_files_checked": len(markdown),
        "internal_links_checked": len(links_seen),
        "broken_links": broken,
        "image_links": images,
        "image_links_ok": all_images_ok,
        "commands_found": commands,
        "commands_match_tested_environment": commands_ok,
        "claim_guards": claims,
        "false_delivery_claims": [k for k, v in claims.items() if not v],
        "release_manifest_file_count": len(manifest_files),
        "release_manifest_missing_files": missing_manifest_files,
        "release_manifest_hash_mismatches": hash_mismatches,
        "status": "PASS" if not broken and all_images_ok and commands_ok and all(claims.values()) else "FAIL",
    }
    if not args.no_write:
        output = args.output or (root / "docs" / "s6r" / "S6R_RELEASE_VERIFICATION.json")
        output = output if output.is_absolute() else root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
