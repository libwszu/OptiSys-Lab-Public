# 00_START_HERE — GPT 审计入口（G1）

## 1. 本次审计对象

| 字段 | 值 |
|---|---|
| Gate | G1 |
| run_id | `20261019_145702_G1_54c9e3fb` |
| 结果 | **PASS** |
| 科学声明状态 | SUPPORTED（仅限 L0 仿真链内部一致与误差可量化） |
| 模型等级 | L0 |
| 证据等级 | SIMULATED；G0 几何为 FORMULA / CROSS-CHECKED；**无 MEASURED / VALIDATED** |
| 数据集 | 4,920 帧（41 距离 × 3 条件 × 40 重复），14,760 条估计记录 |
| 测试 | 194 passed / 0 failed / 0 skipped |
| 代码提交 | `PRIVATE_SOURCE_REVISION` |
| 源码树 SHA-256 | `1c80c3e1f4d8adf28cdec25b19a010dc41f49bc05d27ff2fdaa086c30ad704d5` |
| 配置 SHA-256 | `54c9e3fb3a261a86b20ed6a51fb68a8d8c6e425fa17144c38e96feeb664350b6` |
| 源 PDF SHA-256 | `25d0a727fbf047e8b399be8bd1ab670149b4a32377ff8edcef63e41ca4e6319d` |
| G0 基线 | `20261019_130948_G0_78fa364f`，ZIP SHA-256 `3967d064cbc4349c6d484ec4378cdfe228115545089923b0d2629baab2d34c44`（未嵌套） |
| 硬件后端 | CPU（4 帧工作进程） |

## 2. 30 秒结论

1. L0 高斯光斑按**像元面积**积分（normal CDF 差），非裁切能量相对偏差 **0**；独立 Gauss–Legendre 对照 **3.44e-14**。
2. 无噪声亚像素误差：质心 **1.96e-4 px**、1D **8.03e-4 px**、2D **7.81e-5 px**（阈值 0.05 / 0.02 / 0.01）。
3. 单像元噪声：5 种工况 × 3 次独立 10,000 抽样（合并 n=30,000），均值/方差全部落在 99% 区间；暗电流斜率 5002.04 e/s（相对误差 4.08e-4）。
4. 系统标定只辨识 `a=fxB`、`b=cx−fx tanθ`；`a` 恢复相对误差 4.3e-6–8.3e-6，`b` 偏差 ≤0.001 px。
5. 27/7/7 距离划分互斥；测试集 2,520 次估计，有效 2,481，失败率 **1.55%**（分母为全部尝试帧）。
6. 端到端 RMSE：质心 0.0497 mm、1D 0.0689 mm、2D 0.0444 mm（条件于有效帧）；弱信号下 2D 失败率 13.9%，已如实报告。
7. G0 的 5 项 P1 整改（CLI 退出码、Gate 聚合、冻结保护、反演像面、单位冲突）均有测试，G0 几何回归仍为 2.27e-13 px。

## 3. 文件导航

| 文件 | 用途 |
|---|---|
| `01_EXECUTIVE_SUMMARY.md` | 完成/未完成、负结果与判定 |
| `02_SPEC_TRACEABILITY.md` | R01–R11、G0–G4 追溯 |
| `03_SCIENTIFIC_AUDIT.md` | 公式、单位、独立对照、标定可辨识性、分母 |
| `04_VALIDATION_MATRIX.md` | V0–V7、V1/V2/V3 明细、测试分布 |
| `05_COMPUTE_AND_PERFORMANCE.md` | 实测硬件、G1 基准、并行动机、内存 |
| `06_REPRODUCTION_GUIDE.md` | 干净环境复现与预期输出 |
| `07_KNOWN_ISSUES_AND_FAILURES.md` | 失败运行、负结果、未解决问题 |
| `08_NEXT_GATE_PLAN.md` | G2 路线（仅建议，未执行） |
| `GPT_REVIEW_INSTRUCTIONS.md` | 可执行的审查清单 |
| `manifest.json` / `SHA256SUMS.txt` | 机器可读状态与哈希 |
| `baseline_g0/` | G0 run id、ZIP 哈希、回归结果（无嵌套 ZIP） |
| `run_evidence/` | 配置、环境、基准、指标、标定、划分、样本、代表帧、图、报告 |
| `src/`、`tests/`、`configs/`、`scripts/`、`repro/` | 可独立理解的代码与复现入口 |
| `.github/workflows/ci.yml` | 本地 CI 配置（远端未运行） |

## 4. 最短复核路径

```powershell
python repro/verify_g1.py     # 期望 REPRO_STATUS: PASS
python -m pytest -q           # 期望 194 passed
python scripts/verify_audit_package.py   # 期望 problems: 0
```

数值对照：

- `run_evidence/metrics.json` → `gate_checks`（18 项全部 pass）、`dataset`（4,920）、`summaries`
- `run_evidence/calibration.json` → 三个估计器的 `a,b,std,condition_number,n_frames_used`
- `run_evidence/split_manifest.json` → 27/7/7 与 hash
- `run_evidence/samples/samples.csv` → 14,760 行，含失败帧与质量标志
- `run_evidence/representative_frames/index.json` → 6 个代表帧用途

## 5. 不要从本包得出的结论

- 不是真实相机/镜头性能；所有传感器参数为设计假设。
- 不是工业测距精度；“0.1 mm”不是验收阈值。
- 不含镜头 PSF、像差、散斑、PRNU/DSNU、滚动快门。
- 未做相机内参标定；`B, fx, cx, θ` 不可由一维 Z–u 数据唯一辨识。
- 远端 CI 未运行：`REMOTE_CI_NOT_VERIFIED`。
- 无实测数据：V7 `NOT_RUN`。

## 6. 包的生成与校验

- `scripts/build_g1_audit_package.py`：构建 `package/` → 敏感信息扫描 → `manifest.json` → `SHA256SUMS.txt` → ZIP。
- 已执行：`zipfile.testzip()`、路径穿越检查、160+ 文件逐项哈希、独立临时目录解压、必需文件清单、解压副本 `repro/verify_g1.py` 实际运行。
- ZIP 大小 < 40 MB；包外 `AUDIT_ZIP_SHA256.txt` 记录哈希、字节数与文件数。
