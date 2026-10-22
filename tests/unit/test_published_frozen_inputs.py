"""Negative controls for byte-level publication checks."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_published_frozen_inputs.py"


def _copy_inputs(tmp_path):
    manifest_path = "docs/g4/G4_FREEZE_HASHES.json"
    manifest = json.loads((ROOT / manifest_path).read_bytes())
    for name in [manifest_path, *(entry["path"] for entry in manifest["inputs"])]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path / manifest["inputs"][0]["path"]


def _run(root):
    proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                          capture_output=True, text=True, check=False)
    return proc.returncode, json.loads(proc.stdout)


def test_original_bytes_pass():
    code, result = _run(ROOT)
    assert code == 0
    assert result["status"] == "PASS"


def test_crlf_conversion_is_rejected_without_rewriting(tmp_path):
    target = _copy_inputs(tmp_path)
    changed = target.read_bytes().replace(b"\n", b"\r\n")
    target.write_bytes(changed)
    code, result = _run(tmp_path)
    assert code != 0
    assert result["files"][0]["status"] == "FAIL"
    assert target.read_bytes() == changed


def test_same_size_tampering_is_rejected(tmp_path):
    target = _copy_inputs(tmp_path)
    data = target.read_bytes()
    target.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    code, result = _run(tmp_path)
    assert code != 0
    assert result["files"][0]["bytes"] == len(data)


def test_missing_input_is_rejected(tmp_path):
    target = _copy_inputs(tmp_path)
    target.unlink()
    code, result = _run(tmp_path)
    assert code != 0
    assert result["files"][0]["error"] == "FileNotFoundError"
