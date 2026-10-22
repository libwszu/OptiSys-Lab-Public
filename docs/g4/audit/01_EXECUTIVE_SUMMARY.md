# G4 执行摘要

## 状态

| 裁决 | 状态 |
|---|---|
| 工程执行 | `PASS_WITH_DECLARED_DEVIATIONS` |
| 光学模型验证 | `QUALIFIED` |
| 公差评估 | `PASS`（P0、ASSUMED 扰动、100+100 assemblies/design） |
| 外部实验 | `NOT_AVAILABLE` / `NOT_RUN` |
| 作品包 | `PARTIAL`（实际演示视频未交付） |
| 审计包 | `PASS`（内容、解压复算、篡改拒绝、同/跨环境字节重建） |
| 科学主张 | `QUALIFIED` / `SIMULATED` |
| G2 继承状态 | `QUALIFIED_ONLY` |

## 正式运行

`run/` 保存 4,096-ray baseline/candidate P0 与 P1 追迹，2k/8k/32k×3 seeds 收敛、30 点 OAT、100 装配 precheck 与100装配独立 holdout。完整 tolerance CSV 有 400 行。正式 run 内部 10.1323 s、CLI 外层 13.798 s、peak RSS 405.08 MB、1 worker。

## 代表结果

- P0 baseline：几何通光 `1.000`，r80 `0.18693 mm`，r90 `0.19937 mm`。
- P0 预先固定的 engineering candidate：几何通光 `1.000`，r80 `0.13352 mm`，r90 `0.14241 mm`；镜片口径更大。
- P1 assumed singlet、NA=0.22：baseline 到 1 mm 假设接收区约 `0.68188`；candidate 约 `0.67505`。约三成源权重落在接收区外；这与 P0 差异显著。
- P1 NA=0.05：baseline/candidate 的 r80 与 P0 相对差分别 0.193%/0.265%，80%位置差分位数 0.00668/0.00428 mm，满足冻结的低角度判据。
- P0 paired holdout r90 差 `−0.03884 mm`，95% CI `[−0.04147, −0.03616]`；几何通光差 `+0.00267`，95% CI `[+0.00158,+0.00389]`。整体设计结论仍为 `NO_SUPPORTED_IMPROVEMENT`，因为 P1 full-NA 模型差异未解决且没有实测。

以上都是模拟结果，不是实际光路、镜片规格或实验效率的承诺。
