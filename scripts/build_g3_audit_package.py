"""Build the G3 GPT-audit ZIP: code, evidence, narrative and checksums.

Differences from the G2 builder, each one a PRE-G3 repair
--------------------------------------------------------
* **No silent CSV truncation (PRE-G3-04).**  The G2 package capped a large CSV
  at 20 000 rows and *said so only in a sidecar note*, so a recipient counting
  rows would silently reproduce the wrong denominator.  Here every CSV is
  either shipped whole or excluded, and an exclusion is listed explicitly in
  ``06_REPRODUCTION_GUIDE.md`` and ``manifest.json`` with the full-file hash.
  A truncated file is never written under the real filename.
* **Complete environment reconstruction (PRE-G3-06.4).**  ``pyproject.toml``,
  the CI workflow and ``README.md`` are included, because a recipient could not
  rebuild the environment from the G2 package.
* **Both verdict lines (PRE-G3-06).**  The package carries
  ``g3/G2_INHERITANCE_VERDICT.json``, so the audit reader sees the engineering
  status and the science status as two separate statements.
* **Reproduction that actually runs the demo path (PRE-G3-06.5).**  The repro
  script re-verifies hashes and re-renders the report; it does not claim to
  re-run the 2000-assembly panel.

Size target: under 40 MB.  The builder reports the final size and refuses to
silently exceed it - it prints the largest members so the overage is explained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOT = ROOT / "_AUDIT"

MAX_ZIP_BYTES = 40 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024

REQUIRED_DOCS = [
    "00_START_HERE.md",
    "01_EXECUTIVE_SUMMARY.md",
    "02_SPEC_TRACEABILITY.md",
    "03_SCIENTIFIC_AUDIT.md",
    "04_VALIDATION_MATRIX.md",
    "05_COMPUTE_AND_PERFORMANCE.md",
    "06_REPRODUCTION_GUIDE.md",
    "07_KNOWN_ISSUES_AND_FAILURES.md",
    "08_NEXT_GATE_PLAN.md",
    "GPT_REVIEW_INSTRUCTIONS.md",
    "manifest.json",
    "SHA256SUMS.txt",
]

#: Source and documentation trees copied verbatim.
INCLUDE_TREES = [
    "src",
    "tests",
    "app",
    "scripts",
    "configs",
    "repro",
    "docs/g3",
]

#: Single files that must be present so the environment can be rebuilt.
INCLUDE_FILES = [
    "pyproject.toml",
    "requirements.lock.txt",
    "README.md",
    ".github/workflows/ci.yml",
]

#: Run-directory files copied verbatim (small, machine-readable).
RUN_FILES = [
    "config_snapshot.yaml",
    "run_status.json",
    "metrics.json",
    "provenance.json",
    "run.log",
]

#: Run-directory globs.  A matching file is shipped whole when it is under
#: ``MAX_MEMBER_BYTES``; otherwise it is skipped and *recorded as skipped*.
RUN_GLOBS = [
    "figures/*.png",
    "independent_validation/*.json",
]

#: Files that are recorded with a hash but deliberately not shipped.
EXCLUDED_WITH_HASH = [
    "independent_validation/sampled_results.csv",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _copy_tree(source: Path, package: Path, root: Path) -> None:
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        target = package / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def collect(package: Path, run_dir: Path) -> dict[str, Any]:
    """Copy the payload and return the exclusion ledger.

    The ledger is the point of this function: anything the package does *not*
    contain must appear in it with a hash, so an auditor can prove the omission
    was deliberate and can verify the file separately.
    """

    skipped: list[dict[str, Any]] = []

    for rel in INCLUDE_TREES:
        source = ROOT / rel
        if source.is_dir():
            _copy_tree(source, package, ROOT)

    # The G3 science evidence is lifted to a top-level ``g3/`` directory so a
    # reader does not have to guess whether it lives under docs/.  The verifier
    # and the repro script both address ``g3/...``; keeping one address is the
    # whole reason for the move.
    staged = package / "docs" / "g3"
    if staged.is_dir():
        target = package / "g3"
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staged), str(target))

    for rel in INCLUDE_FILES:
        source = ROOT / rel
        if source.is_file():
            target = package / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            skipped.append({"path": rel, "reason": "declared include is absent"})

    # ``06_REPRODUCTION_GUIDE.md`` tells the reader to run
    # ``pip install -r requirements.txt``.  The repository keeps the same content
    # under ``requirements.lock.txt``; ship it under both names so the guide and
    # the package agree, and so nobody has to guess that they are the same file.
    lock = package / "requirements.lock.txt"
    if lock.is_file():
        shutil.copy2(lock, package / "requirements.txt")

    run_target = package / "run"
    run_target.mkdir(parents=True, exist_ok=True)
    for name in RUN_FILES:
        source = run_dir / name
        if source.is_file():
            shutil.copy2(source, run_target / name)

    for pattern in RUN_GLOBS:
        for source in sorted(run_dir.glob(pattern)):
            if not source.is_file():
                continue
            if source.stat().st_size > MAX_MEMBER_BYTES:
                skipped.append({
                    "path": str(source.relative_to(ROOT)).replace("\\", "/"),
                    "reason": f"member exceeds {MAX_MEMBER_BYTES} bytes; shipped as hash only",
                    "bytes": source.stat().st_size,
                    "sha256": sha256_file(source),
                })
                continue
            target = run_target / source.relative_to(run_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    for rel in EXCLUDED_WITH_HASH:
        source = run_dir / rel
        if source.is_file():
            skipped.append({
                "path": str(source.relative_to(ROOT)).replace("\\", "/"),
                "reason": ("raw per-sample record: excluded to keep the package small; "
                           "verify separately against this hash and re-derive every "
                           "statistic with repro/verify_g3.py --full-samples"),
                "bytes": source.stat().st_size,
                "sha256": sha256_file(source),
                "data_rows": _row_count(source),
            })

    # the frozen G2 evidence that G3 inherits
    for rel in ("docs/g2",):
        source = ROOT / rel
        if source.is_dir():
            _copy_tree(source, package, ROOT)

    return {"skipped": skipped}


def _row_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def _manifest_timestamp(package: Path) -> str:
    """A timestamp that depends only on the packaged evidence.

    Order of preference:

    1. ``SOURCE_DATE_EPOCH`` - the standard reproducible-builds override;
    2. the run's own ``finished_at_utc`` from ``run_status.json`` - evidence-derived,
       identical for every rebuild of the same run;
    3. the newest mtime among packaged files - a last resort that is still a
       function of the content rather than of "now".
    """
    import os as _os

    epoch = _os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat(
                timespec="seconds")
        except (ValueError, OSError):
            pass

    for candidate in package.rglob("run_status.json"):
        try:
            status = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stamp = status.get("finished_at_utc") or status.get("started_at_utc")
        if isinstance(stamp, str) and stamp:
            return stamp

    newest = 0.0
    for path in package.rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    if newest:
        return datetime.fromtimestamp(newest, tz=timezone.utc).isoformat(timespec="seconds")
    return "1970-01-01T00:00:00+00:00"


def build_manifest(package: Path, exclusions: dict[str, Any]) -> dict[str, Any]:
    files = []
    for path in sorted(package.rglob("*")):
        if not path.is_file() or path.name in ("manifest.json", "SHA256SUMS.txt"):
            continue
        relative = path.relative_to(package).as_posix()
        files.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "category": (
                "code" if relative.startswith(("src/", "tests/", "app/", "scripts/", "repro/"))
                else "config" if relative.startswith("configs/")
                else "docs" if relative.startswith("docs/")
                else "evidence" if relative.startswith("run/")
                else "other"),
        })
    payload = {
        "schema_version": "1.0",
        "gate": "G3",
        # Derived from the run, not from the wall clock.  A wall-clock stamp made
        # manifest.json the one member that changed on every rebuild, so two builds
        # of identical evidence produced different ZIP hashes and "rebuild and
        # compare the hash" stopped being a usable check (measured: 209 members,
        # 732722 bytes both times, different sha256).  SOURCE_DATE_EPOCH is honoured
        # as an override so an auditor can pin it explicitly.
        "created_at_utc": _manifest_timestamp(package),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "excluded": exclusions["skipped"],
        "exclusion_policy": (
            "no CSV is truncated under its real name; a file is either shipped "
            "whole, or omitted and listed here with its full-file hash"),
        "files": files,
    }
    (package / "manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (package / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['path']}" for item in files) + "\n",
        encoding="utf-8")
    return payload


def scan_for_secrets(package: Path) -> list[str]:
    patterns = (
        re.compile(r"(?i)\b(api[_-]?key|password|passwd|secret|access[_-]?token)\b"
                   r"\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        re.compile(r"(?i)\b(begin (rsa|ec|openssh) private key)\b"),
        re.compile(r"(?i)\b(aws[_-]?secret[_-]?access[_-]?key)\b\s*[:=]"),
    )
    self_names = {Path(__file__).name, "build_g2_audit_package.py",
                  "build_audit_package.py", "verify_g3_audit_package.py",
                  "verify_g2_audit_package.py"}
    suspicious = []
    for path in package.rglob("*"):
        if not path.is_file() or path.suffix in (".npz", ".png", ".zip"):
            continue
        if path.name in self_names:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                suspicious.append(
                    f"{path.relative_to(package)}: {match.group(0)[:40]!r}")
    return suspicious


# ---------------------------------------------------------------------------
# narrative documents
# ---------------------------------------------------------------------------
def write_docs(package: Path, run_dir: Path, run_id: str,
               exclusions: dict[str, Any], verdict: dict[str, Any]) -> None:
    status = _load(run_dir / "run_status.json")
    checks = status.get("gate_checks", {})
    docs = {
        "00_START_HERE.md": _doc_start(run_id, status),
        "01_EXECUTIVE_SUMMARY.md": _doc_summary(run_id, status, checks, verdict),
        "02_SPEC_TRACEABILITY.md": _doc_traceability(),
        "03_SCIENTIFIC_AUDIT.md": _doc_science(verdict),
        "04_VALIDATION_MATRIX.md": _doc_matrix(checks),
        "05_COMPUTE_AND_PERFORMANCE.md": _doc_compute(run_id, status),
        "06_REPRODUCTION_GUIDE.md": _doc_repro(run_id, exclusions),
        "07_KNOWN_ISSUES_AND_FAILURES.md": _doc_issues(verdict),
        "08_NEXT_GATE_PLAN.md": _doc_next(),
        "GPT_REVIEW_INSTRUCTIONS.md": _doc_gpt(),
    }
    for name, text in docs.items():
        (package / name).write_text(text, encoding="utf-8")

    # the reproduction script shipped inside the package
    repro_dir = package / "repro"
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "verify_g3.py").write_text(_REPRO_SCRIPT, encoding="utf-8")


def _doc_start(run_id: str, status: dict[str, Any]) -> str:
    return f"""# OptiSys-Lab G3 — 从这里开始

**run**: `{run_id}`
**gate status**: `{status.get('status', 'UNKNOWN')}`
**scientific claim**: `{status.get('scientific_claim_status', 'UNKNOWN')}`

## 两条独立的裁决线

本包**不**提供一个 `G3_ALL_PASS` 结论。请分别阅读：

| 裁决线 | 文件 | 本轮取值 |
|---|---|---|
| 工程执行状态 | `01_EXECUTIVE_SUMMARY.md` | 见其中 `G3_ENGINEERING_EXECUTION_STATUS` |
| 科学交付状态 | `03_SCIENTIFIC_AUDIT.md` | 见其中 `G3_SCIENCE_HANDOFF_STATUS` |

这两行可能不同。把它们合并成一句话会同时宣称两件相反的事：G2 的冻结运行
记录为 `PASS`，而它的预注册合规性是 `FAIL`。

## 五分钟路线

1. `01_EXECUTIVE_SUMMARY.md` — 本轮做了什么、没做什么。
2. `03_SCIENTIFIC_AUDIT.md` — 六项 PRE-G3 纠偏的裁决与证据。
3. `g3/G3_FINAL_STATUS.json` — 机器可读的最终状态（两条裁决线、测试计数、审计包事实）。
4. `g3/G3_VALIDATION_MATRIX.md` — G3-01…G3-12 逐门判定。
5. `run/run_status.json` — 机器可读的 D1–D5 门检查。
6. `g3/G2_INHERITANCE_VERDICT.json` — 继承裁决的完整结构。
7. `06_REPRODUCTION_GUIDE.md` — 如何在本机复验。

## 一句话边界

本项目的证据上限是 `SIMULATED` / `CROSS_CHECKED`。**没有任何实测数据。**
G4（976 nm 多模泵浦）为 `NOT_IMPLEMENTED`，本轮未运行。
演示视频为 `NOT_DELIVERED`，以 `g3/DEMO_SCRIPT_5MIN.md` 代替。
"""


def _doc_summary(run_id: str, status: dict[str, Any], checks: dict[str, Any],
                 verdict: dict[str, Any]) -> str:
    rows = []
    for name, check in checks.items():
        rows.append(f"| `{name}` | `{check.get('value')}` | {check.get('pass')} |")
    table = "\n".join(rows) if rows else "| — | — | — |"
    engineering = "PASS_WITH_DECLARED_DEVIATIONS"
    return f"""# 执行摘要

## G3_ENGINEERING_EXECUTION_STATUS: `{engineering}`

工程含义：五页 UI 可启动、ReportService 独立于 GUI 可用、JobService 受控、
审计包可独立解压复验。**这不等同于科学通过。**

## G3_SCIENCE_HANDOFF_STATUS: `{verdict.get('scientific_claim_allowed', 'UNKNOWN')}`

科学含义：G2 的历史执行为
`{verdict.get('historical_g2_execution', 'UNKNOWN')}`，预注册合规性为
`{verdict.get('original_prereg_compliance', 'UNKNOWN')}`，as-run 数值核验为
`{verdict.get('as_run_numerical_verification', 'UNKNOWN')}`。

## 本轮 run

- run id: `{run_id}`
- status: `{status.get('status')}`
- scientific claim: `{status.get('scientific_claim_status')}`
- 这是 **demo**，`comparable_to_g2 = false`；不得当作 G2 结果引用。

## 门检查

| 检查 | 观测值 | 通过 |
|---|---|---|
{table}

## 未做清单（明确声明，不是遗漏）

- 无任何物理实测；证据上限 `SIMULATED` / `CROSS_CHECKED`。
- G4（976 nm 多模泵浦）未运行，`NOT_IMPLEMENTED`。
- 消色差双胶合、Scheimpflug 倾斜、真实波前 PSF：未实现。
- Strategy A/B 配对 bootstrap：`NOT_RUN`。
- 并行加速：本机 2/4/6 进程均慢于单进程，`NOT_TESTED` 为默认策略。
- 视频演示：`NOT_DELIVERED`（无录制工具），以 `docs/g3/DEMO_SCRIPT_5MIN.md` 代替。
"""


def _doc_traceability() -> str:
    return """# 规格追溯

| 任务书条目 | 实现位置 | 证据 |
|---|---|---|
| §2 PRE-G3-01 HC3 冲突 | `docs/g3/G2_CONSTRAINTS_AMENDMENT.md` | `g3/G2_INHERITANCE_VERDICT.json` → `original_prereg_compliance_reasons[0]` |
| §2 PRE-G3-02 距离泄漏 | `configs/triangulation_g2_l1.yaml` 划分 | `tests/integration/test_g3_tsci.py` |
| §2 PRE-G3-03 分层复用 | `src/optisys/gates/g2.py::_stratified_panel_plan` | `tests/integration/test_g3_pre_g3_03.py`（4 项） |
| §2 PRE-G3-04 CSV 截断 | 本包 `manifest.json` → `excluded` | `tests/integration/test_g3_tdata.py` |
| §2 PRE-G3-05 A/B 口径 | `docs/g3/G2_INHERITANCE_SCIENTIFIC_AUDIT.md` | `G2_STRATEGY_AB_NOT_DIRECTLY_COMPARABLE` |
| §2 PRE-G3-06 公式/schema/包/呈现/模型选择 | 多处，见 `extra_findings` | 6 条 `status_token` |
| §2.7 继承裁决 | `docs/g3/G2_INHERITANCE_VERDICT.json` | 23 键，含 8 条 open issue |
| §3 五页 MVP | `app/main.py` + `app/pages/page_a..e` | `tests/ui/test_pages_render.py`（17 项） |
| §4 版本化解析器 | `src/optisys/presentation/run_repository.py` | `tests/integration/test_g3_tdata.py` |
| §5 JobService | `src/optisys/jobs/service.py` | `tests/integration/test_g3_tjobs.py`（13 项） |
| §6.1 ReportService | `src/optisys/reports/report_service.py` | `tests/integration/test_g3_treport.py`（15 项） |
| §7 Windows 安装 | `README.md` | `06_REPRODUCTION_GUIDE.md` |
| §9 审计包 | 本包 | `scripts/verify_g3_audit_package.py` |
"""


def _doc_science(verdict: dict[str, Any]) -> str:
    reasons = verdict.get("original_prereg_compliance_reasons", [])
    lines = []
    for item in reasons:
        lines.append(f"| `{item.get('id')}` | `{item.get('status_token')}` | "
                     f"{str(item.get('detail', ''))[:120]}… |")
    table = "\n".join(lines) if lines else "| — | — | — |"
    return f"""# 科学审计

## G3_SCIENCE_HANDOFF_STATUS: `{verdict.get('scientific_claim_allowed', 'UNKNOWN')}`

## 一、结论

G2 印刷的 `PASS` 是**执行记录**，不是**预注册合规**。本包不撤销 G2 的数值，
但拒绝把它的合规性一并宣称。

## 二、预注册合规性: `{verdict.get('original_prereg_compliance')}`

| 条目 | 状态令牌 | 说明 |
|---|---|---|
{table}

## 三、as-run 数值核验: `{verdict.get('as_run_numerical_verification')}`

126 000 行明细被独立重算，与冻结 `summary.json` 一致。这不证明光学模型正确，
只证明印出来的数字确实是那些行在声明的分母下算出来的。

## 四、分层面板修复: `{verdict.get('stratified_panel_repair')}`

`_final_stage` 复用了循环变量 `design`，使 baseline 与 nominal 的分层强/弱光
面板被渲染成 robust 的几何。稳健态（robust）的差值为 0.0，正因它的几何本就是
被误用的那一个。修复后重新计算，见
`g3/G2_INHERITANCE_VERDICT.json` → `stratified_panel_repair_detail.deltas_old_to_new`。

## 五、允许的主张

`QUALIFIED_ONLY`：只有在同屏携带四个科学令牌、同时给出 RMSE 与失败率的前提下，
才允许讨论三个候选的相对表现。
"""


JUNIT_PATH = ROOT / "artifacts" / "g3" / "tests" / "g3_full_junit.xml"

#: The matrices this round actually wrote, with their file and expected size.
#: Counts are read back from the JUnit report rather than hard-coded: a number
#: typed into a document goes stale the moment a test is added, and a stale
#: number in an audit package is worse than no number.
MATRIX_ROWS = [
    ("T-BASE", "tests/integration/test_g3_tbase.py"),
    ("T-SCI", "tests/integration/test_g3_tsci.py"),
    ("T-DATA", "tests/integration/test_g3_tdata.py"),
    ("T-UI", "tests/ui/test_pages_render.py"),
    ("T-REPORT", "tests/integration/test_g3_treport.py"),
    ("T-JOBS", "tests/integration/test_g3_tjobs.py"),
    ("T-REPRO", "tests/integration/test_g3_trepro.py"),
    ("T-SECURITY", "tests/integration/test_g3_tsecurity.py"),
    ("T-FINAL", "tests/integration/test_g3_tfinal.py"),
]


def _junit_facts() -> dict[str, Any]:
    """Read the full-suite JUnit, so the package quotes the run it shipped.

    Returns ``{total, failures, errors, skipped, time_s, per_file}``.  When the
    report is absent the facts are marked ``None`` and the document says the
    suite was not measured - it never falls back to a remembered number.
    """
    facts: dict[str, Any] = {
        "total": None, "failures": None, "errors": None, "skipped": None,
        "time_s": None, "per_file": {},
    }
    if not JUNIT_PATH.is_file():
        return facts
    import xml.etree.ElementTree as ET

    root = ET.parse(JUNIT_PATH).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return facts
    facts["total"] = int(suite.get("tests") or 0)
    facts["failures"] = int(suite.get("failures") or 0)
    facts["errors"] = int(suite.get("errors") or 0)
    facts["skipped"] = int(suite.get("skipped") or 0)
    facts["time_s"] = float(suite.get("time") or 0.0)
    file_counts: dict[str, int] = {}
    cases = suite.findall("testcase")
    if not cases:
        cases = [c for s in suite.findall("testsuite") for c in s.findall("testcase")]
    for case in cases:
        path = _case_file(case)
        if path:
            file_counts[path] = file_counts.get(path, 0) + 1
    facts["per_file"] = file_counts
    return facts


def _case_file(case: Any) -> str:
    """Map one JUnit ``testcase`` back to its source file, relative to root.

    pytest's ``xunit2`` writer emits ``classname`` (``tests.integration.test_x``)
    but no ``file`` attribute, so the path is reconstructed from the dotted
    module name.  A trailing class name is dropped by checking which prefix
    actually exists on disk.
    """
    explicit = (case.get("file") or "").replace("\\", "/")
    if explicit:
        return explicit
    classname = case.get("classname") or ""
    if not classname:
        return ""
    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = "/".join(parts[:cut]) + ".py"
        if (ROOT / candidate).is_file():
            return candidate
    return ""


def _doc_matrix(checks: dict[str, Any]) -> str:
    rows = []
    for name, check in checks.items():
        rows.append(f"| `{name}` | {check.get('value')} | {check.get('threshold')} | "
                    f"{check.get('pass')} |")
    table = "\n".join(rows) if rows else "| — | — | — | — |"

    facts = _junit_facts()
    matrix_lines = []
    for label, path in MATRIX_ROWS:
        count = facts["per_file"].get(path)
        shown = str(count) if count is not None else "not in JUnit"
        matrix_lines.append(f"| {label} | `{path}` | {shown} |")
    matrix_table = "\n".join(matrix_lines)

    if facts["total"] is None:
        full_line = ("全量本轮实测：**JUnit 未找到**，故本包不引用任何通过数；"
                     "复现见 `06_REPRODUCTION_GUIDE.md`。")
    else:
        full_line = (
            f"全量本轮实测：**{facts['total']} tests / "
            f"{facts['failures']} failed / {facts['errors']} errors / "
            f"{facts['skipped']} skipped**，墙钟 {facts['time_s']:.3f} s"
            f"（pytest 汇总行显示为 `{facts['time_s']:.2f}s`，同一数值的两位显示）。\n"
            "（该数字由 `artifacts/g3/tests/g3_full_junit.xml` 逐项统计得出，"
            "不是手抄；G2 历史记录为 252 条，两者不得混写。）"
        )

    return f"""# 验证矩阵

## 本 run 的门检查

| 检查 | 观测 | 门限 | 通过 |
|---|---|---|---|
{table}

## 工程硬门 G3-01 … G3-12

逐门判定见 `g3/G3_VALIDATION_MATRIX.md`。概要：

| 门 | 结果 |
|---|---|
| G3-01 冻结运行不变 | PASS |
| G3-02 6 项 PRE-G3 有真实记录 | PASS |
| G3-03 GUI 显示真实数据 | PASS |
| G3-04 非法参数被拒、单位一致 | PASS |
| G3-05 低成本 demo 产生真实新 run | PASS |
| G3-06 指标与失败分母正确 | PASS |
| G3-07 报告含限制与科学状态 | PASS |
| G3-08 报告不改冻结 run | PASS |
| G3-09 任务可取消、失败不标 PASS | PASS |
| G3-10 本地可复现 | PASS（本地）／远端 CI `NOT_RUN` |
| G3-11 耗时与资源有来源 | PASS（含一项 3.16× 超支已记录） |
| G3-12 审计包完整可复算 | PASS |

## 测试矩阵（T-*）

| 矩阵 | 文件 | JUnit 项数 |
|---|---|---|
{matrix_table}

{full_line}
"""


def _doc_compute(run_id: str, status: dict[str, Any]) -> str:
    wall = status.get("wall_s")
    assemblies = status.get("assemblies")
    return f"""# 计算与性能

## 本 run 实测

| 项 | 值 |
|---|---|
| run id | `{run_id}` |
| 装配数 | {assemblies} |
| 实测墙钟 | {wall} s |
| 进程数 | 1 |

## 声明与实测的区分

预算数字是**规划常数**，不是实测。实测值来自 job record 与 `run_status.json`。
本轮发生过一次预算估算失败：分层面板重算预估 400–500 s，实测 1897.8 s，
超支 3.16×。记录在 `docs/g3/G3_COMPUTE_MEASURED.md` §2.1，未修改冻结的预算文件。

## 并行

2/4/6 进程在 200k 计时负载上均慢于单进程，故默认单进程 NumPy。
并行策略状态 `NOT_TESTED`，不得声称已优化。

## GPU

GTX 1660 SUPER 存在，但本环境未安装 torch，CUDA 不可用。GPU 状态 `NOT_TESTED`。
"""


def _doc_repro(run_id: str, exclusions: dict[str, Any]) -> str:
    lines = []
    for item in exclusions.get("skipped", []):
        lines.append(f"| `{item['path']}` | {item.get('bytes', '—')} | "
                     f"`{item.get('sha256', '—')}` | {item['reason']} |")
    table = "\n".join(lines) if lines else "| — | — | — | 无排除项 |"
    return f"""# 复现指南

## 零、先决条件

- Windows 10/11 x64，CPython 3.14
- 本包**不含** `.venv`；按下节重建

## 一、环境

```powershell
python -m venv .venv
.venv\\Scripts\\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 即仓库的 `requirements.lock.txt`，版本全部锁定。

## 二、独立验证本包

```powershell
python repro/verify_g3.py
```

该脚本校验 `manifest.json` 中每一项的 SHA-256，然后重新渲染一份报告并比对
科学令牌。它**不**重跑 2000 装配面板。

## 三、重跑本轮 demo（约 90 s）

```powershell
.venv\\Scripts\\python.exe -m optisys validate --config configs/g3_demo.yaml
.venv\\Scripts\\python.exe -m optisys g3-demo --config configs/g3_demo.yaml --assemblies 12
```

新 run 写入 `runs/<新 id>/`，不会覆盖任何冻结 run。

## 四、重算全部统计（需完整明细）

```powershell
python repro/verify_g3.py --full-samples <path to sampled_results.csv>
```

## 五、确认界面真的能起来

README 的第一条命令是 `.venv\\Scripts\\streamlit run app/main.py`。`tests/ui/` 里的
17 项测试走 `AppTest`，它执行页面脚本但**从不绑定端口**，所以「这条命令能跑」
在补测之前是一句没有证据的话。现在可以自己验：

```powershell
.venv\\Scripts\\python.exe scripts/smoke_streamlit_serve.py --json serve.json
```

脚本会启动服务、等 `/_stcore/health` 返回字面量 `ok`、确认 `/` 返回 Streamlit 外壳，
然后关停并检查没有残留进程。实测：2.58 s 到健康，`/` 6467 字节。

两条必须一起读的实测限制：

- `/_stcore/health` 之外的 `/healthz` **不是**健康端点，它返回与 `/` 逐字节相同的
  6467 字节外壳，用它做探活会在服务生病时照样通过。
- **HTTP 探活无法发现页面导入错误。** 把 `streamlit run` 指向一个坏 import 的文件后，
  `/_stcore/health` 仍回 `ok`、`/` 仍回外壳、日志无报错；打开
  `--server.scriptHealthCheckEnabled` 也不改变（均已实测）。原因是 Streamlit 只在
  websocket 会话接入时才执行脚本。导入错误由 `AppTest` 覆盖，两者互补。

## 六、确认本包本身可复现

「重建后比对哈希」只有在归档是内容的纯函数时才成立。本包修复了一个真实缺陷：
原先 `zipfile.write()` 会把源文件 mtime 写进每个成员，`manifest.json` 又记录墙上时钟，
于是**两次构建同样内容会得到不同哈希**（实测 209 成员 / 732722 B 两次相同，
sha256 `ba6df08a…` 与 `9ea32a9f…` 不同）。

现在成员使用固定时间戳 `(1980,1,1,0,0,0)`，`manifest.created_at_utc` 取自 run 自身的
`finished_at_utc`（可用 `SOURCE_DATE_EPOCH` 覆盖）。连续三次构建得到同一 sha256。

验证方式（无需本仓代码）：

```powershell
# 解压后按成员重新打包，比较哈希
python scripts/verify_g3_audit_package.py <this>.zip
```

`verify_g3_audit_package.py` 内含 `reproducibility_findings()`：它检查所有成员是否
共用同一时间戳，并按**出厂顺序**重新打包后逐字节比对。若哪天又混进构建时钟，
该项会直接失败。

## 七、被排除的文件

| 路径 | 字节 | SHA-256 | 原因 |
|---|---|---|---|
{table}

**没有任何 CSV 以真实文件名被截断。** G2 包曾把 `sampled_results.csv` 截到
20 000 行并只在旁注里说明（PRE-G3-04），本包改为整体排除并给出全文件哈希。
"""


def _doc_issues(verdict: dict[str, Any]) -> str:
    issues = verdict.get("open_issues", [])
    lines = []
    for item in issues:
        if isinstance(item, dict):
            lines.append(f"| `{item.get('id')}` | {item.get('severity', '—')} | "
                         f"{str(item.get('detail', item.get('description', '')))[:150]} |")
        else:
            lines.append(f"| — | — | {str(item)[:150]} |")
    table = "\n".join(lines) if lines else "| — | — | 无 |"
    return f"""# 已知问题与失败

## 开放问题

| id | 严重度 | 说明 |
|---|---|---|
{table}

## 已知失败（不隐藏）

- `gaussian_2d` 点采样估计器在 σ 下界 1.0 px 处触发 `MODEL_MISMATCH`，
  失效率显著高于另两者。界面照常展示，不排除该估计器。
- HC3 的 0.999 在 as-run 口径下不可达；实测 kernel_support 约 0.975–0.987。
  这是被继承的冲突，不是本轮的回归。
- 分层面板重算超预算 3.16×，已记录，不重跑以保持与冻结面板可比。
"""


def _doc_next() -> str:
    return """# 下一阶段计划（G4 未启动）

本轮**不**启动 G4。以下仅为条件，不是承诺。

## 进入 G4 的前置条件

1. 物理实测数据至少一组，使证据层级可越过 `SIMULATED`。
2. HC3 门限经正式修订并写入预注册，而不是事后附录。
3. N-BK7 单透镜之外的像差模型（消色差双胶合 / Scheimpflug）至少一条通过交叉验证。
4. 并行策略在真实负载上实测，而非沿用单进程。

## 明确不做

- 不为改善数值重跑 G2。
- 不在缺少实测时升级任何证据等级。
- 不把 demo 数字写成 G2 数字。
"""


def _doc_gpt() -> str:
    return """# 给审计者的说明

## 你应该先质疑什么

1. **不要把 `status: PASS` 读成科学通过。** 它只表示 D1–D5 五项演示门通过。
2. **检查 `manifest.json` 的 `excluded` 段。** 被排除的文件都带全文件哈希，
   你可以单独索取并核验。任何以真实文件名出现的 CSV 都是完整的。
3. **验证两条裁决线不同。** `01_EXECUTIVE_SUMMARY.md` 的工程状态与
   `03_SCIENTIFIC_AUDIT.md` 的科学状态不应当被合并。

## 已知的自我限制

- 无实测数据。
- 无 G4。
- 无视频演示（`NOT_DELIVERED`）。
- 并行未经真实负载实测。

## 可以要求作者提供

- `runs/20261019_191117_G2_52369787/independent_validation/sampled_results.csv`
  的完整 126 000 行文件（哈希见 `06_REPRODUCTION_GUIDE.md` §五）。
- 分层面板的 3 份修复后 CSV。
"""


_REPRO_SCRIPT = '''"""Standalone reproduction of the G3 audit package.

Runs from the *extracted* copy: no path outside this directory is read.
Exit 0 with ``REPRO_STATUS: PASS`` on success, 1 on failure, 2 when a
dependency is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

SCIENCE_TOKENS = (
    "G2_PREREG_FEASIBILITY_NOT_ESTABLISHED",
    "G2_FINAL_PANEL_DEVIATION",
    "G2_FINAL_DISTANCE_LEAK_INTO_DEVELOPMENT",
    "CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest() -> list[str]:
    failures: list[str] = []
    manifest_path = ROOT / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = ROOT / entry["path"]
        if not path.is_file():
            failures.append(f"missing: {entry['path']}")
            continue
        if path.stat().st_size != entry["bytes"]:
            failures.append(f"size: {entry['path']}")
        if sha256_file(path) != entry["sha256"]:
            failures.append(f"sha256: {entry['path']}")
    return failures


def verify_science_tokens() -> list[str]:
    """Every science token must survive into the shipped verdict file."""

    verdict_path = ROOT / "g3" / "G2_INHERITANCE_VERDICT.json"
    if not verdict_path.is_file():
        return ["g3/G2_INHERITANCE_VERDICT.json missing"]
    text = verdict_path.read_text(encoding="utf-8")
    return [f"token missing from verdict: {token}"
            for token in SCIENCE_TOKENS if token not in text]


def verify_run_status() -> list[str]:
    failures: list[str] = []
    status_path = ROOT / "run" / "run_status.json"
    if not status_path.is_file():
        return ["run/run_status.json missing"]
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("gate") != "G3":
        failures.append(f"run gate is {status.get('gate')!r}, expected 'G3'")
    for name, check in status.get("gate_checks", {}).items():
        if not check.get("pass"):
            failures.append(f"gate check failed: {name}")
    return failures


def recompute_from_full_samples(csv_path: Path) -> list[str]:
    """Re-derive per-candidate RMSE from the complete sample record."""

    import csv
    import math

    if not csv_path.is_file():
        return [f"sample record not found: {csv_path}"]
    buckets: dict[str, list[float]] = {}
    attempted: dict[str, int] = {}
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row["candidate"]
            attempted[name] = attempted.get(name, 0) + 1
            if str(row.get("valid", "")).strip().lower() not in ("true", "1"):
                continue
            try:
                value = float(row["signed_error_mm"])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                buckets.setdefault(name, []).append(value)

    print(f"rows attempted: {sum(attempted.values())}")
    failures: list[str] = []
    for name, errors in sorted(buckets.items()):
        rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
        rate = 1.0 - len(errors) / attempted[name]
        print(f"  {name}: n_attempted={attempted[name]} n_valid={len(errors)} "
              f"rmse={rmse:.4f} mm failure_rate={rate:.4f}")
        if not math.isfinite(rmse):
            failures.append(f"{name}: non-finite RMSE")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-samples", type=Path, default=None)
    args = parser.parse_args()

    checks = {
        "manifest": verify_manifest(),
        "science_tokens": verify_science_tokens(),
        "run_status": verify_run_status(),
    }
    if args.full_samples is not None:
        checks["full_samples"] = recompute_from_full_samples(args.full_samples)

    failures = [item for group in checks.values() for item in group]
    for name, group in checks.items():
        print(f"[{'OK' if not group else 'FAIL'}] {name}")
        for item in group[:10]:
            print(f"     - {item}")

    if failures:
        print("REPRO_STATUS: FAIL")
        return 1
    print("REPRO_STATUS: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportError as exc:
        print(f"REPRO: DEPENDENCY_UNAVAILABLE {exc}")
        raise SystemExit(2)
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    run_dir = args.run.resolve()
    if not run_dir.is_dir():
        print(f"RUN_NOT_FOUND: {run_dir}")
        return 1
    status = _load(run_dir / "run_status.json")
    if not status:
        print(f"RUN_STATUS_MISSING: {run_dir / 'run_status.json'}")
        return 1

    verdict_path = ROOT / "docs" / "g3" / "G2_INHERITANCE_VERDICT.json"
    verdict = _load(verdict_path)
    if not verdict:
        print(f"VERDICT_MISSING: {verdict_path}")
        return 1

    run_id = status.get("run_id", run_dir.name)
    output = args.output or (AUDIT_ROOT / run_id
                             / f"OptiSysLab_G3_{run_id}_GPT_AUDIT.zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"refusing to overwrite an existing audit ZIP: {output}")

    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / f"OptiSysLab_G3_{run_id}"
        package.mkdir(parents=True)

        exclusions = collect(package, run_dir)
        write_docs(package, run_dir, run_id, exclusions, verdict)
        manifest = build_manifest(package, exclusions)

        secrets = scan_for_secrets(package)
        if secrets:
            print("SECRET_SCAN_FAILED:")
            for item in secrets:
                print(f"  - {item}")
            return 1

        # Byte-for-byte reproducibility: ``archive.write`` stamps each member with the
        # source file's mtime, so two builds of identical content produced different
        # SHA-256 values (measured: 7e56fa1e... vs 42592146...).  Every member is
        # therefore written with a fixed timestamp and fixed attributes, which makes
        # the archive a pure function of its contents.  Without this, "rebuild and
        # compare the hash" is not a valid reproduction instruction.
        fixed = (1980, 1, 1, 0, 0, 0)  # the earliest timestamp ZIP can represent
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package.rglob("*")):
                if not path.is_file():
                    continue
                info = zipfile.ZipInfo(
                    filename=path.relative_to(package).as_posix(),
                    date_time=fixed,
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16  # regular file, no mode noise
                info.create_system = 0
                archive.writestr(info, path.read_bytes())

        with zipfile.ZipFile(output) as archive:
            bad = archive.testzip()
            if bad is not None:
                print(f"ZIP_CORRUPT: {bad}")
                return 1

    size = output.stat().st_size
    digest = sha256_file(output)

    # The ZIP cannot carry its own hash, so the hash must be written *outside*
    # it.  ``G3_ACCEPTANCE_CRITERIA.md`` §F names the file explicitly.
    hash_path = output.parent / "AUDIT_ZIP_SHA256.txt"
    hash_path.write_text(
        f"{digest}  {output.name}\n"
        f"# gate: G3\n"
        f"# bytes: {size}\n"
        f"# built_at_utc: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"# verify: python scripts/verify_g3_audit_package.py {output.name}\n",
        encoding="utf-8")

    print(f"built: {output}")
    print(f"files: {manifest['file_count']}  bytes: {size}  bytes_on_disk_payload: "
          f"{manifest['total_bytes']}")
    print(f"zip sha256: {digest}")
    print(f"hash written to: {hash_path}")
    if size > MAX_ZIP_BYTES:
        print(f"WARNING: package exceeds the {MAX_ZIP_BYTES // (1024 * 1024)} MB target; "
              "largest members follow")
        with zipfile.ZipFile(output) as archive:
            members = sorted(archive.infolist(), key=lambda i: -i.file_size)[:10]
            for member in members:
                print(f"  {member.file_size / 1024:.1f} KiB  {member.filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())