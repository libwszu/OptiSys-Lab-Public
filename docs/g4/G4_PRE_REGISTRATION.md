# G4-PRE 注册：976 nm 多模光纤泵浦几何光路

**版本**：1.0  **状态**：结果产生前冻结  **登记日期**：2026-10-20  
**主张范围**：工程几何仿真；不代表实测、商品规格或 Er:YAP 激光效率。

## 问题与假设

评估 976 nm 光纤泵浦经准直镜 L1、聚焦镜 L2 后到接收平面的几何射线足迹、几何通光、截光与对准敏感度。基线采用 PDF 起始值：105 µm 芯径、NA 0.22、空气出射、L1 EFL 25 mm、L2 EFL 100 mm。除波长/概念参数外，没有厂家手册、料号、绝对功率或装配统计数据；所有镜片几何、材料模型、孔径、间距、扰动均为 `ASSUMED`。

## 坐标和设计

- 全局右手坐标，光纤端面在 z=0，光沿 +z；核心单位 mm、rad，波长 nm。
- P0 采用位于主平面的理想薄透镜。L1 principal plane z=25 mm，L2 principal plane z=125 mm，接收面 z=225 mm；两镜主平面间距 100 mm。
- Baseline：L1 25 mm / Ø12 mm，L2 100 mm / Ø12 mm。
- `engineering_candidate`：L1 35 mm / Ø16 mm，L2 100 mm / Ø17 mm；L1 与光纤间距置于 35 mm，L2 与目标面保持 100 mm。候选在看结果前由倍率 `f2/f1` 推导，预期斑更小但镜头口径与体积更大；不预设收益成立，不称作优化胜出。
- P1（若 API 执行成功）：Optiland 0.6.3 顺序追迹、N-BK7 色散材料、2.0 mm 厚等双凸 singlet；曲率由 EFL 和 976 nm 折射率计算，材料/厚度/口径仍是明确假设。P1 足迹只包含几何追迹和口径，不包含镀膜/Fresnel/散射/衍射/相干性。
- 有效接收圆半径暂设 1.0 mm，是模型接收区，不是已核实晶体尺寸。

## 光源注册

- 均匀面积近场：`r=R sqrt(U)`、`φ=2πV`，R=0.0525 mm。
- 基准角分布：空气中 NA=0.22 定义为 `sin(θmax)=NA/n_out`；`cosθ=1-U(1-cosθmax)`、φ 均匀，即均匀立体角，而非均匀 θ 或均匀方向余弦。
- 敏感性替代分布：同一最大 NA 下，对 `q=sinθ/sinθmax` 采用 `F(q)=q³` 的边缘偏重角分布。该分布仅为假设，不是实测多模光纤远场。
- 基准源位置和方向先按独立变量采样；每条射线唯一 ID，等权 `w=1/N`，`Σw=1`。功率绝对值为 UNKNOWN。
- 固定随机流：源收敛 seeds `[976051, 976052, 976053]`；OAT seed `202610200`；tolerance precheck seed `202610201`；独立 holdout seed `202610202`。开发样本不得复用为 holdout。

## 设计和验证集

- 无随机优化器；候选已由几何推导预先指定，避免在 holdout 上挑选候选。
- OAT：基线逐项扫描焦距/位置/口径/偏心/倾角/接收面 z，并记录失败与有效域。
- 联合公差 precheck：100 装配；独立 paired holdout：100 装配；两设计使用同一组逐装配无量纲扰动（common random numbers），不同阶段使用不同 seed。
- 公差为 ASSUMED uniform bounded：L1/L2 轴向 ±0.10 mm、横向偏心 ±0.10 mm、倾角 ±0.10°、有效直径 ±0.10 mm、焦距相对误差 ±1%，纤芯半径 ±5%。这些不是制造良率。
- 每装配 2,048 条光线；源收敛另用 2k/8k/32k × 3 seeds。正式运行保留每一装配与失败状态，不只保留汇总。
- 实测数据：无授权原始数据，`V7=NOT_RUN`、`G4_EMPIRICAL_VALIDATION_STATUS=NOT_AVAILABLE`。

## 统计和报告

- 主要几何指标：输入权重、到达各面权重、每个口径阻挡权重、目标区外权重、几何通光率（分母是全源权重）、已到达目标权重条件下的质心/RMS 半径/r80/r90；r80/r90 参考已传输权重质心。
- 密度图同时保留以总输入权重归一化的 `weight_fraction/mm²` 和以目标内传输权重条件化的无量纲密度；不得将其写作 W/mm²。
- 主对照不强制正收益。结果不足以支持改善时写 `NO_SUPPORTED_IMPROVEMENT`，保持全部失败分母。
- 抽样误差按 seed/装配层次报告；不同 rays 数不是物理精度升级。

## 预定裁决线

`G4_ENGINEERING_EXECUTION_STATUS`、`G4_OPTICAL_MODEL_VERIFICATION`、`G4_TOLERANCE_EVALUATION_STATUS`、`G4_EMPIRICAL_VALIDATION_STATUS`、`G4_PORTFOLIO_DELIVERY_STATUS`、`G4_AUDIT_STATUS` 与 `G4_SCIENTIFIC_CLAIM` 分别给出，不生成 `G4_ALL_PASS`。继承 `INHERITED_G2_SCIENCE_STATUS=QUALIFIED_ONLY`。
