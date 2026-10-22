# G3 基线核验（改动代码之前）

- 生成时间（UTC）：2026-10-20T05:55:40Z
- 项目根：`<PROJECT_ROOT>`
- Git HEAD：`PRIVATE_SOURCE_REVISION`
- 工作树状态：**dirty**（G2 交付物未提交；33 项变更/未跟踪）
- 机器可读版本：`docs/g3/G3_BASELINE_HASHES.json`

本文件是 G3 **冻结前的基线快照**。任何后续 `src/` 改动都不回溯修改本文件；
新增检查写到 `G3_ACCEPTANCE_CRITERIA.md` 的"结果"栏或独立报告。

## 1. 任务书声明的哈希与本机实测

| 项目 | 任务书声明 | 本机实测 | 判定 |
|---|---|---|---|
| 源 PDF SHA-256 | `25d0a727…a6f31e` 前缀一致 | `25d0a727fbf047e8b399be8bd1ab670149b4a32377ff8edcef63e41ca4e6319d` | **MATCH** |
| G2 AUDIT ZIP SHA-256 | `08a7b57e3e3ab62162ccef2d7d6c1a339a61c286dac2fef4446e38f4647ba6af` | 同左 | **MATCH** |
| G2 冻结配置 SHA-256 | `52369787c0e7f1dab7363a19132135a012dbe0fd9aa732e96a000d5a2e46e30c` | 同左（`configs/triangulation_g2_l1.yaml`） | **MATCH** |
| G2 ZIP 条目数 | 183（181 受管文件 + `manifest.json` + `SHA256SUMS.txt`） | 183 | **MATCH** |

G2 ZIP 文件大小 1 881 613 bytes；`AUDIT_ZIP_SHA256.txt` 在 ZIP 之外，符合防伪要求。

## 2. 冻结运行目录

| Gate | run_id | 目录大小 | 状态 |
|---|---|---|---|
| G0 | `20261019_130948_G0_78fa364f` | 478 K | PASS |
| G1 | `20261019_145702_G1_54c9e3fb` | 12 M | PASS |
| G2 | `20261019_191117_G2_52369787` | 27 M | PASS（`run_status.json` 记录） |

另有历史/失败目录保持原样，不纳入 G3 修改范围：

- `runs/20261019_165605_G2_2a5b529d`（205 K，早期 G2 探索）
- `runs/20261019_170944_G2_52369787`（27 M，执行 FAIL 的预修运行）
- `runs/20261019_190019_G2_52369787`（535 K，中断运行）
- `_AUDIT/_superseded/`（历史被取代审计包）

**G3 纪律**：以上目录在 G3 全程只读。G3 只写新的 `runs/<新 run_id>/`、
`runs/_derived/`、`_AUDIT/<新 run_id>/`、`docs/g3/`、`artifacts/g3/`。

## 3. G2 冻结运行的实测关键量

直接读取 `runs/20261019_191117_G2_52369787/independent_validation/summary.json`：

| candidate | n_valid / n_attempted | RMSE [mm] | P95 [mm] | 失败率 |
|---|---:|---:|---:|---:|
| baseline | 32 693 / 42 000 | 3.1481 | 6.6430 | 22.16 % |
| nominal | 35 337 / 42 000 | 3.0176 | 6.5663 | 15.86 % |
| robust | 31 373 / 42 000 | 1.9031 | 3.8349 | 25.30 % |

与任务书 1.1 节表格逐项一致。

完整逐样本明细 `independent_validation/sampled_results.csv` 本机实测：

- 文件字节 **25 928 093**；
- 表头 20 列，数据行 **126 000**（3 candidate × 2 000 assembly × 7 distance × 3 estimator）；
- 每候选 42 000 行，`(candidate, assembly)` 组合 6 000 个；
- **无 `# TRUNCATED` 尾行**（与 G2 审计 ZIP 内被截断的副本不同）。

这一点直接决定 PRE-G3-04 可以按"完整重算"处理，而不是 `INSUFFICIENT_EVIDENCE`。

## 4. 依赖与环境（实测）

| 项 | 实测值 |
|---|---|
| Python | 3.14.3（`.venv`，CPython） |
| numpy | 2.5.4 |
| scipy | 1.18.1 |
| matplotlib | 3.11.2 |
| pandas | 3.0.6 |
| psutil | 7.2.2 |
| optiland | 0.6.3（可导入） |
| pytest | 9.1.1 |
| CPU | 12 逻辑核 / 6 物理核 |
| RAM | 31.4 GB |
| GPU | GTX 1660 SUPER 6144 MB，**CUDA 不可用**（torch 未安装） |
| streamlit | 进入 G3 时为 **MISSING**，本轮安装（版本见 `G3_COMPUTE_BUDGET.md`） |

## 5. 进入 G3 时已确认的代码缺陷（复现记录）

这两条在**未修改任何源码**的状态下复现，构成 PRE-G3-03 与 PRE-G3-06.2 的初始证据。

### 5.1 `python -m optisys report --run runs/20261019_191117_G2_52369787` 崩溃

```
File "<PROJECT_ROOT>\src\optisys\cli.py", line 400, in cmd_report
    config = config_from_dict(...)
File "<PROJECT_ROOT>\src\optisys\config.py", line 162, in config_from_dict
    raise ConfigError(f"unsupported schema_version {schema_version!r}; expected {SCHEMA_VERSION!r}")
optisys.config.ConfigError: unsupported schema_version '3.0'; expected '1.0'
EXIT=1
```

`cmd_report` 只分派 `2.0`（G1）与"其它"（落到 schema 1.0），没有 3.0 分支。

### 5.2 `src/optisys/gates/g2.py::_final_stage` 条件分层子面板复用陈旧 `design`

`_final_stage` 中 Strategy B 循环里最后一次赋值是 `design = candidate.design`
（robust）。随后的条件分层循环：

```python
for name in candidate_names:
    candidate = registry.get(name)      # candidate 被重绑定
    factory = per_candidate[name]["fits"]
    subset = _assemble(subset_perturbations, design, config)   # design 未重绑定
    payloads = [... _assembly_payload(..., design=design) ...]  # 同上
```

`design` 仍是 robust 的 `B=34.4, f=7.272, θ=4.0`。即 baseline/nominal 的
strong/weak 子面板用的是 robust 几何。详见 `G2_INHERITANCE_SCIENTIFIC_AUDIT.md` 的 PRE-G3-03。

## 6. 本轮不改的东西

- 不重跑 G0/G1/G2 全量，不覆盖任何冻结目录。
- 不删除 `runs/20261019_170944_G2_52369787` 等失败运行。
- 不改写 `docs/g2/G2_PRE_REGISTRATION.md` 的任何文字（预注册是历史文件）。
- 不在 G3 启动 G4 的 976 nm 仿真。