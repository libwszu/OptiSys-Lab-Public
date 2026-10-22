"""Verify S5 audit ZIP coverage, clean extraction replay and tamper rejection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

EXCEPTIONS={"manifest.json","SHA256SUMS.txt"}
ABSOLUTE_PATH=re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s\"'<>|]+")
SECRETS=(re.compile(r"(?i)\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
         re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"))


def _sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()


def _safe(name:str)->bool:
    if not name or "\\" in name or name.startswith("/") or (len(name)>1 and name[1]==":"):
        return False
    p=PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and all(x not in ("",".") for x in p.parts)


def _parse_sums(data:bytes)->dict[str,str]:
    values={}
    for line in data.decode("utf-8").splitlines():
        if not line.strip():continue
        digest,name=line.split("  ",1);values[name]=digest
    return values


def _copy_tree(src:Path,dst:Path)->None:
    dst.mkdir(parents=True,exist_ok=True)
    for p in src.rglob("*"):
        if p.is_dir():continue
        rel=p.relative_to(src);target=dst/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,target)


def _run_repro(root:Path,timeout:float=180)->subprocess.CompletedProcess:
    return subprocess.run([sys.executable,str(root/"repro/verify_s5.py")],cwd=root,
                          capture_output=True,text=True,timeout=timeout)


def _tamper_csv(path:Path)->None:
    with path.open(newline="",encoding="utf-8") as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    if not fields or "target_x_mm" not in fields:raise ValueError("tamper target column unavailable")
    for row in rows:
        if row.get("target_x_mm") not in (None,""):
            row["target_x_mm"]=f"{float(row['target_x_mm'])+0.1:.12f}"
            break
    else:raise ValueError("no finite target coordinate available for tamper test")
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def verify_archive(path:Path)->dict[str,Any]:
    path=path.resolve()
    if not path.is_file():raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as zf:
        infos=zf.infolist();names=[x.filename for x in infos]
        if len(names)!=len(set(names)):raise ValueError("duplicate ZIP member names")
        unsafe=[n for n in names if not _safe(n)]
        if unsafe:raise ValueError(f"unsafe ZIP member paths: {unsafe[:3]}")
        allowed_compression={zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED}
        if any(x.compress_type not in allowed_compression for x in infos):raise ValueError("unsupported ZIP member compression")
        if zf.testzip() is not None:raise ValueError("ZIP testzip failed")
        content={n:zf.read(n) for n in names if not n.endswith("/")}
    if not EXCEPTIONS.issubset(content):raise ValueError("manifest/SHA self-reference members missing")
    manifest=json.loads(content["manifest.json"].decode("utf-8"))
    records={r["path"]:r for r in manifest.get("files",[])}
    ordinary=set(content)-EXCEPTIONS
    if set(records)!=ordinary:raise ValueError("manifest does not cover every ordinary member exactly")
    for name in sorted(ordinary):
        if len(content[name])!=records[name]["bytes"] or _sha(content[name])!=records[name]["sha256"]:
            raise ValueError(f"manifest hash/byte mismatch: {name}")
    if set(manifest.get("self_reference_exceptions",[]))!=EXCEPTIONS:
        raise ValueError("incorrect manifest self-reference exceptions")
    sums=_parse_sums(content["SHA256SUMS.txt"])
    expected={name:_sha(data) for name,data in content.items() if name!="SHA256SUMS.txt"}
    if sums!=expected:raise ValueError("SHA256SUMS.txt does not match ZIP members")
    for name,data in content.items():
        if Path(name).suffix.lower() in {".txt",".md",".json",".csv",".xml",".yaml",".yml",".py",".toml",".html"}:
            text=data.decode("utf-8",errors="strict")
            if ABSOLUTE_PATH.search(text):raise ValueError(f"absolute local path leaked in {name}")
            if any(p.search(text) for p in SECRETS):raise ValueError(f"possible secret leaked in {name}")
    if path.stat().st_size>=40*1024*1024:raise ValueError("audit ZIP exceeds 40 MB")

    with tempfile.TemporaryDirectory(prefix="optisys_s5_audit_verify_") as td:
        temp=Path(td);clean=temp/"clean";clean.mkdir()
        for name,data in content.items():
            if not _safe(name):raise ValueError(f"unsafe extraction target: {name}")
            dest=clean.joinpath(*PurePosixPath(name).parts);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            if not dest.resolve().is_relative_to(clean.resolve()):raise ValueError("extraction path escaped root")
        replay=_run_repro(clean)
        extracted_repro=(replay.returncode==0 and "REPRO_STATUS: PASS" in replay.stdout)
        if not extracted_repro:raise RuntimeError(f"clean extraction replay failed: {replay.stdout[-2000:]} {replay.stderr[-2000:]}")

        tampered=temp/"tampered";_copy_tree(clean,tampered)
        _tamper_csv(tampered/"run_evidence/full_na_ray_reference.csv")
        bad=_run_repro(tampered)
        tamper_rejected=bad.returncode!=0 and "REPRO_STATUS: FAIL" in bad.stdout
        if not tamper_rejected:raise RuntimeError("changed target coordinate was not rejected")

        deleted=temp/"deleted";_copy_tree(clean,deleted)
        (deleted/"run_evidence/lens_geometry_feasibility.csv").unlink()
        missing=_run_repro(deleted)
        deletion_rejected=missing.returncode!=0 and "REPRO_STATUS: FAIL" in missing.stdout
        if not deletion_rejected:raise RuntimeError("deleted necessary mechanical evidence was not rejected")

    return {"schema":"optisys.s5.audit_verification/1","archive_bytes":path.stat().st_size,
            "archive_sha256":_sha(path.read_bytes()),"members":len(content),"manifest_covered":len(records),
            "self_reference_exceptions":sorted(EXCEPTIONS),"zip_compression":"ZIP_DEFLATED or ZIP_STORED",
            "CONTENT_INTEGRITY":"PASS","EXTRACTED_REPRO":"PASS",
            "TAMPER_REJECTED":"PASS","DELETION_REJECTED":"PASS",
            "security_scan":"PASS","AUDIT_VERIFY":"PASS",
            "repro_stdout":replay.stdout,"tamper_stdout":bad.stdout,"deletion_stdout":missing.stdout}


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("archive",type=Path);args=parser.parse_args()
    try:result=verify_archive(args.archive)
    except Exception as exc:
        print(json.dumps({"AUDIT_VERIFY":"FAIL","error":f"{type(exc).__name__}: {exc}"},ensure_ascii=False,indent=2))
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2));print("AUDIT_VERIFY: PASS");return 0


if __name__=="__main__":raise SystemExit(main())
