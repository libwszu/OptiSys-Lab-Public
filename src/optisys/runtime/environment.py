"""Hardware and software environment probing.

Every field is either measured or explicitly ``UNKNOWN``.  Nothing is inferred
from a marketing name: a GTX 1660 SUPER is not treated as proof that CUDA is
usable, and a missing ``nvidia-smi`` is reported as such.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import psutil

UNKNOWN = "UNKNOWN"

_PACKAGE_PROBES = (
    "numpy",
    "scipy",
    "matplotlib",
    "pandas",
    "psutil",
    "yaml",
    "pytest",
    "optiland",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cpu_model() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            try:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return str(value).strip()
            finally:
                winreg.CloseKey(key)
        except Exception:  # pragma: no cover - platform specific
            return platform.processor() or UNKNOWN
    return platform.processor() or UNKNOWN


def _git_commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "NO_COMMIT"
    if result.returncode != 0:
        return "NO_COMMIT"
    commit = result.stdout.strip()
    return commit if commit else "NO_COMMIT"


def _gpu_info() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"available": False, "reason": "nvidia-smi not found on PATH", "devices": []}
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,memory.used,driver_version,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": f"nvidia-smi failed: {exc}", "devices": []}
    if result.returncode != 0:
        return {
            "available": False,
            "reason": f"nvidia-smi exit {result.returncode}: {result.stderr.strip()[:200]}",
            "devices": [],
        }
    devices = []
    for line in result.stdout.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 4:
            devices.append(
                {
                    "name": parts[0],
                    "memory_total_mb": _to_number(parts[1]),
                    "memory_used_mb": _to_number(parts[2]),
                    "driver_version": parts[3],
                    "compute_capability": parts[4] if len(parts) > 4 else UNKNOWN,
                }
            )
    return {"available": bool(devices), "reason": None, "devices": devices}


def _to_number(value: str) -> float | str:
    try:
        return float(value)
    except (TypeError, ValueError):
        return UNKNOWN


def _torch_info() -> dict[str, Any]:
    try:
        torch = importlib.import_module("torch")
    except Exception:
        return {"installed": False, "cuda_available": "NOT_INSTALLED", "version": None}
    try:
        return {
            "installed": True,
            "version": getattr(torch, "__version__", UNKNOWN),
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
            "device_count": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"installed": True, "cuda_available": "UNKNOWN", "error": str(exc)[:200]}


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in _PACKAGE_PROBES:
        try:
            module = importlib.import_module(name)
        except Exception:
            versions[name] = "NOT_INSTALLED"
            continue
        versions[name] = str(getattr(module, "__version__", UNKNOWN))
    return versions


def _optiland_probe() -> dict[str, Any]:
    try:
        import optiland  # noqa: F401
    except Exception as exc:
        return {"installed": False, "version": None, "import_error": str(exc)[:200]}
    try:
        from importlib.metadata import version

        package_version = version("optiland")
    except Exception:
        package_version = str(getattr(optiland, "__version__", UNKNOWN))
    try:
        from optiland import optic  # noqa: F401

        api_import = "optiland.optic:Optic"
    except Exception:
        api_import = "UNKNOWN"
    return {"installed": True, "version": package_version,
            "api_import": api_import, "lens_case_executed": False}


def collect_environment(project_root: Path) -> dict[str, Any]:
    """Collect a reproducible snapshot of the machine and the toolchain."""

    root = Path(project_root)
    virtual = psutil.virtual_memory()
    disk = shutil.disk_usage(str(root))
    cpu_freq = psutil.cpu_freq()
    load = psutil.cpu_percent(interval=0.5, percpu=False)

    packages = _package_versions()
    gpu = _gpu_info()
    torch_info = _torch_info()

    try:
        git = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
        git_dirty = bool(git.stdout.strip()) if git.returncode == 0 else "NO_REPO"
    except (OSError, subprocess.SubprocessError):
        git_dirty = "UNKNOWN"

    return {
        "schema_version": "1.0",
        "collected_at_utc": _utc_now(),
        "project_root": str(root),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "windows_build": platform.win32_ver()[1] if platform.system() == "Windows" else None,
        },
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": Path(sys.executable).name,
            "in_venv": sys.prefix != sys.base_prefix,
        },
        "cpu": {
            "model": _cpu_model(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "max_frequency_mhz": round(cpu_freq.max, 1) if cpu_freq else UNKNOWN,
            "current_frequency_mhz": round(cpu_freq.current, 1) if cpu_freq else UNKNOWN,
            "utilization_percent_snapshot": load,
        },
        "memory": {
            "total_gb": round(virtual.total / 1024**3, 2),
            "available_gb": round(virtual.available / 1024**3, 2),
            "used_percent_snapshot": virtual.percent,
        },
        "gpu": gpu,
        "cuda": {
            "torch": torch_info,
            "numpy_version": np.__version__,
            "note": "GPU model alone is not evidence of usable CUDA; see torch.cuda_available",
        },
        "disk": {
            "root": str(root),
            "free_gb": round(disk.free / 1024**3, 2),
            "total_gb": round(disk.total / 1024**3, 2),
        },
        "git": {
            "commit": _git_commit(root),
            "dirty": git_dirty,
        },
        "packages": packages,
        "optiland": _optiland_probe(),
        "environment_variables": {
            key: os.environ.get(key, "UNSET")
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                        "NUMEXPR_NUM_THREADS")
        },
    }


if __name__ == "__main__":  # pragma: no cover - manual probe
    print(json.dumps(collect_environment(Path.cwd()), indent=2, ensure_ascii=False))
