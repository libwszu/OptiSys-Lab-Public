# G4 基线差异与裁决记录

记录接管时发现的差异。此文件补充历史，不回写 G0–G3 冻结材料。

## SPEC-DISCREPANCY-01 — G3 后续计划与 G4 原始范围

- 原 PDF：第 14 页 §11 将 976 nm 泵浦光路定义为轻量工程案例；第 15 页风险策略要求缺实测时定位为数字样机并使用独立数值参考。
- G3 ZIP 的 `08_NEXT_GATE_PLAN.md` 建议把实测、HC3 修订、消色差/Scheimpflug 交叉验证和并行测试设为 G4 前置条件。
- 本轮用户授权的 G4 任务书 §0.2 明确裁决：这些是 G3 的更严格建议，不是原 PDF 的强制 Gate；缺少实测不阻止仿真交付，G2 旧问题也不要求在 G4 重跑。
- 处理：遵循原 PDF 与本轮 G4 任务书的优先顺序。无实测状态保持 `NOT_MEASURED / NOT_AVAILABLE`；G2 科学状态继续 `QUALIFIED_ONLY`。不改旧 G3 计划文件。

## HISTORICAL-DURATION-01 — G3 pytest 时间口径

- `_AUDIT/20261020_071457_G3_ea57a83b/04_VALIDATION_MATRIX.md` 记 141.655 s。
- `artifacts/g3/tests/g3_full_junit.xml` 的原始 suite `time` 是 141.655 s；`g3_full_stdout.txt` 显示 141.66 s；两项一致，均为 425 passed / 0 failed / 0 errors / 0 skipped。
- `docs/g3/G3_FINAL_STATUS.json` 与 `docs/g3/G3_COMPUTE_MEASURED.md` 记 145.545/145.55 s，且状态 JSON 说明它来自 JUnit；这与实际 JUnit 属性不符。
- 裁决：pytest suite duration 采用原始 JUnit 的 141.655 s。145.545 s 是否是包含进程启动/包装器的外部墙钟时间，缺少原始计时日志或成对时间戳，标记 `HISTORICAL_DURATION_NOT_ADJUDICATED`。保留全部 G3 原文件及说法，不以 G4 结果覆盖历史。

## AUDIT-ZIP-01 — G3 ZIP 内容完整与重压缩字节差异

- 本机 G3 ZIP 实际 SHA-256：`0e2cf640313950e381828f10d9da8efe9112af56b7d2598c24c7ec5ca545242a`，与接管提示一致；大小 739,379 bytes。
- ZIP 共 212 个成员；manifest 管理 210 个普通文件，`manifest.json` 与 `SHA256SUMS.txt` 是两个自引用例外。原始 ZIP 的 `testzip()` 无损坏，210 项清单哈希逐一匹配。
- Python 3.14.3 / zlib-ng 1.3.1：运行 G3 自带完整 verifier 成功，独立解压后的 `repro/verify_g3.py` 为 PASS。
- Python 3.11.9：运行 verifier 时唯一失败项为从成员重建 ZIP 后的字节 SHA 不同；ZIP 内容哈希与路径检查没有报告问题。判定为压缩器/运行环境差异，不能称作内容损坏，也不宣称跨环境字节级可复现。

## G3-SAMPLES-01 — 完整演示 CSV

- `runs/20261020_071457_G3_ea57a83b/independent_validation/sampled_results.csv` 存在，124,183 bytes，756 条数据记录。
- 实际 SHA-256：`5904f9f784dfd9310026546025f6f6e9b4fb944c35099240d085208c3655192e`，与历史记录一致。原始 G3 ZIP 未包含该 CSV；G4 ZIP 将随包提供本轮 G4 的完整正式样本，不改 G3 ZIP。

## WORKTREE-01 — 接管时已有改动

- 接管前 `git rev-parse HEAD` 为 `PRIVATE_SOURCE_REVISION`，`git status --porcelain=v1` 有 67 行改动/未跟踪项，快照保存在 `G4_BASELINE_HASHES.json`。
- 这些文件视为既有用户工作；没有执行 `reset`、`clean` 或批量清理。G4 新证据写入新文件/新目录。
