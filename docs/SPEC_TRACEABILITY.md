# SPEC_TRACEABILITY — PDF 需求 → 实现 → 证据

源文件：`OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf`
SHA-256：`25d0a727fbf047e8b399be8bd1ab670149b4a32377ff8edcef63e41ca4e6319d`（与总控提示词一致，2026-10-19 校验）
页码依据：PDF 第 6 页需求表、第 2 页 Gate 表、第 8–11 页模型与验证、第 13–17 页阶段任务。

状态口径：`PASS` 仅表示**本 Gate 范围内**的验收证据成立；`IN_PROGRESS` 表示子集已实现但完整需求未完成；`TODO` 表示未实现。不得把计划写成 PASS。

## 1. R01–R11

| ID | 需求（PDF 第 6 页） | G0 | G1 | 已实现内容 | 证据 | 缺口 |
|---|---|---|---|---|---|---|
| R01 | 统一坐标、长度单位、角度单位与像素方向 | PASS | PASS | 右手系、+Z 光轴、+X 横向；显式 mm/rad/pixel/s；schema 2.0 声明单位且无后缀歧义 | `units.py`、`config.py`、`config_g1.py`、单位测试 | 真实相机行列方向仍需标定 |
| R02 | 理想几何前向/逆向求解，覆盖全工作范围 | PASS | PASS | 解析式 + 独立向量/矩阵链；100–300 mm、θ=0/±3° | `geometry/*`、`evaluation/chain.py` | 仅共面二维 |
| R03 | 成像像差、PSF 或经声明的简化光斑模型 | NOT_STARTED | **IN_PROGRESS** | 圆对称 2D 高斯 + 像元面积积分（normal CDF）+ 捕获率；无镜头 PSF/像差 | `imaging/spot.py`、V1 证据 | 镜头 PSF/像差属 G2 |
| R04 | 曝光、传感器噪声、饱和与裁切 | NOT_STARTED | **PASS（L0）** | Poisson(信号+背景+暗电流) + 读出高斯 + 满阱/ADC/黑电平；V2 全部通过 | `imaging/sensor.py`、`metrics.json: v2_*` | 真实相机参数/PRNU/DSNU 未建模 |
| R05 | 三种定位算法及统一接口 | NOT_STARTED | **PASS** | 质心、1D 积分高斯（u 拟合 + v 行质心）、2D 稳健高斯；统一状态与质量标志 | `estimators/*`、V3-A | 未针对真实散斑/双峰场景调优 |
| R06 | 系统标定，分离拟合与独立测试 | NOT_STARTED | **IN_PROGRESS** | `a=fxB`、`b=cx−fx tanθ` 两参数线性标定；27/7/7 距离级划分；测试不参与拟合 | `calibration/system.py`、`split_manifest.json`、V3-B | 相机内参/畸变标定未做 |
| R07 | 可复现的灵敏度与公差采样 | NOT_STARTED | TODO | 仅灵敏度曲线；无公差采样 | `fig2_Z_sensitivity.csv` | G2 |
| R08 | 名义与鲁棒优化对照 | NOT_STARTED | TODO | `tolerance` 命令返回 `NOT_IMPLEMENTED`（exit 3） | CLI 测试 | G2 |
| R09 | 自动保存图表、数据、状态与模型限制 | PARTIAL | **PASS** | run 目录含配置/环境/基准/指标/样本/标定/划分/代表帧/7 图/报告/provenance/状态 | `runs/<G1_RUN_ID>/`、`report.html` | 完整工程报告（跨 Gate）属 G3 |
| R10 | 全新环境可复现标准案例 | PARTIAL | **IN_PROGRESS** | venv + 锁定依赖 + CLI + 194 测试 + `repro/verify_g1.py` + 解压复验 | `06_REPRODUCTION_GUIDE.md` | 远端 CI 未验证 |
| R11 | 976 nm 泵浦案例复用同一框架 | NOT_STARTED | TODO | 仅目录与假设清单 | `cases/pump976/README.md` | G4 |

## 2. Gate 追溯

| Gate | PDF 页码 | 验收要求 | 状态 | 证据 |
|---|---|---|---|---|
| G0 | 第 2、16–17 页 | 坐标/单位/公式/配置/自动测试固定；理想模型独立验证 | **PASS**（2026-10-19 冻结） | `runs/20261019_130948_G0_78fa364f`、G0 审计 ZIP |
| G1 | 第 2、9–10 页 | L0 成像、传感器噪声、三种定位器、标定/测试分离 | **PASS** | 本轮 G1 run、`04_VALIDATION_MATRIX.md`、G1 审计 ZIP |
| G2 | 第 2、10–11 页 | 公差采样、名义/鲁棒优化、独立 MC 复评 | NOT_STARTED | — |
| G3 | 第 2、12–13 页 | 可交互 MVP、自动报告、跨环境复现 | NOT_STARTED | — |
| G4 | 第 2、14 页 | 976 nm 案例复用、求职展示包 | NOT_STARTED | — |

## 3. G1 需求 → 测试 → 数值证据

| 需求 | 代表性测试 | 实测数值 |
|---|---|---|
| R03 | `test_spot.py::test_discrete_sum_matches_continuous_total` | 40,000.000000 e vs 40,000 e，相对偏差 0 |
| R03 | `test_spot.py::test_quadrature_agreement_is_independent_of_the_cdf_path` | 3.44e-14 相对差 |
| R03 | `test_estimators.py::test_noise_free_accuracy` | 2D 7.81e-5 px；1D 8.03e-4 px；质心 1.96e-4 px |
| R04 | `test_sensor.py::test_saturation_clips_at_full_well_and_adc` | 饱和比例 1.0；最大模拟电子 15,000；ADU 4095 |
| R04 | `test_sensor.py::test_adc_mapping_includes_black_level` | 300 e → 100 ADU + 黑电平 |
| R04 | V2（`gates/validation.py`） | 5 工况均值/方差均在 99% CI；暗电流斜率 5002.04 e/s |
| R05 | `test_estimators.py::test_bad_frame_*` | 无信号/饱和/边界/双峰均被标记 |
| R05 | 端到端 | 三估计器 RMSE 0.0444–0.0689 mm（全部有效帧） |
| R06 | `test_calibration.py` | a 相对误差 ≤8.3e-6；b 偏差 ≤0.001 px |
| R06 | `test_splits_metrics.py` | 27/7/7，交集为空；测试距离在标定区间内 |
| R09 | `test_g1_pipeline.py::test_limited…` | 13 类必需文件 + 7 图 + 6 代表帧；冻结保护 |
| R10 | `repro/verify_g1.py` | `REPRO_STATUS: PASS`（解压副本中实际执行） |

## 4. 与总控提示词的接口对照

| 提示词要求 | G1 实现 | 证据 |
|---|---|---|
| `Image.render(scene, seed) -> (image, truth, noise_metadata, status)` | `imaging/sensor.render_frame` | 返回 ADU、模拟电子、期望电子、饱和/ADC 比例、flags、seed |
| `Estimator.estimate(image, roi) -> (u,v,quality,status,time)` | 三种估计器统一 `EstimateResult` | `estimators/base.py` |
| `Calibration.fit(calibration_set) -> (model,range,residuals,provenance)` | `fit_distance_calibration` | `calibration/system.py` |
| 明确状态码，不把 NaN 当成功 | `Status` 扩展 + 质量标志 | `errors.py`、边界/坏帧测试 |
| 失败率以全部尝试帧为分母 | `evaluation/metrics.py` | `failure_breakdown.csv`、`v3_failure_denominator` |
| 配置与版本可复现 | `config_snapshot.yaml`、`provenance.json`、`requirements.lock.txt` | run 目录 / 审计包 |
| `NOT_IMPLEMENTED` 诚实返回 | `tolerance` → exit 3 | CLI 测试 |
