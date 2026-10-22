# 01_EXECUTIVE_SUMMARY

## 判定

| 项 | 结果 |
|---|---|
| Gate | G0 |
| 执行状态 | **PASS** |
| 科学声明 | **SUPPORTED**（范围严格限定：理想共面几何的实现正确性与独立一致性） |
| 科学声明之外 | 传感器性能、镜头像质、标定、公差、优化、实测验证：**NOT_ASSESSED** |
| 测试 | 117 passed / 0 failed / 0 skipped |

## 已真正完成

| # | 内容 | 可核查证据 |
|---|---|---|
| 1 | 明确的坐标/单位/像素方向契约 | `src/optisys/units.py`、`geometry/coplanar.py` 模块 docstring、`tests/unit/test_units.py` |
| 2 | 严格 YAML schema（未知字段拒绝、单位显式、范围检查） | `src/optisys/config.py`、`configs/triangulation_v0.yaml`、`configs/schema/*.json`、15 个配置测试 |
| 3 | 前向/逆向/导数/灵敏度的标量与向量化实现 | `CoplanarGeometry.forward/inverse/forward_many/inverse_many/du_dZ/dZ_du` |
| 4 | 病态与越界状态码，绝不把 NaN 当成功 | `errors.Status`、19 个边界测试、`boundary_cases.csv` |
| 5 | 独立向量/矩阵对照链（3×3 线性解 + 3×4 投影 + Brent + 有限差分） | `geometry/reference.py`、12 个独立链测试、25 个导数测试 |
| 6 | 与 PDF 第 8 页印刷数值的对照 | `formula_comparison.csv`、9 个 reference 测试 |
| 7 | 不可覆盖的 run 目录与完整 provenance | `runtime/run.py`、`provenance.json`、`config_snapshot.yaml` |
| 8 | 实测基准驱动的计算策略 | `benchmark.json`、`compute_plan.json` |
| 9 | 自动 HTML 工程报告（G0 范围） | `run_evidence/` 对应的 `report.html`（不在本包内，见说明） |
| 10 | 最小独立复现脚本 | `repro/verify_g0.py`（打包时在解压副本中执行 PASS） |

> 说明：`report.html` 已复制为 `run_evidence/report.html`；其中的图以相对路径引用 `run_evidence/figures/`，解压后可直接打开（报告第 9 节的索引对应原始 run 目录布局）。报告内容由 `metrics.json` + `figures/` 生成，可用 `python -m optisys report --run runs/<run_id>` 重建。

## 明确未完成

| 需求 | 状态 | 原因 |
|---|---|---|
| R03 成像/PSF/光斑模型 | TODO | G1/G2 范围 |
| R04 曝光、噪声、饱和、裁切 | TODO | G1 范围 |
| R05 三种定位器 | TODO | G1 范围 |
| R06 标定与测试分离 | TODO | G1 范围 |
| R07 公差采样 | TODO | G2 范围 |
| R08 名义/鲁棒优化 | TODO | G2 范围 |
| R11 976 nm 案例 | TODO | G4 范围 |
| V1–V5、V7 | NOT_RUN | 依赖上述模块 |

R09（自动保存与报告）为 **IN_PROGRESS**：G0 的保存链完整，但完整工程报告属 G3。
R10（全新环境复现）为 **IN_PROGRESS**：本地 venv 可重建，远端 CI 未验证（`CI_NOT_VERIFIED`）。

## 负结果与失败记录

| 项 | 事实 | 处理 |
|---|---|---|
| 开发运行 1 | `numpy.linalg.solve` 在 NumPy 2.x 的 batched rhs 语义变化导致异常 | 修正为显式尾轴；保留失败 run 于 `runs/_dev_archive`（项目内） |
| 开发运行 2 | 3×4 投影矩阵与 3×3 内参混用导致 shape 错误 | 修正为 `K @ [R|t]` 齐次形式 |
| 开发运行 3 | 端点 `Z=300` 反演得 `300.00000000000006`，被严格范围判为 OUT_OF_RANGE | 增加 1 nm 数值保护带并新增测试；该 run 标记为 FAIL 并归档 |
| 并行基准 | 2/4/6 进程均慢于单进程（0.51–0.60×） | 如实记录，选择单进程；不掩盖负结果 |
| PDF 式 (3) | 符号与式 (2) 矛盾 | 独立数值验证后按有符号负值实现，幅值用于误差预算；见 SD-001 |

## 一句话总结

G0 交付的是一个**可独立复验的几何内核与证据链**：公式实现与独立数值方法在 1e-13 像素量级一致，错误输入被显式拒绝，运行可追溯；它**不是**传感器精度、镜头像质或产品性能的证明。
