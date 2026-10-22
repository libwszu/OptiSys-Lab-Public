# S6 继承科学范围

Stage 6 是原 G0–G4 项目结束后的有限扩展，检验 S5 所报告的名义光线捕获优势在声明的 P1 刚体误差假设下是否保留，并收口本地软件交付。它不新建强制 Gate，也不构成实际泵浦效率、Er:YAP 数字孪生或制造良率证明。

| 阶段 | 冻结结论 | S6 处理 |
|---|---|---|
| G2 | `QUALIFIED_ONLY` | 原预注册科学边界保持不变 |
| G4 | `QUALIFIED` | 全系统 `NO_SUPPORTED_IMPROVEMENT` 的历史结论保持不变 |
| S5 | `PASS / EXPLAINED_WITH_SCOPE / P1_SUPPORTED_TRADEOFF` | 仅为名义假设 P1、单束 4,096 对光线的 125→135 mm 对照；不自动外推至装配误差 |
| S6-A | 尚待双独立几何参考核验 | 未通过前 S6-C 必须为 `NOT_RUN_DUE_TO_REFERENCE_GATE` |
| S6 实物测量 | `NOT_AVAILABLE` | 本轮没有授权或证据支持的实物测量 |

S5 的原始名义捕获率 `0.660888671875` 与 `0.87060546875`、差值 `+0.209716796875` 及 paired ray bootstrap CI `[0.197265625, 0.221923828125]` 是被冻结的历史数字。本轮不会覆盖它们，也不会称为装配级置信区间。

科学证据级别分别使用 `ASSUMED_MODEL`、`MODEL_CROSS_CHECKED`、`ASSEMBLY_SAMPLED`、`EXPERIMENTALLY_MEASURED`。前三者按各自实际证据标注；`EXPERIMENTALLY_MEASURED` 默认 `NOT_AVAILABLE`。
