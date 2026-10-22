# OptiSys-Lab 项目展示：三角测量主案例 + 976 nm 泵浦光路

## 一句话

用 Python 构建可复现的光电系统仿真平台：同一套配置、运行目录、公差计算、报告、Streamlit 和审计流程支持 650 nm 激光三角测量主案例与 976 nm 多模光纤泵浦第二案例。

## 第二案例解决的问题

给定光纤芯径、NA、L1/L2焦距与孔径，估计到接收面的几何射线足迹、截光、目标平面权重密度、光斑半径和装配扰动敏感度。它是光路工程仿真，不是完整 Er:YAP 激光器数字孪生。

## 实际实现

- 多模光纤源：均匀面积圆盘采样 `r=R√U`；基准远场按均匀立体角采样，使用 `n_out sin(theta_max)=NA`；边缘偏重远场作为显式敏感性模型。
- P0：矢量薄透镜射线传播、口径求交、目标圆形裁切、源权重账本、质心、RMS、r80/r90、二维密度。
- 独立参考：逐射线标量 ABCD/slope 传播；向量与标量位置/方向逐 ray 对照。
- P1：Optiland 0.6.3 两个等凸 N-BK7 假设镜片、每镜两面实际球面/径向光阑，基于真实 `RealRays` 追迹。低 NA 交叉对照通过；NA=0.22 与 P0 理想模型差异明显，并公开展示。
- 复用平台：G4 schema config、run/provenance、JobService硬超时、ReportService、六页 Streamlit 与独立审计 ZIP。
- 统计：OAT 30 点、100 装配 precheck、100 装配独立 paired holdout；所有 400 行样本/失败状态完整保留。

## 代表性正式结果

Run：`20261020_133555_G4_ec3e2813_0e48`。

| 模型 | 设计 | 几何通光至目标区 | r80 [mm] | r90 [mm] |
|---|---|---:|---:|---:|
| P0 ideal thin lens, NA 0.22 | baseline | 1.000 | 0.18693 | 0.19937 |
| P0 ideal thin lens, NA 0.22 | candidate | 1.000 | 0.13352 | 0.14241 |
| P1 assumed N-BK7 singlets, NA 0.22 | baseline | 0.68188 | 0.69445 | 0.84773 |
| P1 assumed N-BK7 singlets, NA 0.22 | candidate | 0.67505 | 0.69750 | 0.84341 |

P0 的 paired holdout `r90` 差为 −0.03884 mm，95% CI [−0.04147, −0.03616]；几何通光差为 +0.00267，95% CI [+0.00158,+0.00389]。这些是 P0 假设模型下的仿真；P1 high-NA 结果不支持把 P0 光斑收益当成真实器件改善。综合工程结论为 `NO_SUPPORTED_IMPROVEMENT`，候选的更小理想焦斑需以真实镜片模型与实验再验证。

## 证据等级

`SIMULATED / CROSS_CHECKED_WITH_SCOPE`。NA=0.05 时 P0/P1 r80 差为 0.193%和0.265%；NA=0.22 时模型差异明显。没有实验照片、功率标定或料号，所有真实器件性能仍 UNKNOWN。

## 目录

- 源码：`src/optisys/sources/multimode_fiber.py`、`src/optisys/optics/pump_beamline.py`、`src/optisys/optics/pump_optiland.py`
- 配置：`configs/pump976_g4_l0.yaml`、`pump976_g4_l1.yaml`、`pump976_g4_tolerance.yaml`
- 正式表格/图/报告：`runs/20261020_133555_G4_ec3e2813_0e48/`
- 可复核 ZIP：见 `_AUDIT/20261020_133555_G4_ec3e2813_0e48/`
