# G4 科学审计

## 光源假设

芯径 `0.105 mm`，半径 `0.0525 mm`，NA `0.22`，出射介质空气 `n_out=1.0`。最大角 `asin(0.22)=12.7099°`。近场均匀面积以 `r=R√U` 采样；远场基准均匀立体角，`cos(theta)=1-U(1-cos(theta_max))`。边缘偏重替代模型对 `q=sin(theta)/sin(theta_max)` 用 `F(q)=q³`。位置和方向独立是 ASSUMED，不代表真实模态统计。射线等权、`Σw=1`，源绝对功率 UNKNOWN。

## 光路与模型层级

- P0：主平面上的理想薄透镜，统一 +z，baseline `L1=25mm@z25/Ø12mm`、`L2=100mm@z125/Ø12mm`、target `z225mm/r1mm`。
- 候选：`L1=35mm@z35/Ø16mm`、`L2=100mm@z135/Ø17mm`、target `z235mm/r1mm`；在结果前按倍率关系固定，口径增大约束同屏报告。
- P1：Optiland 0.6.3，假设 2 mm 厚 N-BK7 equiconvex singlets，Sellmeier `n(976nm)=1.5078427`，无料号。仅几何追迹/径向孔径；没有 Fresnel、涂层、散射、衍射、相干性、真实装调坐标断点。

## 独立对照与差异

P0 vectorized 和独立 per-ray 标量 slope/ABCD 路径在 8,192 条 NA=0.22 rays 上的报告差为 0.0 mm/0；接受阈值分别 `1e-10 mm`、`1e-12`。P1 低角度交叉样本（NA=0.05）差异很小并通过冻结门限。NA=0.22 时 P1 的假设镜片模型对 1 mm target 只有约 68% weighted transmission；P0 理想薄透镜为 100%。因此全 NA 物理验证是 `QUALIFIED`，P0 不能当实际高 NA 泵浦聚焦预测。

## 传输与光斑定义

`geometric_transmission_fraction = Σw_inside_target / Σw_source`。透镜截光、target 区外、未求交、trace failure 都留在源分母；不将幸存射线重归一化。target plane 的二维数组分别保存 source-denominated `weight_fraction/mm²` 与 transmitted-conditioned density；绝对功率未知，绝不称为 W/mm²。

rms 半径、r80、r90 的样本限于实际进入假设 target circle 的传输权重；r80/r90 从 weighted centroid 起算。P0 nominal baseline r90=0.19937 mm、候选 0.14241 mm；P1 高 NA baseline r90=0.84773 mm、候选 0.84341 mm。

## 公差与结论

各扰动范围在配置中标作 ASSUMED，不代表制造良率。precheck 与 holdout 独立 seeds、同一装配变量配对两设计，完整 CSV 保存 400 行。P0 holdout 条件 r90 差的 assembly bootstrap 95% CI 排除 0；但 P1 high-NA 的光斑与 target capture 同 P0 不一致，且没有实验数据。整体结论保守为 `NO_SUPPORTED_IMPROVEMENT`，只保留 P0 假设下的数值比较。
