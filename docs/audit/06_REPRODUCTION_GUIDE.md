# 06_REPRODUCTION_GUIDE

目标：从干净环境复现 G0 的核心数值证据，并区分“数值可复现”与“耗时不可复现”。

## 0. 前置条件

- Python ≥ 3.11（本次验证：CPython 3.14.3，Windows 11）
- 可访问 PyPI，或在离线环境使用 `requirements.lock.txt`
- 无需 GPU、无需 Optiland（G0 不依赖）

## 1. 干净环境重建

```powershell
# 进入解压后的审计包根目录（包含 pyproject.toml 与 src/）
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

若不能联网，使用锁定文件（包含所有传递依赖）：

```powershell
python -m pip install -r requirements.lock.txt
python -m pip install -e . --no-deps
```

> `requirements.lock.txt` 由 `pip freeze` 生成，包含 optiland 0.6.3 及其依赖（vtk 等）。这些是可选 L1 依赖，G0 不导入。

## 2. 最小独立复现（推荐先跑）

```powershell
python repro/verify_g0.py
```

预期输出（数值可能因平台数学库有最后一位差异，量级必须一致）：

```text
config              : ...\configs\triangulation_v0.yaml
fx [pixel]          : 2318.840579710
samples             : 41
max |u_a - u_ref|   : 2.274e-13 px (gate 1e-08)
max rel Z error     : 5.684e-16
max rel d(du/dZ)    : 5.736e-10
dZ/du @200 mm       : -0.862500 mm/px (magnitude 0.862500)
REPRO_STATUS        : PASS
```

> `repro/verify_g0.py` 只跑 **θ = 0° 的 41 个点**，因此它的 `max rel Z error`（5.7e-16）与完整运行的 123 点指标（7.7e-16）略有不同，两者都远低于阈值。完整指标以 `run_evidence/metrics.json` 为准。

判定：`REPRO_STATUS` 必须为 `PASS`；若为 `FAIL`，G0 结论不可沿用。

## 3. 完整测试

```powershell
python -m pytest -q
```

预期：`117 passed`，约 50–60 s（其中 3 个集成测试各运行一次精简基准）。

测试分组：

| 目录 | 用例数 | 作用 |
|---|---|---|
| `tests/unit` | 102 | 单位、配置、前向、独立链、导数、边界 |
| `tests/reference` | 9 | 与 PDF 印刷数值对照 |
| `tests/integration` | 6 | CLI 退出码、运行目录完整性、报告重建 |

## 4. 命令行验证

```powershell
python -m optisys validate --config configs/triangulation_v0.yaml
# 期望：CONFIG_VALID，fx_px = 2318.8405797101445

python -m optisys simulate --config configs/triangulation_v0.yaml
# 期望：新 runs/<run_id>/，status = PASS，max_abs_u_error_px ≈ 2.27e-13

python -m optisys tolerance --config configs/triangulation_v0.yaml
# 期望：NOT_IMPLEMENTED，退出码 3（G2 未实现，这是正确行为）
```

## 5. 复现审计对象

本次冻结 run：`20261019_130948_G0_78fa364f`。

对照以下文件：

| 文件 | 检查点 |
|---|---|
| `run_evidence/metrics.json` | `gate_checks` 全部 `pass: true`；`chain.n_points = 123` |
| `run_evidence/samples/samples.csv` | 123 行；`status` 全为 `OK`；`inverse_status` 全为 `OK` |
| `run_evidence/samples/formula_comparison.csv` | 6 行，与 PDF 印刷值对照 |
| `run_evidence/samples/boundary_cases.csv` | 11 行，`pass` 全为 `TRUE` |
| `run_evidence/figures/fig4_independent_residual.png` | 残差散点在 0 与 ~1e-13 px 两条带 |
| `run_evidence/benchmark.json` | 耗时与并行数据 |
| `manifest.json` | `result_status = PASS`，`tests.passed = 117` |

新运行的 `run_id` 会不同（时间戳），但 `metrics.json` 中的几何指标应逐位一致（同一平台/同一依赖）。

## 6. 包完整性自检

```powershell
python scripts/verify_audit_package.py
```

预期：`VERIFY_STATUS : PASS`，`problems : 0`。

## 7. 已知的可复现性边界

| 项 | 是否逐位一致 | 说明 |
|---|---|---|
| 几何数值 | 是（同平台/同 numpy） | 纯 IEEE-754 双精度运算 |
| 图 PNG 字节 | 否 | matplotlib 版本/字体/渲染差异 |
| 耗时 | 否 | 受 CPU 负载、频率、后台进程影响；只有量级可比较 |
| 报告 HTML 字节 | 否 | 含时间戳与哈希 |
| Windows 外的路径分隔符 | 否 | 代码使用 `pathlib`，数值不受影响 |

## 8. 常见失败与处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: optisys` | 未安装包或未在包根目录 | `pip install -e .` 或设置 `PYTHONPATH=src` |
| `CONFIG_INVALID: unknown key` | 配置被手工改动 | 恢复 `configs/triangulation_v0.yaml` |
| `pytest` 中集成测试很慢 | 基准包含进程池启动 | 正常，约 2–3 s/次；不是挂起 |
| `repro` 报 FAIL 且残差 ~1e-13 | 阈值比较用了绝对 0 | 检查是否误改了 `U_TOLERANCE_PX` |
| 中文字体缺失（图） | 图为英文标注，不影响 | 报告正文为 HTML，不依赖本机字体 |
