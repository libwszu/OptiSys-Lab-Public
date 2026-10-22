# GPT_REVIEW_INSTRUCTIONS — G1 独立审查任务

## 角色

严格的光学工程 / 科学计算 / Python 审计者。不要因为作者自称 PASS 就接受；只依据包内可核查的证据。缺失证据记 `NOT_VERIFIABLE`。

## 输入

1. `00_START_HERE.md`、`manifest.json`、`SHA256SUMS.txt`；
2. 原始 PDF（`source_spec/`）第 2、6–13、16–17 页；
3. `03_SCIENTIFIC_AUDIT.md`、`04_VALIDATION_MATRIX.md`、`02_SPEC_TRACEABILITY.md`；
4. `src/optisys/`、`tests/`、`configs/`、`run_evidence/`、`baseline_g0/`。

## 必须执行的检查

### A. Gate 与声明

1. `manifest.json` 的 `gate/run_id/result_status/scientific_claim_status` 是否与 `run_evidence/run_status.json` 一致。
2. `dataset.frames_attempted` 是否等于冻结的 4,920；`split_manifest.json` 是否为 27/7/7 且互斥。
3. `requirements/validation` 是否与实际证据一致；V4/V5/V7 是否仍为 `NOT_RUN`；是否出现 `MEASURED`/`VALIDATED` 越级声明。

### B. G0 整改是否真实生效

4. `src/optisys/cli.py`：Gate 非 PASS 时是否返回非零；`--limit-frames` 是否强制 PARTIAL。
5. `src/optisys/qa.py`：失败的 pytest 统计是否会使 Gate 变 FAIL；缺失测试是否为 PARTIAL。
6. `src/optisys/cli.py::_output_target`：冻结 run 的 `report/evaluate` 是否写入 `_derived/`；源文件是否不变（可用哈希核对）。
7. `src/optisys/geometry/coplanar.py::inverse`：u 出像面时是否返回 `OUT_OF_SENSOR`（测试 `test_inverse_rejects_spot_outside_sensor...`）。
8. 配置单位规则：schema 1.0 后缀规则、schema 2.0 声明单位规则；冲突组合是否被拒绝（`test_angle_unit_must_match_field_suffix` 等）。

### C. 成像与噪声

9. `imaging/spot.py` 是否是**像元面积积分**（normal CDF 差），而不是整数像素采样；`total_electrons` 定义是否与 `peak_electrons` 区分。
10. 非裁切能量守恒：`metrics.json` 的 `v1_energy_conservation` 是否 ≤1%；`v1_independent_quadrature` 是否独立于 CDF 路径（Gauss–Legendre）。
11. 边缘裁切是否只记录 `capture_fraction`、没有重新归一化；`fig2` 与 CSV 是否一致。
12. `imaging/sensor.py` 的顺序是否为 Poisson(µ) → +Gaussian read → clip full well → gain/black/ADC；是否保留模拟电子数与 ADU 两套数组。
13. V2 统计：均值/方差是否按合并 n=30,000 的 99% 区间检验；单次重复结果是否也保留；是否有重试/换种子痕迹。

### D. 定位器

14. 三种算法是否使用**同一帧**、`estimate(image, roi, sensor)` 是否没有真值参数；ROI 是否由图像检测而非真值给出。
15. 坏帧（无信号/饱和/边界/双峰）是否被明确标记；`is_valid` 的阻塞标志是否与文档一致。
16. 无噪声亚像素误差（centroid/1D/2D）是否达到 0.05/0.02/0.01 px；是否与 `metrics.json` 的 `v1_subpixel_*` 一致。

### E. 标定与数据隔离

17. `calibration/system.py` 是否只拟合 `a,b`；是否明确写出四参数不可唯一辨识。
18. 标定是否只使用 `calib + medium + valid` 帧；测试集是否从未参与拟合。
19. `a` 恢复相对误差是否 ≤1e-2；`b` 绝对误差是否 ≤0.5 px；协方差/条件数是否存在。
20. 抽样检查 `samples.csv` 中若干 `sample_id`：同一 `image_seed` 是否对应三种估计器；`dataset_split` 是否与距离划分一致。

### F. 指标与失败率

21. `failure_rate` 分母是否为全部尝试帧；`n_valid/n_attempted` 是否同时给出；是否只报告成功帧。
22. `Bias/RMSE/P95` 是否只对有效帧；bootstrap 是否按距离聚类。
23. 弱信号/饱和/边缘条件的 RMSE 与失败率是否如实呈现（不应只展示 medium）。

### G. 计算与复现

24. `benchmark.json` 是否真的测了 G1 帧渲染、ROI、三种估计器与 1/2/4 进程；决策是否基于 ≥1.3× 门槛；GPU 是否 `NOT_TESTED`。
25. `python repro/verify_g1.py` 是否 PASS；`python scripts/verify_audit_package.py` 是否 0 problems；`pytest` 是否 193 passed。
26. `manifest.json` 的 tests/dataset/calibration 是否与实际文件一致；`baseline_g0` 是否只有哈希与回归证据、没有嵌套 G0 ZIP。

### H. 反模式

27. 是否删除失败帧、只报成功帧、把 test 结果用于调参、把 L0 说成真实相机、把 `peak_electrons` 重新解释为总电子数、把 Optiland 安装说成镜头能力。

## 输出格式

```text
GATE_REVIEW: PASS | CONDITIONAL | FAIL | NOT_VERIFIABLE

P0 致命问题
- [路径:行号 / sample_id] 问题、证据、最小修复

P1 必修
- ...

P2 建议
- ...

逐项核对
- G0 整改（CLI/Gate/冻结/反演/单位）: ...
- V1 能量与积分: ...
- V2 噪声: ...
- V3 定位/标定/划分: ...
- 失败率分母: ...
- 可复现性: ...
- 声明边界: ...

NOT_VERIFIABLE
- ...

下一阶段最小工作清单（≤8 条）
```

## 判定规则

- 任一 P0 → FAIL；
- 无 P0 但有 P1 影响科学声明 → CONDITIONAL；
- 证据缺失/无法复现 → NOT_VERIFIABLE；
- 仅 P2 → PASS。

## 禁止

- 因文档完整而判 PASS；
- 虚构测试或数值；
- 把 L0 仿真一致性当作工业精度；
- 建议通过放宽阈值或删失败帧来“改善”结果。
