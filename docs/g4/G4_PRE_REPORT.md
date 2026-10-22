# G4-PRE 接管核验

**时间**：2026-10-20（本机 Windows）  
**状态**：`PRE4_READY_WITH_DECLARED_LIMITS`  
**依据**：原始 PDF、G3 冻结运行、G3 审计 ZIP、本机记录和本轮 G4 任务书。未使用旧建议取代原 PDF 的 G4 范围。

## 核验矩阵

| ID | 核验 | 本轮证据 | 判定 |
|---|---|---|---|
| PRE4-01 | 旧 Gate 双线状态 | G3_FINAL_STATUS、G2_INHERITANCE_VERDICT、UI/report 定向回归；工程线 `PASS_WITH_DECLARED_DEVIATIONS`，科学线 `QUALIFIED_ONLY` | PASS |
| PRE4-02 | G3 ZIP 内容可复核 | SHA-256、212 成员/210 manifest 文件、内容哈希、3.14 独立解压复现；3.11 只在重压缩字节上不同 | CONTENT PASS；CROSS-ENV BYTE `NOT_GUARANTEED` |
| PRE4-03 | G3 pytest 时间冲突 | JUnit `time=141.655` 与 stdout `141.66s` 一致；另有 145.545s 记录无法由可用原始计时证据重建 | suite duration 已核；外部墙钟 `HISTORICAL_DURATION_NOT_ADJUDICATED` |
| PRE4-04 | G3 原始 756 行 CSV | 冻结运行文件 124,183 bytes / 756 数据行 / SHA-256 与历史记录一致 | PASS |
| PRE4-05 | 平台扩展点 | CLI `validate` 实际 exit 0；JobService、ReportService、五页 AppTest、现有光学接口的定向 pytest 73 passed / 0 failed / 0 skipped，JUnit/stdout/stderr 已保存 | PASS |
| PRE4-06 | Optiland 实际能力 | 本机固定 `optiland==0.6.3`；G2 单透镜真实追迹测试通过；G4 两个 N-BK7 假设 singlet 的真实 Optiland trace 通过。NA=0.05 时两个设计的 P0/P1 r80 差 0.2–0.3%、80%位置差 <0.01 mm；NA=0.22 时 P1 接收区通光约 67–68%，与 P0 的 100%不同 | P1 API PASS；物理验证限定低角度，完整 NA 必须标 `QUALIFIED` |
| PRE4-07 | 当前硬件与环境 | Python 3.14.3、Ryzen 5 4600G 6C/12T、31.41 GB RAM（采样时可用 13.66 GB）、GTX 1660 SUPER 6 GB；torch 未安装，CUDA 未测。18 次真实 Optiland workload profile：1/2/4/6 worker 分别 7.639/7.215/7.405/10.265 s，peak RSS 370/695/1346/1996 MB | CPU 基线 PASS；2 worker 仅 1.06×，未达 1.3×扩展门槛，正式使用 1 worker；GPU `NOT_TESTED` |
| PRE4-08 | 预注册、门限与预算冻结 | `G4_PRE_REGISTRATION.md`、`G4_ACCEPTANCE_CRITERIA.md`、`G4_COMPUTE_BUDGET.md` 和三个 config 已在 G4 结果计算前保存并哈希 | PASS；哈希见 `G4_FREEZE_HASHES.json` |

## 运行安全与范围

- G0/G1/G2/G3 冻结运行、历史配置、G3 文档与正式审计 ZIP 在 G4 基线快照中逐文件散列；此后只追加 G4 证据。
- 接管时 67 行既有 Git 改动已原样登记。`scripts/make_basetemp.py` 会清理其专用 G3 测试临时目录中的旧子目录；为避免触碰历史测试产物，本轮使用新建的 `artifacts/g4/pre/_basetemp_interfaces` 空目录。
- 第一轮 G4 Optiland 探针发现并修复局部 z 原点映射偏移；修正前数据保留在 `artifacts/g4/pre/optiland_g4_smoke.json`，不作物理结论。修正后交叉核对/性能证据在 `artifacts/g4/pre/optiland_g4_crosscheck_coordinatefix.json` 与 `compute_profile.json`。
- 项目没有提供经授权且带标定元数据的 976 nm 光斑数据。本轮外部实验状态为 `NOT_AVAILABLE`，不会启动或要求启动 976 nm 光源。
- 原 PDF §11 与本轮 G4 任务书允许仿真继续；G3 后续计划的额外前置建议按 `G4_BASELINE_DISCREPANCIES.md` 记录，不作为阻塞条件。

## PRE 产物

- 基线：`G4_BASELINE_HASHES.json`
- 矛盾裁决：`G4_BASELINE_DISCREPANCIES.md`
- 实际环境：`../../artifacts/g4/pre/environment.json`
- 接口与光学测试：`../../artifacts/g4/pre/commands.json`、JUnit、stdout/stderr
- 预注册/验收/预算：同目录 G4 文件与 config 快照
- 实测算力：`G4_COMPUTE_MEASURED.md`
