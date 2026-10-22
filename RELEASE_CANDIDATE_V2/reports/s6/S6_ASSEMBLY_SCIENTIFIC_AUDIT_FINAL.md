# S6 装配级鲁棒性结果与最终裁决

## 裁决

**跨本轮登记的完整公差情景：** `TRADEOFF_OR_NO_SUPPORTED_GAIN`  
**名义 1×公差主要 estimand：** 135 mm 相对 125 mm 的 assembly-paired 平均捕获差为正，bootstrap 区间排除 0。  
**证据级别：** `ASSEMBLY_SAMPLED`，仅适用于假设 P1 光学模型与模拟公差分布；实测状态 `NOT_AVAILABLE`。

自动统计程序最初按 nominal-only 主估计给出 `SUPPORTED_WITHIN_ASSUMED_P1_AND_TOLERANCES`。冻结验收标准还要求在整个已声明容差敏感性范围内披露低尾和失败成本。`stress_2x` 的 paired P05 差为负且其 bootstrap 区间完全低于 0，另有少量额外 L2 截光，因此 Amendment 03 将**跨情景总标签**定为 `TRADEOFF_OR_NO_SUPPORTED_GAIN`。所有数值、阈值、样本、分母和 CI 保持原样。

## 各情景结果

捕获率以每个 assembly 的全部输入 source weight 为分母。平均差的 95% 区间与 P05 paired difference 区间均来自 2,000 次按 `assembly_id` 重采样的 cluster bootstrap；不是按单条 ray 重采样。

| 情景 | 125 mean | 135 mean | paired mean Δ pp [CI95] | 125 P05 | 135 P05 | paired P05 Δ pp [bootstrap CI95] |
|---|---:|---:|---:|---:|---:|---:|
| 0× (零公差) | 66.53% | 85.92% | +19.39 [+19.22, +19.56] | 63.87% | 84.47% | +17.38 [+16.89, +17.87] |
| 0.5× (收紧) | 66.43% | 85.57% | +19.14 [+18.97, +19.33] | 58.79% | 77.92% | +17.09 [+16.60, +17.57] |
| 1× (名义主要情景) | 65.69% | 83.74% | +18.05 [+17.74, +18.34] | 51.64% | 69.90% | +13.67 [+12.60, +14.93] |
| 2× (加严压力情景) | 59.69% | 72.43% | +12.75 [+11.65, +13.85] | 27.51% | 32.91% | -5.69 [-9.28, -0.90] |

四个情景各 200 个 assembly、每设计每 assembly 1,024 rays；每个 assembly 的基线/候选复用相同 source rays 和相同相对位姿扰动。总计 800 个唯一 assembly scenario、1,600 条 design-level assembly 记录、1,638,400 ray-design traces、8,000 个 bootstrap replicates。无 assembly 漏算、超时、重复 ID 或无效几何装配。

## 尾部、截光与代价

- Nominal 1×：125 mean `65.69%`，135 mean `83.74%`；paired mean Δ `+18.05 pp`，CI95 `[+17.74, +18.34] pp`。P05 paired Δ `+13.67 pp`，CI95 `[+12.60, +14.93] pp`。两设计的 assembly invalid rate 都为 0；本情景未见 aperture、TIR、trace 或 no-intersection loss。
- Stress 2×：paired mean Δ `+12.75 pp`，CI95 `[+11.65, +13.85] pp`；但 paired P05 Δ `-5.69 pp`，bootstrap CI95 `[-9.28, -0.90] pp`，均低于 0。候选出现 2 条 L2 aperture-blocked rays，基线 1 条；两者各有 88 条 L1 aperture-blocked rays。没有 invalid assembly、TIR 或 trace failure。
- Stress 情景两设计边际 P05 capture 分别为 `27.51%` 和 `32.91%`；这些边际分位不抵消 paired P05 的负尾，因为后者衡量同一装配扰动下的逐 assembly 差。
- 全平面（包含 1 mm 接收圆外、但到达该平面的光线）r90 的 assembly P95：nominal 125/135 分别 `2.089 / 1.590 mm`；stress 125/135 分别 `2.698 / 2.229 mm`。
- 135 mm 设计保留相对基线多移动 L2 10 mm 的名义机械调整；没有安装空间和行程数据，不能声称实物可装性。

## 参数和边界

名义误差 sigma 是每镜 x/y decenter 0.05 mm、x/y tilt 0.10°、z axial 0.30 mm，独立零均值 ±3 sigma 截断正态；0.5× 与 2× 情景沿用同一标准化 latent draw。它们不是供应商制造指标。几何参数为假设 N-BK7 等凸 singlet，清口径 12 mm、中心厚度 2 mm；vendor part `NOT_VERIFIED`。光纤输入 105 µm core、NA 0.22，近场均匀面积、远场均匀立体角是假设；绝对 source power `UNKNOWN`。

S5 的历史名义 ray bootstrap 结果原样保留，S6 assembly bootstrap 的重采样单位是 assembly。S6 不是实物制造良率、真实泵浦功率、Er:YAP 效率或热性能证明；G2=`QUALIFIED_ONLY`、G4=`QUALIFIED` 和 S5=`P1_SUPPORTED_TRADEOFF` 不被升级。

**结果数据：** `assembly_statistics.json`（应用 Amendment 03 后的总标签）、`assembly_statistics_programmatic.json`（原 nominal-only 自动裁决）、`p1_assembly_samples.csv`、`paired_assembly_comparison.csv`、`assembly_bootstrap_replicates.csv`、`failure_breakdown.csv`、`assembly_manifest.csv`。图表数值来源为 `assembly_robustness_plot_data.csv`。
