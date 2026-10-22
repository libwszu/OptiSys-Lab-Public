# G3 验收标准（冻结于 2026-10-20T05:55:40Z，结果产生前）

版本 `G3_ACCEPT_v1.0`。阈值先冻结，之后不得放松以求 PASS。

## A. 两条平行裁决线

### A1 `G3_ENGINEERING_EXECUTION_STATUS`

| 判定 | 条件 |
|---|---|
| `PASS` | GUI 有真实数值链；≥1 套可重复 demo；schema 1/2/3 数据与报告可用；完整测试/安装/审计复现实际通过；旧 run 保护通过 |
| `PARTIAL` | 部分 UI/报告/部署存在非科学性缺陷但可追踪；不得宣称完整 MVP |
| `FAIL` | 核心命令失败、数值或单位误呈现、旧数据被改写、测试伪造 |

### A2 `G3_SCIENCE_HANDOFF_STATUS`

| 判定 | 条件 |
|---|---|
| `CLEAR` | 全部关键 G2 遗留偏差已获独立证据或合规修订并充分披露，图表来源正确 |
| `QUALIFIED` | G2 as-run 数据可展示，但存在预注册偏离、数据重叠或证据不足；界面/报告/README 显式呈现 |
| `BLOCKED` | 存在无法隔离的错误图表/错误计算，或把失败样本当成功、把违反约束的候选称可行 |

聚合状态形如 `PASS_G3_ENGINEERING_WITH_G2_SCIENCE_QUALIFIED`。**禁止压缩为 `G3_ALL_PASS`。**

## B. 工程硬门（G3-01 … G3-12）

| ID | 质量门 | 验收方式 | 严重度 |
|---|---|---|---|
| G3-01 | G0/G1/G2 冻结运行与源 ZIP 不变 | 前后 `G3_BASELINE_HASHES.json` 对比，`tree_digest` 全等 | P0 |
| G3-02 | 6 项 PRE-G3 有真实处理记录 | 每项有 CSV/JSON 证据 + PASS/PARTIAL/QUALIFIED 判定 | P0 |
| G3-03 | GUI 从本机启动并显示真实数据 | 端到端 UI smoke + 真实截图 | P0 |
| G3-04 | 非法参数被拒、单位一致 | 自动测试 + 现场操作 | P0 |
| G3-05 | 低成本 demo 产生真实新 run | 命令、配置、日志、数据、图、状态齐全 | P0 |
| G3-06 | G2 图表指标/失败分母正确，受疑子面板禁用或修复 | 与结构化数据回算一致 | P0 |
| G3-07 | 报告含模型限制与 G2 科学状态 | 离线 HTML + 固定值测试 | P0 |
| G3-08 | 新报告不修改冻结 run | 运行前后哈希复测 | P0 |
| G3-09 | 后台任务可取消、失败不标 PASS | 进程控制 + 模拟故障 | P1 |
| G3-10 | Windows 安装/回归/UI/报表可复现 | 新 venv + 本地 CI 模拟，分列远端状态 | P0 |
| G3-11 | 复现耗时与资源有来源 | profiling/采样日志，禁止估算冒充 | P1 |
| G3-12 | 审计 ZIP 含科学关键原始数据且自身完整 | manifest/SHA/解压副本复算 | P0 |

P0 项不允许用 skip 变绿。

## C. 数值一致性判据（冻结）

| 检查 | 阈值 |
|---|---|
| G2 主表重算 vs `summary.json` 的 RMSE | 相对差 ≤ 1e-9 |
| 同项 P95 | 相对差 ≤ 1e-9 |
| 同项 `n_valid` / `n_attempted` | 整数完全相等 |
| 失败率 | 绝对差 ≤ 1e-12 |
| 每候选行数 | 恰为 42 000 |
| 全表行数 | 恰为 126 000 |
| `(candidate, assembly, distance, estimator)` 唯一主键 | 无重复 |
| 配对 `n_both_valid` | 与按 `assembly_id` 聚类掩码一致 |

## D. PRE-G3 各项的判定口径

| ID | PASS 条件 | 允许的最差状态 |
|---|---|---|
| PRE-G3-01 | 四档门限逐候选逐距离给出支持率与可行性；两套约束口径并存；结论写进 verdict | `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED` 也可接受，但必须记录 |
| PRE-G3-02 | 由源码调用链生成 `G2_DATA_USAGE_MAP.csv`；交叉集合自动测试；样本量对齐缺陷记录 | `QUALIFIED` + 明示适用范围限 medium |
| PRE-G3-03 | 有先失败后通过的回归测试；最小修复；重算子面板；主表不受影响有代码路径证明 | `PARTIAL` 若无法重算（需说明） |
| PRE-G3-04 | 完整 126 000 行独立重算，逐指标对照 | `INSUFFICIENT_EVIDENCE` 仅在缺原始文件时允许 |
| PRE-G3-05 | A/B 同口径表 + `NOT_DIRECTLY_COMPARABLE` 明示；校准帧数勘误 | `NOT_DIRECTLY_COMPARABLE` 是合格结论 |
| PRE-G3-06 | 公式勘误、CLI 修复 + 回归测试、缺件补入、模型选择如实标注 | 未执行项标 `NOT_EXECUTED_AS_REGISTERED` |

## E. 测试统计门

- 全量 `pytest`：`failed == 0`，`skipped == 0`，且 `passed >= 252`（历史基线）。
- 新 JUnit 与 exit code 必须本轮真实产生，不得抄 G2 记录。
- UI 测试不得靠 `skip` 通过。

## F. 审计包门

| 项 | 阈值 |
|---|---|
| ZIP 完整性 | `testzip()` 返回 `None` |
| 重名/路径穿越 | 0 |
| manifest 逐项 SHA-256 | 全部匹配 |
| 独立解压后 `repro/verify_g3.py` | exit 0 或显式 `PARTIAL` |
| ZIP 体积 | < 40 MB（不含被排除的可再生大文件） |
| ZIP SHA-256 记录位置 | ZIP 之外的 `AUDIT_ZIP_SHA256.txt` |

## G. 结果记录区（执行后填写，禁止改写上面的阈值）

见 `G3_FINAL_STATUS.json` 与 `docs/g3/G3_VALIDATION_MATRIX.md`。