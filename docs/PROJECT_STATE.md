# PROJECT_STATE — OptiSys-Lab

最后更新：2026-10-19（UTC）
当前 Gate：**G1**
Gate 状态：**PASS**
冻结运行：`runs/20261019_145702_G1_54c9e3fb`
审计包：`_AUDIT/20261019_145702_G1_54c9e3fb/OptiSysLab_G1_20261019_145702_G1_54c9e3fb_GPT_AUDIT.zip`

## 1. Gate 总览

| Gate | 内容 | 状态 | 证据 |
|---|---|---|---|
| G0 | 工程基线 + 二维共面几何独立验证 | **PASS**（2026-10-19 冻结） | `runs/20261019_130948_G0_78fa364f`、G0 审计 ZIP |
| G1 | L0 成像、CMOS 噪声、三种定位器、系统标定与独立测试 | **PASS** | 本轮 G1 run、194 测试、G1 审计 ZIP |
| G2 | L1 镜头/PSF、公差 Monte Carlo、名义/鲁棒优化 | NOT_STARTED | — |
| G3 | 可交互 MVP、自动工程报告、全新环境复现 | NOT_STARTED | — |
| G4 | 976 nm 泵浦第二案例、求职展示包 | NOT_STARTED | — |

## 2. 本轮 G1-PRE 整改（G0 遗留）

| 问题 | 处理 | 测试 |
|---|---|---|
| CLI 对 Gate FAIL 仍返回 0 | `cmd_simulate` 仅在 `status == PASS` 时返回 0；PARTIAL/FAIL 返回 1 | `test_simulate_returns_nonzero_when_a_gate_check_fails` |
| Gate 聚合未纳入测试统计 | `qa.aggregate_gate_status`：数值门 + 边界 + 已摄入测试；缺失测试为 PARTIAL，失败/跳过/数量不足为 FAIL | `test_qa.py`（8 项） |
| `report/evaluate` 修改冻结 run | 冻结 run 的派生输出写入 `runs/_derived/<run_id>/<UTC>_<kind>/`；源文件哈希不变 | `test_frozen_run_is_not_modified_by_report_or_evaluate` |
| 反演不检查像面 | `inverse/inverse_many` 在深度合法但 u 出像面时返回 `OUT_OF_SENSOR` | `test_inverse_rejects_spot_outside_sensor_even_when_depth_is_in_range` |
| 配置单位歧义 | schema 1.0：字段后缀决定单位，冲突声明拒绝；schema 2.0：通用字段 + 声明单位 | `test_angle_unit_must_match_field_suffix`、`test_theta_follows_declared_rad_unit` |
| 报告字典/列表字面量 | `_fmt_value` 渲染布尔/字典/列表；GPU 用可读字符串 | `report` 输出检查 |
| 审计包缺 CI 文件 | G1 打包包含 `.github/workflows/ci.yml`；远端未运行，标 `REMOTE_CI_NOT_VERIFIED` | `REQUIRED` 列表 |

## 3. G1 本轮完成

- L0 圆对称高斯光斑，按像元面积积分（normal CDF 差），`total_electrons` 定义与 `peak_electrons` 明确区分；捕获率不做重归一化。
- CMOS 链：Poisson(信号+背景+暗电流) → 读出高斯 → 满阱裁切 → 增益/黑电平/ADC；保留模拟电子与 ADU 两套结果。
- 三种定位器：阈值质心、1D 积分高斯（u 拟合 + v 行质心）、2D 稳健高斯；统一 `EstimateResult`、质量标志与耗时。
- 系统标定：`u = a/Z + b`，`a=fxB`、`b=cx−fx tanθ`；27/7/7 距离级划分；测试集不参与拟合。
- 端到端 4,920 帧 × 3 估计器 = 14,760 条记录；7 张图 + 数据表 + 6 个代表帧 + HTML 报告。
- 计算策略：基准测得 4 进程 2.67×，实际采用 4 帧工作进程；结果与单进程逐位一致。

## 4. 关键结果（最终 run）

| 指标 | 实测 | 阈值 | 结论 |
|---|---|---|---|
| V1 能量守恒 | 0 | ≤1% | PASS |
| V1 独立 Gauss–Legendre | 3.44e-14 | ≤1e-6 | PASS |
| V1 亚像素（质心/1D/2D） | 1.96e-4 / 8.03e-4 / 7.81e-5 px | 0.05 / 0.02 / 0.01 | PASS |
| V2 噪声统计 | 5 工况 × 3 重复全部通过 | 99% CI | PASS |
| V2 暗电流斜率 | 5002.04 e/s（0.041%） | ≤5% | PASS |
| V3 `a` 恢复 | 4.29e-6–8.27e-6 相对 | ≤1e-2 | PASS |
| V3 测试集失败率 | 2,481 / 2,520 = 1.55% | 分母为全部尝试 | PASS |
| 端到端 RMSE（质心/1D/2D） | 0.0497 / 0.0689 / 0.0444 mm | 仅报告，不设工业阈值 | — |
| 最终测试集 RMSE（strong/medium/weak，2D） | 0.0080 / 0.0199 / 0.0874 mm | — | — |
| pytest | 194 passed / 0 failed / 0 skipped | ≥190 | PASS |
| 墙钟 | 320.9 s（4 workers） | ≤900 s | PASS |

精度指标仅对有效帧；失败率分母为全部尝试帧。所有结果均为 L0 仿真，不是实测或工业精度。

## 5. 环境

- Windows 11 build 10.0.26100，CPython 3.14.3（venv）
- Ryzen 5 4600G，6C/12T，31.41 GB RAM（运行时空闲 16.77 GB）
- GTX 1660 SUPER 6144 MB 存在，但 torch 未安装 → CUDA 不可用；GPU `NOT_TESTED`
- numpy 2.5.4 / scipy 1.18.1 / matplotlib 3.11.2 / pandas 3.0.6 / pytest 9.1.1 / optiland 0.6.3（未运行镜头案例）

## 6. 已知限制与风险

| 编号 | 问题 | 影响 | 状态 |
|---|---|---|---|
| SD-001 | PDF 式 (3) 导数符号 | 幅值正确、符号缺失；已按负号实现 | 已披露，不阻塞 |
| OI-002 | `min_baseline_mm=1.0` 无机械依据 | 有效性下限未经物理验证 | OPEN |
| OI-004 | Optiland 未运行镜头案例 | 不构成 L1 能力声明 | DEFERRED（G2） |
| OI-005 | 远端 CI 未执行 | R10/V6 只能 PARTIAL | OPEN |
| OI-009 | 无实测数据 | 最高证据等级 CROSS-CHECKED | OPEN |
| OI-013 | 2D 估计器在 weak 条件失败率 13.9% | 弱信号下稳健拟合更易被质量门拒绝；已如实报告 | OPEN（负结果） |
| OI-014 | 并行时单帧耗时高于单进程（内存带宽竞争） | 端到端仍 2.3× 加速；指标已注明测量条件 | CLOSED（已说明） |

完整列表见 `docs/OPEN_ISSUES.md`。

## 7. 下一轮入口

用户说“继续”时：

1. 读取本文件与 `docs/VALIDATION_MATRIX.md`，确认 G0/G1 证据仍与当前 HEAD 一致。
2. 进入 G2：Optiland L1 适配、PSF→图像、公差采样、名义/鲁棒优化与独立 MC。
3. 不修改已冻结的 G0/G1 run；新 Gate 单独冻结与打包。
