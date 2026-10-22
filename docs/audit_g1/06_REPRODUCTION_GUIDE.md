# 06_REPRODUCTION_GUIDE — G1

## 0. 前置条件

- Python ≥ 3.11（本轮：CPython 3.14.3，Windows 11）
- 依赖：`pip install -e .[dev]`，或离线 `pip install -r requirements.lock.txt && pip install -e . --no-deps`
- 不需要 GPU、不需要 Optiland（G1 只用 NumPy/SciPy/Matplotlib）
- 完整 4,920 帧实验约需 5–6 分钟（本机 4 进程实测；单进程约 12.6 分钟）

## 1. 最小独立复现（约 2 秒）

```powershell
python repro/verify_g1.py
```

预期输出（本机实测）：

```text
config                 : ...\configs\triangulation_g1_l0.yaml
energy relative error  : 0.000e+00
quadrature max rel err : 4.060e-16
noise mean z-score     : 0.049 (|z| <= 4)
noise variance ratio   : 0.9943 (0.9-1.1)
2-D estimator error    : 7.813e-05 px (<= 0.01)
calibration a rel err  : 2.442e-15
calibration b abs err  : 5.684e-13 px
split 27/7/7           : True
REPRO_STATUS           : PASS
```

它检查：像元面积积分守恒、独立 Gauss–Legendre 对照、单像元噪声均值/方差、二维定位器亚像素误差、两参数标定恢复、27/7/7 划分。

## 2. 完整测试

```powershell
python -m pytest -q
```

预期：`194 passed`（0 failed / 0 skipped），约 1 分 40 秒。
其中 6 个 G1 集成测试会各跑 30–60 帧的限量流水线（`--limit-frames`），**不会**产生 PASS 的 G1 证据。

## 3. 完整 G1 实验

```powershell
python -m optisys validate --config configs/triangulation_g1_l0.yaml
python -m optisys simulate --config configs/triangulation_g1_l0.yaml
```

预期：

- 新建 `runs/<UTC>_G1_<config-hash>/`
- 4,920 帧 × 3 定位器 = 14,760 条估计记录
- `run_status.json` 的 `status` 为 `PASS` 或 `PARTIAL`（取决于 V1–V3 与测试证据）
- 关键文件：`samples.csv`、`calibration.json`、`split_manifest.json`、`figures/`、`representative_frames/`、`report.html`

若只做冒烟：

```powershell
python -m optisys simulate --config configs/triangulation_g1_l0.yaml --limit-frames 60
```

限量运行会被强制标为 `PARTIAL`，CLI 返回非零退出码，**不能**当作 G1 通过。

## 4. 派生复评（不修改冻结 run）

```powershell
python -m optisys evaluate --run runs/<G1_RUN_ID>
python -m optisys report   --run runs/<G1_RUN_ID>
```

输出写入 `runs/_derived/<run_id>/<UTC>_report/` 与 `..._evaluate/`，源 run 的文件哈希保持不变（有测试断言）。

## 5. 审计包自检

```powershell
python scripts/verify_audit_package.py <解压后的包根目录>
```

预期 `VERIFY_STATUS: PASS`、`problems: 0`。

## 6. 证据对照

| 文件 | 检查点 |
|---|---|
| `run_evidence/metrics.json` | `gate_checks` 全为 true；`dataset.frames_attempted = 4920` |
| `run_evidence/calibration.json` | 三个估计器的 `a_px_mm`、`b_px`、`status`、`n_frames_used`；`identifiability` 文本 |
| `run_evidence/split_manifest.json` | 27/7/7，三集合互斥 |
| `run_evidence/samples/samples.csv` | 每行状态、质量标志、误差、耗时；失败帧保留 |
| `run_evidence/representative_frames/index.json` | 6 个代表帧的用途与 ROI |
| `run_evidence/tests_summary.json` / `pytest_junit.xml` | 193 passed 的机器可读记录 |

## 7. 已知的可复现性边界

| 项 | 是否逐位一致 | 说明 |
|---|---|---|
| 图像/噪声（同 seed） | 是（同平台、同 NumPy） | `default_rng` + blake2b 稳定 seed |
| 几何/标定数值 | 是（同依赖） | 双精度线性代数 |
| 图 PNG / HTML | 否 | 字体、版本、时间戳 |
| 耗时 | 否 | CPU 负载与频率；只比较量级 |
| 完整实验的总帧数 | 是 | 由配置与划分决定 |

## 8. 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| `CONFIG_INVALID: schema_version` | 用 1.0 配置跑 G1 | 使用 `configs/triangulation_g1_l0.yaml` |
| `UNKNOWN key` | 手工改了字段名 | 恢复配置；schema 2.0 不允许未知字段 |
| `simulate` 返回 1 | Gate 非 PASS，或使用了 `--limit-frames` | 查看 `run_status.json` 的 `gate_aggregation` |
| `report` 写到 `_derived` | 冻结 run 保护 | 正常行为，源证据不可改 |
| Calibration `NOT_ESTIMABLE` | 限量运行或标定帧不足 3 个距离 | 跑完整实验；不要用手工改阈值绕过 |
