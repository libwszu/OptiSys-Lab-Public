"""Apply the frozen cross-scenario tail rule to the completed S6-C metrics."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20261021_024715_S6_P1"
RUN = ROOT / "runs" / RUN_ID
C_DIR = RUN / "s6_c_assemblies"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pp(x: float) -> str:
    return f"{100.0 * float(x):+.2f}"


def apply() -> dict:
    raw_path = C_DIR / "assembly_statistics_programmatic.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if raw.get("status") != "COMPLETE" or raw.get("S6_C_ASSEMBLY_CLAIM") != "SUPPORTED_WITHIN_ASSUMED_P1_AND_TOLERANCES":
        raise ValueError("unexpected programmatic S6-C status; refusing to adjudicate")
    original_run_status = json.loads((C_DIR / "run_status_programmatic.json").read_text(encoding="utf-8"))
    nominal = raw["scenarios"]["nominal_1x"]
    stress = raw["scenarios"]["stress_2x"]
    if stress["p05_paired_delta_capture"] >= 0.0 or stress["p05_paired_delta_bootstrap_ci95"][1] >= 0.0:
        raise ValueError("registered stress tail no longer meets the documented tradeoff trigger")
    failure_delta = stress["failure_weight_mean_delta_candidate_minus_baseline"]
    if failure_delta.get("L2_APERTURE_BLOCK", 0.0) <= 0.0:
        raise ValueError("expected stress-tier L2 aperture loss was not present")

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    adjudication = {
        "schema": "optisys.s6.c_final_adjudication/1", "run_id": RUN_ID,
        "S6_C_ASSEMBLY_CLAIM": "TRADEOFF_OR_NO_SUPPORTED_GAIN",
        "automatic_nominal_only_claim": raw["S6_C_ASSEMBLY_CLAIM"],
        "computational_run_status": "COMPLETE",
        "scope": "aggregate across the four registered zero/tight/nominal/stress tolerance scenarios",
        "reason": "The preregistered lower-tail/failure-cost clause applies to the full declared sensitivity envelope. The nominal primary estimand is positive, but the registered 2x stress tier has a negative paired P05 delta with a bootstrap interval below zero and additional candidate L2 aperture blocking.",
        "nominal_primary": {
            "mean_delta_capture": nominal["mean_delta_capture_candidate_minus_baseline"],
            "mean_delta_ci95": nominal["paired_mean_delta_capture_ci95"],
            "p05_paired_delta": nominal["p05_paired_delta_capture"],
            "p05_paired_delta_ci95": nominal["p05_paired_delta_bootstrap_ci95"],
            "n_complete_pairs": nominal["n_complete_pairs"],
        },
        "stress_2x": {
            "mean_delta_capture": stress["mean_delta_capture_candidate_minus_baseline"],
            "mean_delta_ci95": stress["paired_mean_delta_capture_ci95"],
            "p05_paired_delta": stress["p05_paired_delta_capture"],
            "p05_paired_delta_ci95": stress["p05_paired_delta_bootstrap_ci95"],
            "L2_aperture_block_weight_delta_candidate_minus_baseline": failure_delta["L2_APERTURE_BLOCK"],
            "baseline_L2_aperture_block_rays": 1,
            "candidate_L2_aperture_block_rays": 2,
        },
        "metrics_changed": False,
        "thresholds_changed": False,
        "samples_changed": False,
        "interpretation_change": "Aggregate label narrowed from nominal-only automation to the preregistered cross-scenario tail/failure rule.",
        "amendment": "docs/s6/S6_AMENDMENT_03.md",
        "input_sha256": {
            "assembly_statistics_programmatic.json": _sha(raw_path),
            "paired_assembly_comparison.csv": _sha(C_DIR / "paired_assembly_comparison.csv"),
            "failure_breakdown.csv": _sha(C_DIR / "failure_breakdown.csv"),
            "assembly_bootstrap_replicates.csv": _sha(C_DIR / "assembly_bootstrap_replicates.csv"),
        },
        "adjudicated_at_utc": created_at,
    }
    adj_path = C_DIR / "S6_C_FINAL_ADJUDICATION.json"
    if adj_path.exists():
        raise FileExistsError(adj_path)

    final_stats = dict(raw)
    final_stats["S6_C_ASSEMBLY_CLAIM"] = "TRADEOFF_OR_NO_SUPPORTED_GAIN"
    final_stats["automatic_nominal_only_claim"] = raw["S6_C_ASSEMBLY_CLAIM"]
    final_stats["aggregate_scope"] = adjudication["scope"]
    final_stats["final_adjudication"] = "S6_C_FINAL_ADJUDICATION.json"
    final_stats["adjudication_amendment"] = "docs/s6/S6_AMENDMENT_03.md"
    for scenario in raw["scenarios"]:
        if final_stats["scenarios"][scenario] != raw["scenarios"][scenario]:
            raise AssertionError("scenario metrics changed during adjudication")
    (C_DIR / "assembly_statistics.json").write_text(
        json.dumps(final_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    final_status = dict(original_run_status)
    final_status.update({
        "S6_C_ASSEMBLY_CLAIM": "TRADEOFF_OR_NO_SUPPORTED_GAIN",
        "automatic_nominal_only_claim": raw["S6_C_ASSEMBLY_CLAIM"],
        "adjudication_amendment": "docs/s6/S6_AMENDMENT_03.md",
        "final_adjudication": "S6_C_FINAL_ADJUDICATION.json",
        "final_status_updated_at_utc": created_at,
    })
    (C_DIR / "run_status.json").write_text(
        json.dumps(final_status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def row(scenario: str, label: str) -> str:
        s = raw["scenarios"][scenario]
        ci = s["paired_mean_delta_capture_ci95"]
        p05ci = s["p05_paired_delta_bootstrap_ci95"]
        return (f"| {label} | {s['mean_capture_baseline125']*100:.2f}% | "
                f"{s['mean_capture_candidate135']*100:.2f}% | "
                f"{_pp(s['mean_delta_capture_candidate_minus_baseline'])} "
                f"[{_pp(ci[0])}, {_pp(ci[1])}] | "
                f"{s['p05_capture_baseline125']*100:.2f}% | "
                f"{s['p05_capture_candidate135']*100:.2f}% | "
                f"{_pp(s['p05_paired_delta_capture'])} "
                f"[{_pp(p05ci[0])}, {_pp(p05ci[1])}] |")

    report = f"""# S6 装配级鲁棒性结果与最终裁决

## 裁决

**跨本轮登记的完整公差情景：** `TRADEOFF_OR_NO_SUPPORTED_GAIN`  
**名义 1×公差主要 estimand：** 135 mm 相对 125 mm 的 assembly-paired 平均捕获差为正，bootstrap 区间排除 0。  
**证据级别：** `ASSEMBLY_SAMPLED`，仅适用于假设 P1 光学模型与模拟公差分布；实测状态 `NOT_AVAILABLE`。

自动统计程序最初按 nominal-only 主估计给出 `{raw['S6_C_ASSEMBLY_CLAIM']}`。冻结验收标准还要求在整个已声明容差敏感性范围内披露低尾和失败成本。`stress_2x` 的 paired P05 差为负且其 bootstrap 区间完全低于 0，另有少量额外 L2 截光，因此 Amendment 03 将**跨情景总标签**定为 `TRADEOFF_OR_NO_SUPPORTED_GAIN`。所有数值、阈值、样本、分母和 CI 保持原样。

## 各情景结果

捕获率以每个 assembly 的全部输入 source weight 为分母。平均差的 95% 区间与 P05 paired difference 区间均来自 2,000 次按 `assembly_id` 重采样的 cluster bootstrap；不是按单条 ray 重采样。

| 情景 | 125 mean | 135 mean | paired mean Δ pp [CI95] | 125 P05 | 135 P05 | paired P05 Δ pp [bootstrap CI95] |
|---|---:|---:|---:|---:|---:|---:|
{row('zero','0× (零公差)')}
{row('tight_0p5x','0.5× (收紧)')}
{row('nominal_1x','1× (名义主要情景)')}
{row('stress_2x','2× (加严压力情景)')}

四个情景各 200 个 assembly、每设计每 assembly 1,024 rays；每个 assembly 的基线/候选复用相同 source rays 和相同相对位姿扰动。总计 800 个唯一 assembly scenario、1,600 条 design-level assembly 记录、1,638,400 ray-design traces、8,000 个 bootstrap replicates。无 assembly 漏算、超时、重复 ID 或无效几何装配。

## 尾部、截光与代价

- Nominal 1×：125 mean `{nominal['mean_capture_baseline125']*100:.2f}%`，135 mean `{nominal['mean_capture_candidate135']*100:.2f}%`；paired mean Δ `{_pp(nominal['mean_delta_capture_candidate_minus_baseline'])} pp`，CI95 `[{_pp(nominal['paired_mean_delta_capture_ci95'][0])}, {_pp(nominal['paired_mean_delta_capture_ci95'][1])}] pp`。P05 paired Δ `{_pp(nominal['p05_paired_delta_capture'])} pp`，CI95 `[{_pp(nominal['p05_paired_delta_bootstrap_ci95'][0])}, {_pp(nominal['p05_paired_delta_bootstrap_ci95'][1])}] pp`。两设计的 assembly invalid rate 都为 0；本情景未见 aperture、TIR、trace 或 no-intersection loss。
- Stress 2×：paired mean Δ `{_pp(stress['mean_delta_capture_candidate_minus_baseline'])} pp`，CI95 `[{_pp(stress['paired_mean_delta_capture_ci95'][0])}, {_pp(stress['paired_mean_delta_capture_ci95'][1])}] pp`；但 paired P05 Δ `{_pp(stress['p05_paired_delta_capture'])} pp`，bootstrap CI95 `[{_pp(stress['p05_paired_delta_bootstrap_ci95'][0])}, {_pp(stress['p05_paired_delta_bootstrap_ci95'][1])}] pp`，均低于 0。候选出现 2 条 L2 aperture-blocked rays，基线 1 条；两者各有 88 条 L1 aperture-blocked rays。没有 invalid assembly、TIR 或 trace failure。
- Stress 情景两设计边际 P05 capture 分别为 `{stress['p05_capture_baseline125']*100:.2f}%` 和 `{stress['p05_capture_candidate135']*100:.2f}%`；这些边际分位不抵消 paired P05 的负尾，因为后者衡量同一装配扰动下的逐 assembly 差。
- 全平面（包含 1 mm 接收圆外、但到达该平面的光线）r90 的 assembly P95：nominal 125/135 分别 `{nominal['all_plane_r90_p95_mm_baseline125']:.3f} / {nominal['all_plane_r90_p95_mm_candidate135']:.3f} mm`；stress 125/135 分别 `{stress['all_plane_r90_p95_mm_baseline125']:.3f} / {stress['all_plane_r90_p95_mm_candidate135']:.3f} mm`。
- 135 mm 设计保留相对基线多移动 L2 10 mm 的名义机械调整；没有安装空间和行程数据，不能声称实物可装性。

## 参数和边界

名义误差 sigma 是每镜 x/y decenter 0.05 mm、x/y tilt 0.10°、z axial 0.30 mm，独立零均值 ±3 sigma 截断正态；0.5× 与 2× 情景沿用同一标准化 latent draw。它们不是供应商制造指标。几何参数为假设 N-BK7 等凸 singlet，清口径 12 mm、中心厚度 2 mm；vendor part `NOT_VERIFIED`。光纤输入 105 µm core、NA 0.22，近场均匀面积、远场均匀立体角是假设；绝对 source power `UNKNOWN`。

S5 的历史名义 ray bootstrap 结果原样保留，S6 assembly bootstrap 的重采样单位是 assembly。S6 不是实物制造良率、真实泵浦功率、Er:YAP 效率或热性能证明；G2=`QUALIFIED_ONLY`、G4=`QUALIFIED` 和 S5=`P1_SUPPORTED_TRADEOFF` 不被升级。

**结果数据：** `assembly_statistics.json`（应用 Amendment 03 后的总标签）、`assembly_statistics_programmatic.json`（原 nominal-only 自动裁决）、`p1_assembly_samples.csv`、`paired_assembly_comparison.csv`、`assembly_bootstrap_replicates.csv`、`failure_breakdown.csv`、`assembly_manifest.csv`。图表数值来源为 `assembly_robustness_plot_data.csv`。
"""
    report_path = C_DIR / "S6_ASSEMBLY_SCIENTIFIC_AUDIT_FINAL.md"
    report_path.write_text(report, encoding="utf-8")
    final_stats_hash = _sha(C_DIR / "assembly_statistics.json")
    final_status_hash = _sha(C_DIR / "run_status.json")
    result = {**adjudication, "final_assembly_statistics_sha256": final_stats_hash,
              "final_run_status_sha256": final_status_hash,
              "final_report_sha256": _sha(report_path)}
    print(json.dumps({"S6_C_ASSEMBLY_CLAIM": result["S6_C_ASSEMBLY_CLAIM"],
                      "nominal_primary_mean_delta_pp": _pp(nominal["mean_delta_capture_candidate_minus_baseline"]),
                      "stress_paired_p05_delta_pp": _pp(stress["p05_paired_delta_capture"]),
                      "stress_paired_p05_ci_pp": [_pp(x) for x in stress["p05_paired_delta_bootstrap_ci95"]],
                      "programmatic_nominal_claim": raw["S6_C_ASSEMBLY_CLAIM"],
                      "metrics_changed": False}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    result = apply()
    (C_DIR / "S6_C_FINAL_ADJUDICATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
