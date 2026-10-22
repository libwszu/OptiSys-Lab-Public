# G2 继承的科学审计（G3 轮）

生成时间：2026-10-20（UTC）
对象：`runs/20261019_191117_G2_52369787`（冻结，本轮**未修改**任何字节）
机器可读裁决：`docs/g3/G2_INHERITANCE_VERDICT.json`

> 本文只陈述本轮实际执行的检查与其结果。没有执行过的检查不写结论。

---

## 0. 一句话裁决

历史 G2 运行**记为** `PASS`，其数值在 126 000 行原始明细上可被完全独立重算，但**预注册未被遵守**：四项材料性偏离（HC3 门限、测试距离泄漏、最终面板条件缺失、标定模型选择未执行）。因此科学主张只能是 `QUALIFIED_ONLY`，不能把历史 `PASS` 当作未受限的真实性背书。

| 字段 | 值 | 依据 |
|---|---|---|
| `historical_g2_execution` | `PASS_RECORDED` | `run_status.json`: status=PASS, 252/252 测试绑定, 27 门全绿 |
| `original_prereg_compliance` | **`FAIL`** | 见 §1 |
| `as_run_numerical_verification` | **`PASS`** | 见 §2 |
| `stratified_panel_repair` | **`PASS`** | 见 §3 |
| `full_samples_available` | **`true`** | 见 §4 |
| `scientific_claim_allowed` | **`QUALIFIED_ONLY`** | 见 §6 |

两行结论互相独立：工程执行确实跑完了，数值确实自洽；同时预注册确实没被遵守。压缩成一个 `G2_ALL_PASS` 会同时宣称两件相反的事。

---

## 1. 预注册合规：`FAIL`（四项材料性偏离）

### 1.1 HC3 门限冲突（PRE-G3-01）

| 项 | 值 |
|---|---|
| 预注册 | `docs/g2/G2_PRE_REGISTRATION.md:33`，`kernel support >= 0.999` |
| as-run | `configs/triangulation_g2_l1.yaml:112`，`min_kernel_support: 0.950` |

**实测**（`scripts/g3_pre_g3_01_hc3.py`，四档门限 × 三候选 × 3 约束距离 + 观测面板）：

| 候选 | probe@100 | probe@200 | probe@300 | 观测 min | 观测 max | < 0.999 占比 | < 0.950 占比 |
|---|---|---|---|---|---|---|---|
| baseline | 0.9787 | 0.9804 | 0.9820 | 0.97505 | 0.98738 | **100 %** | 0 % |
| nominal | 0.9836 | 0.9737 | 0.9783 | 0.97280 | 0.98621 | **100 %** | 0 % |
| robust | 0.9871 | 0.9814 | 0.9814 | 0.97499 | 0.99051 | **100 %** | 0 % |

三个冻结设计在 0.999 下**全部不可行**。这不是舍入差异，是量级差异。

**科学读法**：0.999 是对**有限 PSF 窗**的截断要求。窗口半宽由几何足迹决定（`half = ceil(max|du|,|dv|) + airy_radius_margin × airy_radius + 1`，上限 `max_half_px=40`），而单透镜在 f/6.7–f/10 下 Airy 半径 ~1.4 px、几何足迹仅 3–9 µm，窗口天然紧，0.972–0.991 是结构上限。**0.999 对该光学模型不可达，HC3 是一条病态约束，而非一条严格约束。**

> ⚠️ 这个读法是**事后修订的依据**，不是追溯辩护。预注册文本仍然是它原来的样子，`G2_PRE_REGISTRATION.md` 一个字节都没改。
> 状态令牌：`G2_PREREG_FEASIBILITY_NOT_ESTABLISHED`

### 1.2 最终测试距离进入开发阶段（PRE-G3-02）

| 项 | 内容 |
|---|---|
| 预注册 | `docs/g2/G2_PRE_REGISTRATION.md:69`，最终测试距离不得出现在 search / OAT / precheck / 模型选择中 |
| as-run | `OAT`、`PRECHECK`、`PRECHECK(observed)` 均评估 **105.0 mm** 与 **285.0 mm** |
| 泄漏计数 | 3 个阶段 × 2 个距离 |

既有 O6 检查只覆盖了 `TRAIN vs FINAL-TEST(main)`，漏掉 `OAT vs FINAL-TEST` 与 `PRECHECK vs FINAL-TEST`。

**泄漏性质**：**距离复用**，不是种子复用、也不是装配复用。OAT 与 precheck 用 `G2P` 命名空间，最终测试用 `G2F`，`FIN####` 与 `PRE####` 互不相交。后果是：冻结设计在三个后来充当测试距离的距离上被筛过，那两个测试点在**设计层面**不是纯 holdout。
状态令牌：`G2_FINAL_DISTANCE_LEAK_INTO_DEVELOPMENT`

### 1.3 搜索全跑在 validation 距离上（PRE-G3-02b）

预注册把 `validation_distances`（10 个值）声明为「仅用于模型族选择」。但 `_search_stage` 把其中两个子集（7 值、4 值）直接塞进了 nominal 与 robust 的目标函数。声明的 search-train 列表（100..300 step 20）**从未被使用**。

结论：设计搜索背后**根本不存在距离级 holdout**。
状态令牌：`G2_SEARCH_USES_VALIDATION_DISTANCES`

### 1.4 最终面板条件缺失（PRE-G3-02c）

| 项 | 预注册 | as-run |
|---|---|---|
| 每装配帧数 | 7 距离 × {strong, medium, weak} = 21 | 7 距离 × medium only = 7 |

所以每候选 42 000 行是 `(2000 装配 × 7 距离 × 3 估计器)` 的记录数，**不是** 42 000 张独立多工况图像。主面板的一切结论都只在 medium 条件下成立。
状态令牌：`G2_FINAL_PANEL_DEVIATION`

### 1.5 标定模型选择未按预注册执行（PRE-G3-06.5）

| 项 | 内容 |
|---|---|
| 预注册 | `G2_PRE_REGISTRATION.md:113-116`：M2 的 validation RMSE 若比 M1 低 ≥ 20 % 则选 M2，且在最终测试**之前**写 `calibration_model_choice.json` |
| as-run | `config_snapshot.yaml:117` 直接写 `model: M1` |
| 调用点检索 | `select_model()` 全仓只出现在 `tests/unit/test_tolerance_g2.py:194` |
| 产物检索 | `calibration_model_choice.json` 在冻结 run 中**不存在** |

M1 是配置选择的结果，不是那条规则输出的结果。
状态令牌：`CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED`

**补充（PRE-G3-06.1 的独立测算）**：M2 的 rms 为 0.01848 px，M1 为 0.30423 px，**M2 优于 M1 16.46×**。所以按注册规则执行，大概率会选 M2。本条的发现是「规则被跳过」，不是「M1 是错答案」。

---

## 2. as-run 数值核验：`PASS`

`src/optisys/audit/g2_recompute.py` 不导入任何 G2 gate 代码，从原始逐样本 CSV 重新推导全部聚合量。

| 项 | 值 |
|---|---|
| 源文件 | `runs/20261019_191117_G2_52369787/independent_validation/sampled_results.csv` |
| SHA-256 | `58e4a4c8216ec1769aeb43e3be77f4e7437c0fd6c6fccccb4b639fe2243a3080` |
| 字节数 | 25 928 093 |
| 行数 | **126 000**（期望 126 000） |
| `# TRUNCATED` 标记 | **不存在** |
| 重复主键 | 0 |
| 模糊 valid 单元格 | 0 |
| valid 但非有限值 | 0 |
| 耗时 | 25 s |

| 候选 | n_valid | RMSE (mm) | P95 (mm) | bias (mm) | MAE (mm) | 失败率 | 冻结值比对 |
|---|---|---|---|---|---|---|---|
| baseline | 32 693 | 3.14812689267054 | 6.643043 | +0.141057 | 2.320033 | 0.22159524 | **MATCH** |
| nominal | 35 337 | 3.017621563364543 | 6.566348 | +0.063774 | 2.145345 | 0.15864286 | **MATCH** |
| robust | 31 373 | 1.903109443210548 | 3.834881 | −0.171747 | 1.476441 | 0.25302381 | **MATCH** |

容差 `rtol=1e-9`、率值 `atol=1e-12`。**实测最大相对差 0.0**。逐估计器（9 组）同样全部 MATCH。

6 组配对 bootstrap（3 对 × {RMSE, 失败率}）全部重算出与冻结 CI 同号的结论：

| 配对 | ΔRMSE (mm) | 95 % CI | 排除 0 | Δ失败率 | 95 % CI |
|---|---|---|---|---|---|
| nominal − baseline | −0.10995 | [−0.21195, −0.01850] | 是 | −0.06557 | [−0.07043, −0.06079] |
| robust − baseline | −1.11645 | [−1.16474, −1.07159] | 是 | +0.02571 | [+0.02043, +0.03079] |
| robust − nominal | −0.99327 | [−1.07103, −0.91442] | 是 | +0.09129 | [+0.08364, +0.09900] |

聚类单元 `assembly_id`，2000 次重采样，种子 424242。

**这证明**：冻结 CSV 与冻结汇总互相自洽，记录下来的数字不是转录或聚合伪影。
**这不证明**：物理实测、从零光学复跑、预注册合规、L1-approximate 模型本身的正确性。
门限：`as_run_numerical_verification = PASS`。

---

## 3. 分层面板修复：`PASS`

### 3.1 缺陷

`src/optisys/gates/g2.py::_final_stage` 的第三段循环复用了 Strategy B 候选循环遗留的 `design` 变量，于是**每个候选**的 strong/weak 分层都用 robust 几何（B=34.4，f=7.272385，θ=4.0）渲染。

### 3.2 主面板为何未受污染

Strategy A 主面板与 Strategy B 子集都在各自循环内重新绑定自己的 design，只有第三段继承了陈旧绑定。

**数据级证明**：对每候选，用自己的标定参数反解 `Z_hat` 残差 **0.0 mm**；用其他候选的参数反解，最大残差 **8034.7 mm**。→ 主面板每一行都由各自候选的工厂标定产生，陈旧变量从未进入 126 000 行主表。

### 3.3 回归测试（先失败，后通过）

```
tests/integration/test_g3_pre_g3_03.py::test_every_assembling_loop_binds_its_own_design
tests/integration/test_g3_pre_g3_03.py::test_stratified_plan_binds_design_per_candidate
tests/integration/test_g3_pre_g3_03.py::test_stratified_plan_independent_of_loop_order
tests/integration/test_g3_pre_g3_03.py::test_stratified_measurement_rebind_bug_would_be_caught
```

修复前实测报错 `candidate loop #2 at line 1140 does not bind design`，修复后 4/4 通过。

### 3.4 最小修复

新增 `_stratified_panel_plan(registry, candidate_names, perturbations, config)`，按候选显式构建 `(design, assemblies)` 计划；`_final_stage` 遍历计划并写 `stratified_<name>.csv`。不改动任何已冻结数值。

### 3.5 重算结果

200 装配 × 7 距离 × 2 条件 × 3 估计器，命名空间 `G2F_C`，每候选 8 400 行，单进程。

| 候选 | 条件 | 旧 RMSE (mm) | 新 RMSE (mm) | 旧失败率 | 新失败率 |
|---|---|---|---|---|---|
| baseline | strong | 24.0057 | **3.7322** | 0.8350 | 0.6971 |
| baseline | weak | 23.8676 | **3.0789** | 0.5626 | 0.2133 |
| nominal | strong | 117.6668 | **2.9035** | 0.7857 | 0.5105 |
| nominal | weak | 114.1704 | **6.5429** | 0.5364 | 0.2412 |
| robust | strong | 2.1457 | 2.1457 | 0.6426 | 0.6426 |
| robust | weak | 4.4412 | 4.4412 | 0.2314 | 0.2314 |

robust 的 delta 恒为 0.0 —— 因为 robust 自己的几何恰好就是被陈旧绑定的那份，缺陷对它是「错得正好」。

### 3.6 科学后果

旧分层面板对 baseline 与 nominal **不携带任何候选专属信息**。任何从该面板读出的「候选 X 在强光下表现差」一律撤回。

修复后候选确实分开了：nominal 的 weak RMSE 升到 6.54 mm，baseline weak 为 3.08 mm。分层条件也没能挽救 nominal。

**预算超支记录**：实测 1 897.8 s，超出 `G3_COMPUTE_BUDGET.md` 的 600 s 预算 3.16 倍。按 `G3-D-001`，**不修改已冻结的预算数值**，实测值记入 `docs/g3/G3_COMPUTE_MEASURED.md`。

---

## 4. 完整明细可得性：`true`

| 项 | 内容 |
|---|---|
| 任务书说法 | G2 审计 ZIP 内 `sampled_results.csv` 被截断至 20 000 行并含 `# TRUNCATED` |
| 本机事实 | 冻结 run 目录内该文件 **25 928 093 字节 / 126 000 行 / 无截断标记** |
| 判定 | 对 ZIP **成立**，对本机 run 目录 **不成立** |
| 结论 | PRE-G3-04 是**审计打包缺陷**，不是数据丢失缺陷 |

处置：G3 审计包直接装完整文件并附独立 SHA-256 增补记录；**G2 ZIP 不重新打包**，保持字节一致以便溯源。

---

## 5. 其他勘误项

### 5.1 L1 像高公式多乘 1/Z（PRE-G3-06.1）

原句（`03_SCIENTIFIC_AUDIT.md` §4）：

```
u_lens - cx = fx * (image distance / Z) * B / Z + distortion
```

| Z (mm) | traced u (px) | 原句给出 (px) | 误差 (px) | 误差占待解释偏移比例 |
|---|---|---|---|---|
| 100 | 1117.26 | 673.73 | −443.54 | −92.9 % |
| 150 | 959.47 | 654.99 | −304.48 | −95.3 % |
| 200 | 879.95 | 648.43 | −231.51 | **−96.5 %** |
| 250 | 832.08 | 645.40 | −186.69 | −97.2 % |
| 300 | 800.13 | 643.75 | −156.38 | −97.7 % |

公式给出的偏移量只有真值的 2–7 %。错误类别：**Z 的代数幂次（多一个 1/Z）**，不是符号错。

**正确形式**：`u_lens − cx = −fx · m(Z) · (B − Z·tanθ) / p`，其中 `m(Z) = f/(Z − z_H)`，即 M2 形式 `u = a/(Z−c) + b`，`c = z_H`。

**模型对比**（关键反证）：

| 模型 | a | b | c (mm) | rms (px) | max abs (px) |
|---|---|---|---|---|---|
| M1 `a/Z + b` | 47 563.48 | 641.910 | — | 0.30423 | 0.47106 |
| M2 `a/(Z−c) + b` | 48 496.89 | 639.230 | **−1.45** | **0.01848** | 0.02382 |

M2 优于 M1 **16.46×**。

**可伪证预测**：若原句的「image distance / Z」机制成立，`c` 应落在焦距 8 mm 附近；实测落在 **−1.45 mm**，指向**主平面偏移**，不是简单的 1/Z 重标定。把 `c` 当焦距读会错两次。

`13.49 px` 那个数字（L0 vs traced 之差）仍然有效，错的只是展示的公式。**没有冻结数字发生变化**，这是纯文档勘误，且**不修改**旧审计文件——本文件即为勘误记录。

### 5.2 Strategy A/B 不可直接相减（PRE-G3-05）

| 维度 | A | B |
|---|---|---|
| 装配数 | 2000 | 200 |
| 估计器 | 3 | 1 |
| 尝试行数 | 42 000 | 1 400 |
| 每单元校准帧 | 0 | 9 |
| 标定对象 | 工厂名义单元 | 各装配自身扰动光学 |

裁定：`NOT_DIRECTLY_COMPARABLE`。唯一可接受的比较是按估计器对齐的那一格：

| 候选 | A RMSE (integrated, mm) | B RMSE (mm) | A 失败率 | B 失败率 |
|---|---|---|---|---|
| baseline | 3.00332 | 0.22940 | 0.10514 | 0.09286 |
| nominal | 2.92517 | 0.03852 | 0.00100 | 0.00071 |
| robust | 1.88504 | 0.48891 | 0.12929 | 0.12357 |

即便如此仍非配对检验：B 只覆盖 2000 个装配中的 200 个。**最小诚实比较是在 200 个共享装配上做同估计器的配对 A/B bootstrap，本轮 `NOT_RUN`**（预算受限，且 A 侧无该 200 子集的逐样本结果）。

**撤回**：「重标定大约值 1.5 mm（baseline）到 3 mm（robust）」。该句把 200 装配单估计器的数减到了 2000 装配三估计器的数上，混合了总体。

### 5.3 校准帧数勘误 5 → 9（PRE-G3-05b）

`g2.py:1046` 的非 quick 路径取 9 个校准距离。报告写 5，是 quick 模式的值。**报告文字错、代码对**，且 Strategy B 的成本被低估了 80 %。

### 5.4 CLI 无 schema 3.0 分支（PRE-G3-06.2）

原 `cmd_report` 只分派 `2.0`，其余全部落到 schema 1.0，于是 G2 run 报 `ConfigError: unsupported schema_version '3.0'`（exit 1）。

新增 `_resolve_report_config()` 从 `config_snapshot.yaml` 三路分派 1.0 / 2.0 / 3.0，`cmd_report` 增加 `kind == G2` 分支调用 `render_g2_report`。验证输出 `frozen_run_untouched: True`，并在报告生成后对冻结 run 执行 `sha256sum -c` 通过。

### 5.5 审计包缺件（PRE-G3-06.4）

G2 ZIP 缺 `pyproject.toml`、CI workflow、`README`，收件方无法仅凭包重建环境。G3 包补齐这三项；G2 ZIP 不重打包。

---

## 6. 允许的科学主张：`QUALIFIED_ONLY`

**存活的主张**（全部限于 L1-approximate 单透镜模型 + medium 光照条件）：

- robust 的配对 RMSE 低于 baseline：Δ = −1.1165 mm，95 % CI [−1.1647, −1.0716]，排除 0，2000 装配聚类
- robust 的配对 RMSE 低于 nominal：Δ = −0.9933 mm，95 % CI [−1.0710, −0.9144]，排除 0
- nominal 的配对 RMSE 低于 baseline：Δ = −0.1099 mm，95 % CI [−0.2119, −0.0185]，排除 0

**必须与每个数字同屏的令牌**：

1. `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED`
2. `G2_FINAL_PANEL_DEVIATION`
3. `G2_FINAL_DISTANCE_LEAK_INTO_DEVELOPMENT`
4. `CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED`
5. robust 的更高失败率（0.2530 vs baseline 0.2216）

**禁止表述**：

- 「完全遵守预注册」
- 「G2 通过全部科学门」
- 「重标定值 1.5–3 mm」（已撤回）
- 「每单元 5 个校准帧」（已勘误为 9）
- 「robust 是最优设计」

**未升级**：不晋升 `MEASURED` 或 `VALIDATED`。无任何物理数据。证据层级上限仍是 `SIMULATED` / `CROSS_CHECKED`。

---

## 7. 复现方式

```bash
# 1. 基线哈希核验（只读）
python scripts/g3_baseline_snapshot.py

# 2. 126000 行独立重算
python -c "from optisys.audit.g2_recompute import main; main()"
# 或看 artifacts/g3/pre/g2_recompute.json

# 3. HC3 门限扫描
python scripts/g3_pre_g3_01_hc3.py

# 4. 数据使用图
python scripts/g3_pre_g3_02_data_usage.py

# 5. 分层缺陷回归测试
pytest tests/integration/test_g3_pre_g3_03.py -v

# 6. 分层重算（约 1900 s，超预算，谨慎）
python scripts/g3_pre_g3_03_stratified_repair.py

# 7. A/B 可比性
python scripts/g3_pre_g3_05_comparability.py

# 8. 公式勘误
python scripts/g3_pre_g3_06_formula.py
```