# G4 验证矩阵

正式结果来自 `runs/20261020_133555_G4_ec3e2813_0e48`。验收阈值在结果前冻结于 `G4_ACCEPTANCE_CRITERIA.md`，哈希见 `G4_FREEZE_HASHES.json`。

| ID | 判据/范围 | 观测 | 判定 | 证据 |
|---|---|---|---|---|
| PRE4-01 | 继承两条裁决线 | G3 工程 `PASS_WITH_DECLARED_DEVIATIONS`；G2 science `QUALIFIED_ONLY` | PASS | `G4_PRE_REPORT.md`、G3 baseline docs |
| PRE4-02 | G3 ZIP 内容和跨环境重建分开 | 212 members / 210 manifest files；Python 3.14 完整复现；3.11 只在 DEFLATE 字节重建不同 | CONTENT PASS；cross-env old G3 DEFLATE 不保证 | `G4_BASELINE_DISCREPANCIES.md` |
| PRE4-03 | 历史 pytest 时间差 | JUnit 141.655 s 与 stdout 141.66 s 一致；145.545 s 外层时间不可重建 | suite duration 确认；process wall `HISTORICAL_DURATION_NOT_ADJUDICATED` | 同上 |
| PRE4-04 | G3 756 行原始 CSV | 756 rows、124,183 bytes、哈希与历史一致 | PASS | `G4_BASELINE_DISCREPANCIES.md`、`baseline_g3/G3_756_sampled_results.csv` |
| PRE4-05 | 扩展点 | CLI、JobService、ReportService、Optiland、旧五页定向回归 73 passed | PASS | `artifacts/g4/pre/` |
| PRE4-06 | Optiland | Optiland 0.6.3 两个真实 singlet surfaces；NA=0.05 P0/P1 r80 相对差 <1%、位置差 <0.01 mm；NA=0.22 明显模型差异 | QUALIFIED | `run/optical_crosscheck.json`、`raytrace_reference.csv` |
| PRE4-07 | CPU/worker/GPU | G4 512-ray 真实 P1 profile 覆盖 1/2/4/6；2 worker 仅 1.06×，4/6更慢；GPU未测 | 1 worker 固定；GPU `NOT_TESTED` | `G4_COMPUTE_MEASURED.md` |
| PRE4-08 | 预注册冻结 | 6 个 prereg/config 哈希与 freeze manifest 匹配 | PASS | `G4_FREEZE_HASHES.json` |
| P4-V0a | NA、方向、权重、非法源配置 | NA 约束与方向归一测试通过；负/零/非有限输入拒绝；权重总和误差 ≤1e-12 | PASS | `tests/unit/test_pump976_source.py` |
| P4-V0b | 源概率测度 | 近场 `r²/R²` 与角分布的 uniformized CDF KS D ≤1.63/√N；18 行分布摘要完整 | PASS | `run/source_distribution_summary.csv` |
| P4-V1a | P0 vs 独立标量参考 | 8,192 条 NA=0.22 rays；最大位置差 0.0 mm，方向差 0 | PASS | `run/optical_crosscheck.json` |
| P4-V1b | 口径/坏样本/权重 | 口径、目标区外权重分别分类；失败仍留在 1.0 source denominator；闭合误差 ≤1e-10 | PASS | `run/ray_balance.csv`、unit tests |
| P4-V2 | P1 真实追迹 | Optiland 0.6.3；低角度位置和 r80 交叉门通过。高 NA P1 与 P0 不一致，报告为模型差异 | QUALIFIED | `run/optical_crosscheck.json` |
| P4-V3 | 目标密度/权重守恒 | 8 组 P0/P1、NA=0.05/0.22 账本；所有 balance residual 为 0 | PASS | `run/target_plane_density.npz`、`run/ray_balance.csv` |
| P4-V4 | ray-count 稳定性 | 2k/8k/32k × 3 seeds × 两设计；8k→32k 中位 r80 变化各约 0.389%；95% t intervals 已保存 | PASS | `run/ray_count_convergence.csv`、summary JSON |
| P4-V5a | OAT/公差 | 30 OAT rows；100 precheck +100 holdout assemblies/design；完整 400 rows、paired seeds | PASS | `run/oat.csv`、`run/tolerance_samples.csv`、`split_manifest.json` |
| P4-V5b | 候选收益 | P0 holdout r90 配对差 CI 排除 0；但 P1 full NA 行为不同，不能据此声称整体 optical improvement | `NO_SUPPORTED_IMPROVEMENT` overall | `run/bootstrap_summary.json`、`run/design_comparison.csv` |
| P4-V6a | AppTest 与 watchdog | 18 UI tests；独立 JobService 睡眠负向控制终止子进程并记录 TIMEOUT | PASS | 全量 JUnit、`tests/integration/test_g4_jobs.py` |
| P4-V6b | 全量 pytest | 449 passed /0 failed /0 errors /0 skipped，exit 0；JUnit 134.520 s，外层 136.938 s | PASS | `artifacts/g4/tests/g4_full_*` |
| P4-V6c | CLI/UI/server | G3 G3-demo 1 assembly真实 CLI exit0；G4 reduced CLI exit0但run status PARTIAL；Streamlit server smoke health ok；AppTest另行验证执行 | PASS_WITH_SCOPE | `artifacts/g4/tests/*cli*`, `streamlit_serve.json` |
| P4-V7 | 外部实验 | 无授权/标定数据 | `NOT_AVAILABLE / NOT_RUN` | `run/run_status.json` |
| P4-V8 | ZIP 内容与独立复验 | 282 members；280 manifest files +2 self-reference exceptions；content/extract/replay/tamper/same-env/cross-env Python 3.11 & 3.14 均 PASS；ZIP_STORED | PASS | `_AUDIT/20261020_133555_G4_ec3e2813_0e48/` |
| COMPUTE | 父进程 watchdog | JobService 0.25 s sleep negative control真实终止进程树；正式 G4 外层 CLI 13.798 s | PASS | `tests/integration/test_g4_jobs.py`, CLI log |

工程路径完成，物理主张受限于 P1 假设镜片与缺少实测。没有把数学一致性写成实验认证。
