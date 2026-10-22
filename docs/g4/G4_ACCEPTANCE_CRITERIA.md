# G4 验收标准（结果前冻结）

**版本**：1.0  **冻结日期**：2026-10-20  **状态**：FROZEN_BEFORE_G4_RESULTS  
结果失败后不得放宽本文件阈值并沿用原版本。若需更改，另建版本并记录对原结论的影响。

| ID | 验收规则 | 判据 |
|---|---|---|
| P4-V0a | 输入/方向/权重 | 非有限参数、NA>n_out、负半径、N≤0、负权重均明确拒绝；方向最大范数误差 ≤1e-12；`sin θmax·n_out` 与 NA 绝对误差 ≤1e-12；等权和与 1 的误差 ≤1e-12。 |
| P4-V0b | 源采样统计 | 固定样本上 `r²/R²` 与 `(1-cosθ)/(1-cosθmax)` 的 KS D ≤ `1.63/sqrt(N)`；替代远场必须有独立分布 ID 和 seed，不能冒充测量。 |
| P4-V1a | P0 解析/独立参考 | 自由传播、薄透镜极限、矢量平面求交与独立标量/ABCD 参考的位置误差 ≤1e-10 mm、方向误差 ≤1e-12。 |
| P4-V1b | 物理边界 | aperture 减小不能增加其后存活权重；源权重按一个且仅一个结果类别分摊；残差 ≤1e-10。零样本/全失败时比率和半径为 null，并标 `NOT_EVALUABLE`。 |
| P4-V2 | Optiland P1 | 实际环境版本必须为 0.6.3，且真实 RealRays 通过至少两个 singlet 元件。低 NA=0.05、开口径交叉样本：P0/P1 中位位置差 ≤0.05 mm；r80 差 ≤10%。阈值只适用于该低角度/薄透镜对照，不外推到 NA=0.22。若实现不满足，P1 标 `PARTIAL/NOT_VERIFIED`，P0 结论不升级。 |
| P4-V3 | 权重与目标统计 | source = target + outside target + aperture blocked + trace/invalid categories；归一化残差 ≤1e-10；geometric transmission 在 [0,1]；密度积分与对应权重在 1e-8 相对误差内一致。 |
| P4-V4 | 射线数稳定性 | 2k/8k/32k 各 3 seeds 全部交付。报告跨 seed 95% 区间；若 8k→32k 的中位 r80 相对变化 >5%，标为未收敛/需提高采样，不以“通过”掩盖。 |
| P4-V5a | OAT/公差完整性 | OAT 每参数保留所有水平；precheck 和独立 holdout 各 100 装配/设计，所有行和失败状态完整；paired 设计扰动严格同 seed/同样本 ID；失败率分母含全部尝试。 |
| P4-V5b | 候选收益 | 不设正收益硬门。仅当 holdout 的 paired assembly bootstrap 95% CI 排除 0，且传输/口径权衡同时可见，才写有支持的改善；否则 `NO_SUPPORTED_IMPROVEMENT`。 |
| P4-V6a | 服务复用 | 原五页 AppTest 无异常；第六页执行真实 G4 代码并显示 SIMULATED/model level/G2 QUALIFIED_ONLY；JobService 真实 timeout 负向控制必须中断子进程并写 TIMEOUT。 |
| P4-V6b | 软件回归 | 全量 pytest 0 failures / 0 errors / 0 skipped；原有 G3 425 测试不得删、skip、xfail 或降门限；记录真实 JUnit、stdout、stderr、exit code 与时间。 |
| P4-V6c | CLI/服务 | G3 主案例和 G4 泵浦案例各有真实低成本 CLI；AppTest 和真实 Streamlit server smoke 分开报告，HTTP 健康检查不等同页面 WebSocket E2E。 |
| P4-V7 | 实验 | 无授权原始实验资料时 `NOT_RUN / NOT_AVAILABLE`，不得输出 MEASURED 或 VALIDATED_BY_EXPERIMENT。 |
| P4-V8 | 审计包 | `testzip()`、路径/重复名、全成员哈希、独立解压复算、低成本 P0 重跑、临时副本篡改拒绝均通过；同环境 byte repro 只在同一明确 Python/zlib 下判断；跨环境 DEFLATE 为 `NOT_GUARANTEED`。 |
| COMPUTE | 资源门 | 每个 G4 子任务由父进程 watchdog 限时；计算阶段总上限 300 s，单任务上限 180 s。超时必须写 `TIMEOUT/PARTIAL` 并保留已完成分块。 |

## 分析合同

- 核心值全是几何 ray density proxy，不是相干 PSF、绝对辐照度或吸收功率。
- 通光率分母固定为光源全部入射权重；被阻挡/未求交光线不能重归一化。
- r80/r90 仅针对进入接收有效圆内的传输权重，并以加权质心为中心。
- 所有工程状态、物理模型验证、公差状态、实测状态、审计状态独立报告；科学收益可以为负或不支持。
