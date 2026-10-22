# 00_START_HERE — GPT 审计入口

## 1. 这是什么

**OptiSys-Lab** 是一个面向就业的光电系统仿真平台。本包是 **G0（工程基线 + 二维共面几何独立验证）** 的审计快照。

| 字段 | 值 |
|---|---|
| Gate | G0 |
| run_id | `20261019_130948_G0_78fa364f` |
| 结果 | **PASS** |
| 科学声明状态 | SUPPORTED（仅限“理想共面几何实现与独立链一致”） |
| 模型等级 | L0（理想针孔，无镜头/噪声/PSF） |
| 证据等级 | FORMULA、SIMULATED、CROSS-CHECKED；**无 MEASURED / VALIDATED** |
| 硬件后端 | CPU |
| 代码提交 | `PRIVATE_SOURCE_REVISION` |
| 源码树 SHA-256 | `054b0919c53cdd1b8e155043decf92a768948c13132ac76b172a8cf039a50960` |
| 源 PDF SHA-256 | `25d0a727fbf047e8b399be8bd1ab670149b4a32377ff8edcef63e41ca4e6319d` |
| 测试 | 117 passed / 0 failed / 0 skipped |

## 2. 30 秒结论

1. 解析式 `X_L = B − Z tanθ`、`u = cx + fx(B/Z − tanθ)`、`Z = fxB/(u − cx + fx tanθ)` 已实现，并有标量与向量化两条路径。
2. 独立对照链（3×3 线性方程求交 + 齐次 3×4 投影矩阵 + Brent 反演）给出同一结果：最大像点差 **2.27e-13 px**，门限 1e-8 px。
3. 反演一致性 **7.7e-16**（相对），导数与参考链有限差分一致性 **6.1e-10**（相对）。
4. 123 个工况点全部有效；11 个边界/病态用例全部返回预期状态码，未把 NaN/越界值当作测量。
5. PDF 第 8 页印刷数值（463.77 / 231.88 / 154.59 px，0.8625 / 1.9406 mm/px）被本实现复现到印刷精度。
6. PDF 式 (3) 的 `dZ/du` 印刷为正号，但与式 (2) 的有符号求导矛盾；幅值正确、符号缺失，见 `03_SCIENTIFIC_AUDIT.md` 第 6 节与 `docs/SPEC_DISCREPANCIES.md`。

## 3. 文件导航

| 文件 | 用途 |
|---|---|
| `01_EXECUTIVE_SUMMARY.md` | 完成/未完成清单与判定 |
| `02_SPEC_TRACEABILITY.md` | R01–R11、G0–G4 追溯 |
| `03_SCIENTIFIC_AUDIT.md` | 假设、公式、单位、独立方法、SD-001、局限 |
| `04_VALIDATION_MATRIX.md` | V0–V7 与 11 个边界用例 |
| `05_COMPUTE_AND_PERFORMANCE.md` | 实测硬件、基准、并行与 GPU 决策 |
| `06_REPRODUCTION_GUIDE.md` | 干净环境复现步骤与预期输出 |
| `07_KNOWN_ISSUES_AND_FAILURES.md` | 未关闭问题、失败运行、负结果 |
| `08_NEXT_GATE_PLAN.md` | G1 最小路线与验收 |
| `GPT_REVIEW_INSTRUCTIONS.md` | 给审稿 AI 的具体任务 |
| `manifest.json` | 机器可读状态、哈希、需求/验证矩阵 |
| `SHA256SUMS.txt` | 包内逐文件校验 |
| `src/optisys/` | 实际源码（完整可读） |
| `tests/` | 实际执行的 117 个测试 |
| `configs/` | 有效配置与 JSON Schema |
| `repro/` | 最小独立复现脚本（解压后可直接运行） |
| `run_evidence/` | 本次冻结运行的配置、环境、基准、指标、样本、图 |
| `source_spec/` | 原始 PDF 与哈希 |

## 4. 独立复核的最短路径

```powershell
# 1) 解压后，在包根目录运行最小复现（只用包内 src 与 configs）
python repro/verify_g0.py
# 期望：max |u_a - u_ref| ~ 2e-13 px；REPRO_STATUS: PASS

# 2) 运行完整测试（需要 numpy/scipy/matplotlib/pyyaml/psutil/pytest）
python -m pip install -e .[dev]
python -m pytest -q
# 期望：117 passed

# 3) 对照证据
#    run_evidence/metrics.json          -> gate_checks 全部 pass
#    run_evidence/samples/samples.csv   -> 123 行，status 全为 OK
#    run_evidence/figures/fig4_*.png    -> 残差散点，远低于 1e-8 px
```

## 5. 不要从本包得出的结论

- 不要认为传感器精度、重复性、温漂、信噪比已被验证：**没有任何成像或噪声模型**。
- 不要认为镜头/PSF/像差已被建模：Optiland 仅安装并验证可导入，**未运行镜头案例**。
- 不要认为跨平台可复现已完成：仅本机 Windows 验证，CI 未在远端运行（`CI_NOT_VERIFIED`）。
- 不要把 G0 报告当作 G3 的交互式应用。
- 不要把 `peak_electrons`、`spot_sigma_px` 等配置字段当作已生效的物理参数：它们在 G0 只做 schema 校验。

## 6. 包的生成与校验

- 包由 `scripts/build_audit_package.py` 构建：先写 `package/`，再扫描敏感信息、生成 `manifest.json` 与 `SHA256SUMS.txt`，最后压缩。
- ZIP 完整性：`zipfile.testzip()` 已执行。
- 独立临时目录解压后：逐文件 SHA-256 复验、路径安全扫描、必需文件检查。
- 解压副本中的 `repro/verify_g0.py` 已实际执行并返回 PASS。
- ZIP 自身的 SHA-256 与大小写在包外 `AUDIT_ZIP_SHA256.txt`。
