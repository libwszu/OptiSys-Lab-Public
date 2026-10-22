# PDF / G4 任务书追溯

| 要求 | 实现 | 审计证据 |
|---|---|---|
| PDF R11：第二个 976 nm 泵浦工程案例 | schema 4.0 configs、fiber source、P0 beamline、P1 Optiland、target metrics | `configs/pump976_g4_*.yaml`; `src/optisys/{sources,optics,evaluation,gates}/`; `run/` |
| G4-A：纤芯均匀面积与 NA 概率测度 | `r=R*sqrt(U)`；均匀立体角 `cos(theta)` uniform；edge-biased sensitivity `F(q)=q^3` | `run/source_distribution.json`, `source_distribution_summary.csv`, `source_samples.csv/.npz` |
| G4-B：单位、光路、孔径、目标接收区 | mm/rad/nm contracts、P0 vector/scalar、P1 Optiland、source-denominated ledger | `run/optics_model.json`, `raytrace_reference.csv`, `ray_balance.csv`, `target_plane_metrics.csv`, density NPZ |
| G4-C：OAT、公差、paired holdout | 30 OAT rows; 100+100 assemblies/design, common random numbers, 400 complete rows | `run/oat.csv`, `tolerance_samples.csv`, `split_manifest.json`, `bootstrap_summary.json` |
| G4-D：实验对比条件性 | 无授权/标定数据，`NOT_AVAILABLE / NOT_RUN` | `run/run_status.json`, `G4_OPEN_ISSUES.md` |
| G4-E：复用 CLI/UI/report/jobs | CLI `pump976`, JobService timeout, Streamlit page F, ReportService schema 4 | `src/optisys/cli.py`, `app/pages/page_f_pump976.py`, `test_evidence/` |
| G4-F：独立审计与审计 ZIP | 固定元数据 ZIP_STORED、逐文件哈希、解压重算、篡改拒绝、同/跨环境重建 | `manifest.json`, `SHA256SUMS.txt`, `repro/verify_g4.py`, 外部 `AUDIT_VERIFY_LOG.txt` |
| 旧科学状态持续可见 | `QUALIFIED_ONLY` 保留在旧页面/报告；G4 报告明确继承状态 | `baseline_g3/`, HTML report, status JSON |

原 PDF 第 14 页 §11 的范围优先于 G3 后续建议；SPEC 差异和裁决见 `g4/G4_BASELINE_DISCREPANCIES.md`。
