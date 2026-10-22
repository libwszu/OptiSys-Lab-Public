# G4 简历主张与边界

## 可用描述

> 为光电系统仿真平台实现 976 nm 多模光纤泵浦第二案例：自研面积/立体角一致的加权射线源、P0 双薄透镜光线传播与能量账本、Optiland 0.6.3 双 singlet 适配、目标平面密度/光斑指标、OAT 和 paired Monte Carlo 公差评估；以独立标量参考、ray-count 收敛、完整 holdout 样本和可复现审计包验证软件链路。所有结果明确标记为仿真。

## 可量化补充（必须带模型范围）

- P0 baseline：NA=0.22、4096 rays、目标区几何通光 1.000，条件 r90=0.19937 mm。
- P0 预定义 candidate：4096 rays、通光 1.000，条件 r90=0.14241 mm；L1/L2 口径从 Ø12/Ø12 增至 Ø16/Ø17 mm。
- P1 假设 N-BK7 singlet：相同接收区 target transmission 约 0.682（baseline）和 0.675（candidate），条件 r90 约 0.848/0.843 mm；这暴露 P0/P1 的 full-NA 模型差异，因此不应把 P0 结果说成真实器件改善。
- P0 100 组件 holdout paired r90 差 −0.03884 mm，95% CI [−0.04147,−0.03616]；只适用于已注册的 P0 光学/扰动假设。

## 不可写的主张

- “实测验证”“实际泵浦耦合效率”“W/mm²”“吸收功率/温升”“Er:YAP 激光效率”。
- “P1 对 NA=0.22 的真实光路已完整验证”或“工程 candidate 已被物理证明优于 baseline”。
- “产线良率/制造合格率”：扰动区间均为 ASSUMED，不来自制造统计。
- “完整 Er:YAP 激光器数字孪生”：本案例不含谐振腔、增益、吸收、热透镜或波动光学。

## 第三方归属

Optiland 0.6.3 提供 sequential surface/ray-trace 引擎；P0 source sampler、beamline vectorization、账本、评估、公差配对、UI/report/审计层由本项目实现。无真实镜片料号、无实验图片、无绝对功率输入。继承 G2 scientific status 为 `QUALIFIED_ONLY`。
