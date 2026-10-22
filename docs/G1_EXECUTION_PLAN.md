# G1_EXECUTION_PLAN

本轮唯一目标：在保留 G0 几何内核的前提下，修复 G0 遗留工程问题，完成 **G1：L0 光斑成像 → CMOS 简化传感器 → 三种亚像素定位 → 系统距离标定 → 独立测试与报告**，冻结证据并生成审计 ZIP。**不进入 G2。**

## 0. 起点核验（2026-10-19）

| 项 | 期望 | 实测 | 结论 |
|---|---|---|---|
| PDF SHA-256 | `25d0a727…319d` | 一致 | PASS |
| G0 审计 ZIP SHA-256 | `3967d064…4c44` | 一致 | PASS |
| G0 run | `20261019_130948_G0_78fa364f` | 存在，status PASS | PASS |
| G0 源码树摘要 | `054b0919…0960` | 当前 `src/**/*.py` 一致 | PASS |
| G0 记录 commit | `28b713a4…3f82` | 为当前 HEAD 的祖先（HEAD `b4a85e2`，仅文档提交） | 记录差异，不回滚 |

G0 ZIP 作为基线快照，不作为当前源码来源；本轮所有修复进入新提交与新 G1 证据。

## 1. 子阶段

| 子阶段 | 内容 | 退出条件 |
|---|---|---|
| G1-PRE | 修复 0.3 的 5 个 P1 + 2 个 P2 | 新增回归测试通过；G0 117 项适用测试不回退 |
| G1-A | 二维高斯 + 像元面积积分 + 裁切/捕获率 | V1-A/V1-B 独立验证通过 |
| G1-B | 电子数、泊松、读出、暗电流、增益、ADC、饱和 | V2-A/V2-B 统计检验通过 |
| G1-C | 三种定位器 + 质量标志 + 坏帧 | V3-A 通过（同帧比较、无真值泄漏） |
| G1-D | 系统标定 a,b；27/7/7 固定划分；端到端测试 | V3-B 通过（无泄漏、参数冻结） |
| G1-E | 正式实验、指标、图表、报告、冻结 | G1 总验收 |
| G1-AUDIT | ZIP、manifest、独立解压复验 | 包完整性 + 解压 repro 实际执行 |

## 2. 模块与接口

```text
src/optisys/
  imaging/spot.py       SpotSpec, integrated_weights(), render_spot(), capture_fraction()
  imaging/sensor.py     SensorSpec, render_frame() -> RenderResult
  imaging/roi.py        detect_roi(image, config, background) -> RoiResult
  estimators/base.py    EstimateResult, estimator registry
  estimators/centroid.py, gaussian_1d.py, gaussian_2d.py
  calibration/system.py fit_distance_calibration(), DistanceCalibration
  evaluation/splits.py  make_distance_splits() -> SplitManifest
  evaluation/metrics.py summarise_groups(), bootstrap_ci()
  gates/g1.py           run_g1() 端到端流水线
  reports/figures_g1.py, reports/report_g1.py
  qa.py                 aggregate_gate_status()（核心数值门 + 必需测试）
```

统一接口：

```text
SpotSpec.total_electrons, sigma_px, center_px
integrated_weights(shape, center, sigma) -> (weights, capture_fraction)
SensorSpec.render(spot, seed) -> RenderResult(image_adu, electrons, truth, flags, ...)
Estimator.estimate(image_adu, roi, cfg) -> EstimateResult(u_hat, v_hat, quality, status, runtime_ms)
fit_distance_calibration(samples, split) -> DistanceCalibration(a_px_mm, b_px, covariance, ...)
```

## 3. 科学边界

- 仅 L0：圆对称单峰高斯、理想像元面积积分、独立泊松/高斯噪声、线性增益与硬饱和。
- 不使用真实镜头 PSF、散斑、PRNU/DSNU、滚动快门、真实相机料号、实测数据。
- `v` 由二维光斑给出（中心恒为 `cy`），但 G0 的共面几何仍只约束 `u`；二维能力仅用于成像与定位，不构成双目/面形测量。
- 标定只辨识组合参数 `a=fxB`、`b=cx-fx tanθ`；**不声称四个几何参数可独立辨识**。

## 4. 正式数据集（运行前冻结）

- 距离：41 个，100–300 mm，步长 5 mm。
- 条件：3 档（strong / medium / weak），总电子数 200k / 40k / 8k。
- 重复：每距离每条件 40 帧。
- 总量：41 × 40 × 3 = **4,920 帧**；三种定位器使用**同一帧集**。
- 划分：按距离整体划分 27 / 7 / 7（calib / validation / test），测试距离全在标定覆盖区间内部，不外推。
- 代表帧：约 12 帧 `.npz`（有效、低 SNR、饱和、边缘裁切、ROI 失败、双峰干扰）。

未采用 PDF 建议的 12,300 帧（41×100×3）：在正式运行前根据 Pilot 基准估算，其生成+拟合+存储成本约为本文规模的 2.5 倍，超出单轮 900 s 计算预算且显著增加包体；**在运行前**将 4,920 定为 G1 正式规模，未在查看结果后缩减。该选择记录在 `G1_ACCEPTANCE_CRITERIA.md` 与 `05_COMPUTE_AND_PERFORMANCE.md`。

## 5. 算力策略

1. Pilot：3 距离 × 3 重复 × 3 条件 = 27 帧，测分项耗时。
2. 单帧全画幅 1280×1024，逐帧生成、在线聚合，不驻留全部图像。
3. 先单进程；若拟合为瓶颈且独立任务 ≥1.3× 收益，再测 2/4/6 进程（含 IPC）。
4. GPU 不启用；`GPU_NOT_TESTED`。
5. 长任务按批次写 checkpoint 索引（sample_id、seed、状态、耗时）。

## 6. 停止与阻断

- 能量守恒 > 1%、噪声统计拒绝、失败帧标 OK、标定/测试 ID 交叉、CLI 对 FAIL 返回 0、证据哈希不一致 → 立即停止扩展，修复或判 FAIL/PARTIAL。
- 任一门失败不得通过调整阈值绕过；阈值只能在运行前以版本化文档修改。

## 7. 交付

- `runs/<G1_RUN_ID>/` 全套证据（含 `samples.csv`、`calibration.json`、`split_manifest.json`、`representative_frames/`、6–8 图）。
- 更新 `docs/PROJECT_STATE.md`、`SPEC_TRACEABILITY.md`、`VALIDATION_MATRIX.md`、`OPEN_ISSUES.md`。
- `_AUDIT/<G1_RUN_ID>/OptiSysLab_G1_<RUN_ID>_GPT_AUDIT.zip` + SHA-256 + 打包日志。
- 终端按任务书第 10 节格式汇报，停在 G1。
