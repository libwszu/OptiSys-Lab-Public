# G3 开放问题登记册

开启于 2026-10-20。条目只关闭、不删除；关闭时指向证据文件。

## A. 继承自 G2 的科学问题

| ID | Sev | 问题 | G3 处理 | 状态 |
|---|---|---|---|---|
| PRE-G3-01 | P0 | 预注册 HC3 `kernel support >= 0.999`，as-run 配置 `0.950`；三候选 100/200/300 mm 实测 0.974–0.987 均低于 0.999 | 四档门限重判 + 两套口径并存 + 事后修订文档 | **证据齐备**：`G2_CONSTRAINTS_AMENDMENT.md`、`evidence/G2_HC3_SUMMARY.json`。判定 `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED`；0.999 结构不可达。**未解决，仅披露+修订** |
| PRE-G3-02 | P0 | 预注册禁止最终测试距离进入 OAT/precheck，实际 OAT 与 precheck 均含 105 / 285 mm | 调用链数据使用图 + 交叉集合测试 | **证据齐备**：`evidence/G2_DATA_USAGE_VERDICT.json`。泄漏=距离复用，非种子/装配复用。另发现 search 全程跑在 validation 距离上、最终面板仅 medium |
| PRE-G3-03 | P0 | `_final_stage` 条件分层循环复用 Strategy B 遗留的 `design`（robust 几何） | 先失败后修复回归测试 + 最小修复 + 重算 | **已修复并重算**：4/4 回归测试通过；`artifacts/g3/pre/stratified_repair/`。旧面板对 baseline/nominal 无信息量，相关表述撤回；主表 126 000 行未受污染（反解残差 0.0 vs 8034.7 mm） |
| PRE-G3-04 | P0 | G2 审计 ZIP 内 `sampled_results.csv` 仅 20 000 行且含 `# TRUNCATED` | 本机完整 126 000 行独立重算 + 增补包 | **已完成**：`FULLY_RECOMPUTED`，三候选全 `MATCH`（rtol 1e-9，最大相对差 0.0）。定性为**打包缺陷非数据丢失** |
| PRE-G3-05 | P1 | Strategy A（2000×3×7）与 B（200×1×7）不同口径直接相减；报告称 B 用 5 个校准帧 | 同口径表 + 校准帧数勘误 | **已完成**：裁定 `NOT_DIRECTLY_COMPARABLE`；校准帧 5→9 勘误；撤回「1.5–3 mm」增益句；配对 A/B `NOT_RUN`（预算） |
| PRE-G3-06 | P1 | 公式疑似多乘 1/Z；CLI report 无 schema 3.0 分支；审计包缺 pyproject/CI/README；PRE-10 呈现；模型选择未按预注册执行；repro smoke 被当完整复现 | 逐条勘误/修复/标注 | **6.1 完成**（`ERRATUM_REQUIRED`，多一个 1/Z，偏移仅真值 2–7 %；M2 优于 M1 16.46×，c=−1.45 mm 主平面偏移非焦距）· **6.2 完成**（三路 schema 分派 + G2 渲染分支，冻结 run 未动）· **6.4 记录**（G3 包补齐，G2 ZIP 不重打包）· **6.5 确认**（`select_model` 仅测试调用，`calibration_model_choice.json` 不存在） |
| G2-07 | P2 | robust 以更高失败率换更低 RMSE（1.90 mm / 25.30 % vs baseline 3.15 mm / 22.16 %） | UI 与报告强制同屏三指标，不排名"最优" | 承接（`G3-D-008`） |

## B. G3 自身问题

| ID | Sev | 问题 | 状态 |
|---|---|---|---|
| G3-01 | P2 | 演示视频未录制 | `NOT_DELIVERED`；脚本见 `DEMO_SCRIPT_5MIN.md`（含录制检查单），不得用占位链接冒充 |
| G3-02 | P3 | PDF 报告导出依赖未安装时标 `NOT_DELIVERED` | **已定**：本机无 reportlab/weasyprint，`ReportResult.pdf_status = NOT_DELIVERED` 且不生成空文件；见 `test_pdf_is_reported_as_not_delivered_not_faked` |
| G3-03 | P1 | 分层面板重算实测 1 897.8 s，超 600 s 预算 3.16× | **已记录**，见 `G3_COMPUTE_MEASURED.md` §2；冻结预算未改 |
| G3-04 | P2 | 本轮未实测并行加速（1/2/4 进程） | `NOT_TESTED`；沿用 G0/G1 单进程结论，不构成新证据 |
| G3-05 | P2 | 全量 pytest（含集成）尚未产生新 JUnit | **已完成**：`artifacts/g3/tests/g3_full_junit.xml`，结果见下 |
| G3-06 | P3 | `metrics_from_errors` 在 `n_attempted == 0` 时返回 `failure_rate = 1.0`，把「没有尝试」报成「100% 失败」 | **已修复**：改为 `None`，并补 `n_errors`。真实数据无零尝试单元（9 单元各 14 000 行），故不影响任何已发布数字；见 `test_metrics_reject_a_zero_denominator` |
| G3-07 | P2 | G2 审计 ZIP 的 `requirements` 只以 `requirements.lock.txt` 存在，而复现指南写 `-r requirements.txt`，读者需自行推断二者相同 | **已修复（仅 G3 包）**：G3 包双名并存；G2 ZIP 按不作废原则不重打包 |
| G3-08 | P3 | G2 审计 ZIP 若被要求复验，需另行索取完整 `sampled_results.csv` | **已披露**：G3 包 `manifest.json` → `excluded` 段给出全文件 SHA-256 与行数，可单独核验 |

## C. 明确不在 G3 范围

- G4 976 nm 多模泵浦：`NOT_IMPLEMENTED`。
- 消色差双胶合、Scheimpflug 倾斜、真实波前 PSF：未做。
- 任何实测数据：无。全部证据层级上限为 `SIMULATED` / `CROSS-CHECKED`。