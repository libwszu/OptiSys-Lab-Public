# G3 执行计划（冻结于改动代码之前）

- 版本：`G3_PLAN_v1.0`
- 冻结时间（UTC）：2026-10-20T05:55:40Z
- Git HEAD：`PRIVATE_SOURCE_REVISION`（工作树 dirty）
- 依据：`1md/OptiSysLab_G3_Development_Scientific_Repair_and_Audit_Prompt.md`

**本文件在结果产生之前写定。** 后续如需修改验收阈值，必须在
`DECISION_LOG.md` 追加条目并说明理由；不允许"跑完再改标准"。

## 1. 优先次序

科学/统计诚实性 > 冻结证据不可变性 > 可复现与自动验收 > 软件交互 > 美观。

## 2. 阶段划分与产出

| 阶段 | 内容 | 产出目录 | 前置 |
|---|---|---|---|
| S0 调查与冻结 | 基线哈希、计划、阈值 | `docs/g3/` | — |
| S1 G3-PRE | 六项科学/工程纠偏 | `docs/g3/`, `artifacts/g3/pre/` | S0 |
| S2 缺陷修复 | stale design、report schema 3.0 | `src/`, `tests/` | S1 定性完成后 |
| S3 数据层 | 版本化解析器、数据协议、ReportService、JobService、Audit | `src/optisys/{presentation,jobs,reports,audit}/` | S2 |
| S4 UI MVP | Streamlit 五页 | `app/` | S3 |
| S5 demo | 真实小工况 run + 图 + 报告 | `runs/<new>/`, `_derived/` | S4 |
| S6 回归 | 全量 pytest、UI smoke、报告 smoke | `artifacts/g3/tests/` | S5 |
| S7 冻结与审计 | 新 run 冻结、ZIP、独立解压复验 | `_AUDIT/<new>/` | S6 |

## 3. 技术选型

**UI：Streamlit 1.66.0（本机已实测安装成功）。**

理由：

1. 已有架构是"CLI + run 目录 + JSON/CSV 证据"，Streamlit 可以直接以只读方式读取，
   不需要为 GUI 重建数据模型；
2. 纯 Python，无 C++/Qt 构建链，Windows 12 核机器上 `streamlit run` 即启动；
3. 内置数据表、图表、下载按钮，五页 MVP 的交互面足够；
4. 唯一被否的方案 PySide6：需要额外的事件循环/线程模型改造，且打包与
   自动化 UI 测试成本更高，与"5 分钟内可运行"目标冲突。

**不引入第二套 UI。** 任何 PySide6 代码都不写。

## 4. 模块落位（相对现有仓库的增量）

```
src/optisys/presentation/     # 只读数据协议、RunRepository、显示规则、单位
src/optisys/jobs/             # 子进程任务执行、状态机、取消、profile 估算
src/optisys/reports/          # 在现有 report*.py 旁增加统一 ReportService
src/optisys/audit/            # 哈希、manifest、ZIP 构建与校验
app/main.py                   # 薄控制层
app/pages/                    # 5 页
app/components/               # 状态徽标、单位提示、表格
configs/g3_demo.yaml          # 短时演示配置（schema 3.0，缩减面板）
scripts/verify_g3_release.py
scripts/build_g3_audit_package.py
scripts/verify_g3_audit_package.py
tests/ui/ tests/integration/ tests/reference/
```

## 5. 接口隔离

UI 只能通过四个服务取数或提交任务，**不得**在按钮回调里直接调用 G2 优化循环：

- `ConfigService`：加载 + 校验配置，返回规范化摘要与 schema 版本；
- `RunRepository`：枚举 run、按 schema 解析、返回带 `run_id / schema_version /
  model_level / units / evidence_level / status / source_sha256` 的视图对象；
- `JobService`：以受控子进程执行白名单命令，持久化任务记录；
- `ReportService`：从 CSV/JSON 重建 HTML 报告，冻结 run 一律写 `_derived/`。

## 6. 停止与降级规则（照抄任务书 §10）

- 单位或反演错、哈希未知偏移、冻结结果被覆盖、分母错、数据错配未隔离
  → `G3_ENGINEERING` 不得 PASS。
- HC3 / 预注册集合问题无法修复但能隔离披露 → `G3_SCIENCE_HANDOFF=QUALIFIED`。
- 缺 Optiland 或 Windows UI 依赖 → `DEPENDENCY_UNAVAILABLE`，工程 Gate `PARTIAL`。
- 新环境复现或 ZIP 独立解压失败 → 不交付完整 PASS 包。

## 7. 明确不做

- 不做 G4 的 976 nm 多模泵浦仿真；
- 不新增消色差双胶合、Scheimpflug、真实波前 PSF；
- 不为了漂亮数值重跑 G2 优化；
- 不使用 GPU（`GPU_NOT_TESTED`）；
- 不伪造任何截图、进度条或"永远成功"的状态灯。

## 8. 执行结果（事后追加，不改上面的阈值）

| 阶段 | 状态 | 产出 |
|---|---|---|
| S0 调查与冻结 | ✅ 完成 | `G3_BASELINE_HASHES.json`、`G3_EXECUTION_PLAN.md`、`G3_ACCEPTANCE_CRITERIA.md`、`G3_COMPUTE_BUDGET.md` |
| S1 G3-PRE | ✅ 完成 | `G2_INHERITANCE_VERDICT.json`、`G2_INHERITANCE_SCIENTIFIC_AUDIT.md`、`G2_CONSTRAINTS_AMENDMENT.md`、`artifacts/g3/pre/` |
| S2 缺陷修复 | ✅ 完成 | `_stratified_panel_plan`、三路 schema 分派、分层重算（超支 3.16× 已记录） |
| S3 数据层 | ✅ 完成 | `presentation/run_repository.py`（schema 1/2/3）、`jobs/service.py`、`reports/report_service.py`、`audit/g2_recompute.py` |
| S4 UI MVP | ✅ 完成 | `app/main.py` + 五页 + `components/`；17 项 UI 测试 |
| S5 demo | ✅ 完成 | `runs/20261020_071457_G3_ea57a83b`：756 行 / 77.2 s / 4 图 / PASS |
| S6 回归 | ✅ 完成 | `artifacts/g3/tests/g3_full_junit.xml`；见 §9 |
| S7 冻结与审计 | ✅ 完成 | `_AUDIT/20261020_071457_G3_ea57a83b/`；独立解压复验 PASS |

**额外产出（计划外但为验收所必需）**：
`scripts/verify_g3_release.py`（一次性验收）、`tests/integration/test_g3_t*.py`（8 个矩阵）、
`docs/g3/G3_FINAL_STATUS.json`、`docs/g3/G3_VALIDATION_MATRIX.md`、
`docs/g3/DEMO_SCRIPT_5MIN.md`、`docs/g3/RESUME_CLAIMS_AND_LIMITS.md`。

## 9. 测试结果

全量 `pytest`：**424 passed / 0 failed / 0 errors / 0 skipped**，exit 0。
（G2 历史记录 252 条为历史值，不混写。）

| 矩阵 | 项数 |
|---|---|
| T-BASE | 12 |
| T-SCI | 25 |
| T-DATA | 20 |
| T-UI | 17 |
| T-REPORT | 15 |
| T-JOBS | 13 |
| T-REPRO | 16 |
| T-SECURITY | 24 |
| T-FINAL | 27 |
| 旧回归（unit / reference / integration） | 其余 |

## 10. 选型复核

本计划 §3 选了 Streamlit 1.66.0 并声明不用第二套 UI。执行结果：**只用了 Streamlit**，
未写任何 PySide6 代码。`app/` 下共 9 个模块，全部为 Python，无 C++/Qt 构建链。