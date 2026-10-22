"""Build and install a clean Python 3.11 release-check environment."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - host venv has psutil
    psutil = None

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".venv_s6r_release"
OUT = ROOT / "artifacts" / "s6r" / "environment"


def run(command: list[str], timeout_s: float, stdout_path: Path, stderr_path: Path) -> dict[str, object]:
    start_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    with stdout_path.open("w", encoding="utf-8", newline="") as out, stderr_path.open("w", encoding="utf-8", newline="") as err:
        process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, text=True)
        timed_out = False
        try:
            code = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            if psutil is not None:
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    for child in reversed(children):
                        try:
                            child.terminate()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    try:
                        parent.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    _, alive = psutil.wait_procs(children + [parent], timeout=5)
                    for item in alive:
                        try:
                            item.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if process.poll() is None:
                process.kill()
            process.wait()
            code = 124
    return {
        "command": command,
        "started_at_utc": start_utc,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_s": time.monotonic() - started,
        "timeout_s": timeout_s,
        "timed_out": timed_out,
        "exit_code": code,
        "stdout_path": str(stdout_path.relative_to(ROOT)).replace("\\", "/"),
        "stderr_path": str(stderr_path.relative_to(ROOT)).replace("\\", "/"),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if ENV.exists():
        raise SystemExit(f"Refusing to reuse or overwrite existing environment: {ENV}")
    create_stdout, create_stderr = OUT / "venv_create_stdout.txt", OUT / "venv_create_stderr.txt"
    create = run(["py", "-3.11", "-m", "venv", str(ENV)], 90, create_stdout, create_stderr)
    results: dict[str, object] = {"schema": "optisys.s6r.environment_install/1", "python_selector": "py -3.11", "target_environment": str(ENV), "create_venv": create}
    if create["exit_code"] != 0 or create["timed_out"]:
        (OUT / "install_status.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(results, indent=2))
        return int(create["exit_code"])

    python = ENV / "Scripts" / "python.exe"
    install = run([str(python), "-m", "pip", "install", "-e", ".[dev,ui,optics]"], 300, OUT / "install_stdout.txt", OUT / "install_stderr.txt")
    results["install"] = install
    if install["exit_code"] == 0 and not install["timed_out"]:
        freeze = subprocess.run([str(python), "-m", "pip", "freeze"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        (OUT / "pip_freeze.txt").write_text(freeze.stdout, encoding="utf-8")
        (OUT / "pip_freeze_stderr.txt").write_text(freeze.stderr, encoding="utf-8")
        versions_script = (
            "import json,platform,sys,importlib.metadata as m; "
            "names=['numpy','pandas','scipy','streamlit','optiland','matplotlib','PyYAML','psutil','pytest']; "
            "print(json.dumps({'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'packages':{n:(m.version(n) if any(d.metadata['Name'].lower()==n.lower() for d in m.distributions()) else None) for n in names}},indent=2))"
        )
        version_run = subprocess.run([str(python), "-c", versions_script], cwd=ROOT, capture_output=True, text=True, timeout=60)
        (OUT / "environment_versions.json").write_text(version_run.stdout + ("\n" + version_run.stderr if version_run.stderr else ""), encoding="utf-8")
        results["pip_freeze_exit_code"] = freeze.returncode
        results["version_probe_exit_code"] = version_run.returncode
        if version_run.returncode == 0:
            results["environment"] = json.loads(version_run.stdout)
    results["status"] = "PASS" if install["exit_code"] == 0 and not install["timed_out"] else "FAIL"
    (OUT / "install_status.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if results["status"] == "PASS" else int(install["exit_code"] or 1)


if __name__ == "__main__":
    raise SystemExit(main())
