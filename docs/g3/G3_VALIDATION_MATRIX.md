# G3 验证矩阵

结果产生于 **2026-10-20**，对应 run `20261020_071457_G3_ea57a83b`。
阈值口径见 `G3_ACCEPTANCE_CRITERIA.md`（2026-10-20T05:55:40Z 冻结，结果前）。

## 一、工程硬门 G3-01 … G3-12

| ID | 门 | 判定 | 证据 |
|---|---|---|---|
| G3-01 | G0/G1/G2 冻结运行与源 ZIP 不变 | ✅ **PASS** | 三份 run 的整树摘要（路径 + 逐文件 SHA-256）与 `G3_BASELINE_HASHES.json` 逐位相等；源 PDF、G2 审计 ZIP、G2 配置哈希均 `expected == actual`。测试：`test_frozen_run_tree_matches_the_baseline_snapshot`（3 项）、`test_frozen_run_status_file_hash_is_unchanged`（3 项） |
| G3-02 | 6 项 PRE-G3 有真实处理记录 | ✅ **PASS** | 每项均有 JSON/CSV 证据与判定；见 `G2_INHERITANCE_VERDICT.json`。测试：`test_g3_tsci.py`（25 项） |
| G3-03 | GUI 从本机启动并显示真实数据 | ✅ **PASS** | 五页 AppTest 零异常；页 B 单帧真实追迹 5.95 s。测试：`test_pages_render.py`（17 项） |
| G3-04 | 非法参数被拒、单位一致 | ✅ **PASS** | 配置校验拒绝非法 schema；页 B 参数有界；单位声明在每份报告与每条 provenance 中。测试：`test_config_g2.py`、`test_units.py` |
| G3-05 | 低成本 demo 产生真实新 run | ✅ **PASS** | `runs/20261020_071457_G3_ea57a83b`：756 行（12 装配 × 7 距离 × 3 候选 × 3 估计器）、77.2 s、4 图、`status PASS`、D1–D5 全通过 |
| G3-06 | G2 图表指标/失败分母正确，受疑子面板已禁用或修复 | ✅ **PASS** | 126 000 行重算与 `summary.json` 全指标 `MATCH`；分层面板已修复重算，旧值与新值并列。测试：`test_report_rmse_matches_a_recomputation_from_the_csv`、`test_report_failure_rate_uses_the_attempt_denominator` |
| G3-07 | 报告含模型限制与 G2 科学状态 | ✅ **PASS** | 每份报告 4/4 科学令牌；含「无实测」「G4 未运行」「A/B 不可直接比较」。测试：`test_g3_treport.py`（15 项） |
| G3-08 | 新报告不修改冻结 run | ✅ **PASS** | 构建前后整树摘要相等；默认输出落在 `runs/_derived/`。测试：`test_building_a_report_does_not_modify_the_frozen_run`、`test_default_output_directory_is_under_derived` |
| G3-09 | 后台任务可取消、失败不标 PASS | ✅ **PASS** | 退出码 1/2→`FAIL`、3→`DEPENDENCY_UNAVAILABLE`、超时→`TIMEOUT`、取消→`CANCELLED`、重启→`ORPHANED`。测试：`test_g3_tjobs.py`（13 项） |
| G3-10 | Windows 安装/回归/UI/报表可复现 | ⚠️ **PASS（本地）／远端 `NOT_RUN`** | 全量 pytest 425 通过（本地）；远端 CI **未运行**，不得声称通过 |
| G3-11 | 复现耗时与资源有来源 | ✅ **PASS** | `G3_COMPUTE_MEASURED.md` 全部为实测；分层面板超支 3.16× 如实记录；规划常数与实测值在 UI 与文档中分列 |
| G3-12 | 审计 ZIP 含科学关键原始数据且自身完整 | ✅ **PASS** | 成员数/字节数以构建输出为准（包内不记录自身计数，理由见 `G3_FINAL_STATUS.json` 的 `member_counts_note`）；`testzip()` PASS；manifest 逐项 SHA-256 全匹配；除 manifest 与 SHA256SUMS 外无未登记成员；解压副本 repro `PASS`；篡改一字节会被拒 |

**P0 项（G3-01…G3-08, G3-10, G3-12）无一使用 skip 变绿。** G3-10 的远端部分单独标注为 `NOT_RUN`。

## 二、数值一致性判据（§C）

| 检查 | 阈值 | 实测 | 判定 |
|---|---|---|---|
| G2 主表重算 vs `summary.json` RMSE | 相对差 ≤ 1e-9 | 0.0 | ✅ |
| 同项 P95 | 相对差 ≤ 1e-9 | 0.0 | ✅ |
| `n_valid` / `n_attempted` | 整数相等 | 相等 | ✅ |
| 失败率 | 绝对差 ≤ 1e-12 | 0.0 | ✅ |
| 每候选行数 | 恰 42 000 | 42 000 | ✅ |
| 全表行数 | 恰 126 000 | 126 000 | ✅ |
| 主键唯一 | 无重复 | 无重复（CSV 直接核验） | ✅ |
| 配对 `n_both_valid` | 与聚类掩码一致 | 一致 | ✅ |

## 三、PRE-G3 各项判定（§D）

| ID | 判定 | 允许的最差状态 | 是否在允许内 |
|---|---|---|---|
| PRE-G3-01 | `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED` | 该状态本身可接受，但须记录 | ✅ 在范围内 |
| PRE-G3-02 | `QUALIFIED` + 适用范围限 medium | 同 | ✅ 在范围内 |
| PRE-G3-03 | 先失败后通过的回归测试 + 最小修复 + 重算 | `PARTIAL` 若无法重算 | ✅ 优于下限（已重算） |
| PRE-G3-04 | 完整 126 000 行独立重算 | `INSUFFICIENT_EVIDENCE` 仅缺原始文件时 | ✅ 优于下限 |
| PRE-G3-05 | `NOT_DIRECTLY_COMPARABLE` 明示 + 校准帧勘误 | 该结论本身合格 | ✅ 在范围内 |
| PRE-G3-06 | 逐条勘误/修复/标注 | 未执行项标 `NOT_EXECUTED_AS_REGISTERED` | ✅ 6.1/6.2/6.4/6.5 有结论 |

## 四、测试矩阵（T-*）

| 矩阵 | 文件 | 项数 | 通过 |
|---|---|---|---|
| T-BASE | `tests/integration/test_g3_tbase.py` | 12 | ✅ |
| T-SCI | `tests/integration/test_g3_tsci.py` | 25 | ✅ |
| T-DATA | `tests/integration/test_g3_tdata.py` | 20 | ✅ |
| T-UI | `tests/ui/test_pages_render.py` | 17 | ✅ |
| T-REPORT | `tests/integration/test_g3_treport.py` | 15 | ✅ |
| T-JOBS | `tests/integration/test_g3_tjobs.py` | 13 | ✅ |
| T-REPRO | `tests/integration/test_g3_trepro.py` | 16 | ✅ |
| T-SECURITY | `tests/integration/test_g3_tsecurity.py` | 24 | ✅ |

全量：**425 tests / 0 failed / 0 errors / 0 skipped**，exit 0，145.545 s。

## 五、审计包门（§F）

| 项 | 阈值 | 实测 | 判定 |
|---|---|---|---|
| ZIP 完整性 | `testzip()` → `None` | `None` | ✅ |
| 重名 / 路径穿越 | 0 | 0（`is_safe_member` 逐成员校验） | ✅ |
| manifest 逐项 SHA-256 | 全部匹配 | 逐项全匹配（计数随重建变化，以构建输出为准） | ✅ |
| 未被 manifest 覆盖的成员 | 0 | 0 | ✅ |
| 独立解压后 `repro/verify_g3.py` | exit 0 | exit 0 + `REPRO_STATUS: PASS` | ✅ |
| ZIP 体积 | < 40 MB | 约 0.7 MB | ✅ |
| ZIP SHA-256 位置 | ZIP 之外 | `AUDIT_ZIP_SHA256.txt` | ✅ |
| 字节级可复现 | 连续构建哈希一致 | 连续 3 次构建 sha256 相同（`147978f0...`） | ✅ |
| 可复现性被断言 | 验包脚本检查 | `reproducibility_findings()` 重新打包比对 | ✅ |
| 无 CSV 以真实文件名截断 | 0 | 0 | ✅ |

## 六、明确未验证项

| 项 | 状态 | 不得写成 |
|---|---|---|
| 远端 CI | `NOT_RUN` | "CI 通过" |
| 并行加速（G3 负载） | `NOT_TESTED` | "已并行优化" |
| GPU / CUDA | `NOT_TESTED` | "支持 GPU" |
| 物理实测 | `NOT_MEASURED` | "实测验证" |
| G4（976 nm） | `NOT_IMPLEMENTED` | "支持 976 nm" |
| 演示视频 | `NOT_DELIVERED` | "有演示视频" |