"""Run directory management, provenance hashing and status reporting.

Every run gets an immutable, unique directory ``runs/<run_id>/``.  History is
never overwritten: a collision raises instead of silently reusing a folder.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import optisys


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_tree_digest(root: Path, subdir: str = "src") -> str:
    """Deterministic digest of all ``*.py`` files under *root/subdir*."""

    base = Path(root) / subdir
    files = sorted(path for path in base.rglob("*.py") if "__pycache__" not in path.parts)
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(Path(root)).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def new_run_id(gate: str, config_sha256: str, when: datetime | None = None) -> str:
    """``YYYYMMDD_HHMMSS_<gate>_<config-hash prefix>`` in UTC."""

    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    short = config_sha256[:8] if config_sha256 and config_sha256 != "UNKNOWN" else "nohash"
    return f"{stamp}_{gate}_{short}"


@dataclass
class RunContext:
    project_root: Path
    gate: str
    config_sha256: str
    config_path: Path | None = None
    runs_dir: Path | None = None
    run_id: str = ""
    directory: Path = field(init=False)
    _log_lines: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        root = Path(self.project_root)
        runs = Path(self.runs_dir) if self.runs_dir else root / "runs"
        if not self.run_id:
            self.run_id = new_run_id(self.gate, self.config_sha256)
        candidate = self.run_id
        suffix = 1
        while (runs / candidate).exists():
            candidate = f"{self.run_id}-{suffix:02d}"
            suffix += 1
        self.run_id = candidate
        self.directory = runs / self.run_id
        (self.directory / "figures").mkdir(parents=True)
        (self.directory / "checkpoints").mkdir()
        self.log(f"run {self.run_id} created at {utc_now()}")

    # ------------------------------------------------------------------
    def path(self, name: str) -> Path:
        return self.directory / name

    def log(self, message: str) -> None:
        line = f"[{utc_now()}] {message}"
        self._log_lines.append(line)
        print(line, flush=True)

    def flush_log(self) -> Path:
        target = self.path("run.log")
        target.write_text("\n".join(self._log_lines) + "\n", encoding="utf-8")
        return target

    def write_json(self, name: str, payload: dict[str, Any]) -> Path:
        target = self.path(name)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return target

    def write_text(self, name: str, text: str) -> Path:
        target = self.path(name)
        target.write_text(text, encoding="utf-8")
        return target

    def snapshot_config(self, config_path: Path) -> Path:
        source = Path(config_path)
        target = self.path("config_snapshot.yaml")
        target.write_bytes(source.read_bytes())
        if _sha256_file(source) != _sha256_file(target):
            raise RuntimeError("config snapshot hash mismatch")
        return target

    def provenance(self, *, model_level: str, seeds: list[int],
                   extra: dict[str, Any] | None = None) -> dict[str, Any]:
        root = Path(self.project_root)
        config_snapshot = self.path("config_snapshot.yaml")
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "project": "OptiSys-Lab",
            "gate": self.gate,
            "run_id": self.run_id,
            "created_at_utc": utc_now(),
            "code": {
                "package_version": optisys.__version__,
                "model_level": model_level,
                "source_tree_sha256": source_tree_digest(root),
                "source_tree_scope": "src/**/*.py (sorted relative path + sha256)",
                "git_commit": _git_commit(root),
            },
            "inputs": {
                "config_path": str(self.config_path) if self.config_path else None,
                "config_sha256": self.config_sha256,
                "config_snapshot_sha256": _sha256_file(config_snapshot)
                if config_snapshot.exists() else None,
            },
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
            "random_seeds": seeds,
            "determinism": {
                "rng": "numpy.random.default_rng / SeedSequence",
                "note": "G0 geometry is deterministic; the seed controls sampling order only",
            },
        }
        if extra:
            payload["extra"] = extra
        return payload

    def finalise(self, status: str, gate_checks: dict[str, Any],
                 scientific_claim_status: str, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "gate": self.gate,
            "status": status,
            "scientific_claim_status": scientific_claim_status,
            "finished_at_utc": utc_now(),
            "gate_checks": gate_checks,
            "outputs": sorted(
                path.relative_to(self.directory).as_posix()
                for path in self.directory.rglob("*")
                if path.is_file()
            ),
        }
        if extra:
            payload["extra"] = extra
        self.write_json("run_status.json", payload)
        self.flush_log()


def _git_commit(root: Path) -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "NO_COMMIT"
    return result.stdout.strip() if result.returncode == 0 else "NO_COMMIT"
