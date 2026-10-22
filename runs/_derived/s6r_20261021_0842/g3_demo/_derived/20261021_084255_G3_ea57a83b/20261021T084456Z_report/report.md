# OptiSys-Lab G3 工程报告

- run: `20261021_084255_G3_ea57a83b`
- gate: `G3` · schema `3.0`
- model level: `UNKNOWN`
- evidence level: `SIMULATED`
- status: `PASS` · scientific: `DEMO_ONLY_NOT_A_G2_CONFIRMATION`
- config sha256: `UNKNOWN`

> **科学状态 QUALIFIED_ONLY — 不是未受限的 PASS**
>
> 历史执行为 `PASS_RECORDED`；预注册合规性 `FAIL`；数值核验 `PASS`。
>
> 必须同屏携带：
> - `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED`
> - `G2_FINAL_PANEL_DEVIATION`
> - `G2_FINAL_DISTANCE_LEAK_INTO_DEVELOPMENT`
> - `CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED`

## 精度指标（全尝试帧口径）

| 候选 | 尝试 | 有效 | 失败率 | RMSE (mm) | P95 (mm) | bias (mm) |
|---|---|---|---|---|---|---|
| baseline | 21 | 11 | 47.62% | 1.6383 | 3.2586 | 1.3490 |
| nominal | 21 | 12 | 42.86% | 12.0437 | 18.3894 | 9.5725 |
| robust | 21 | 7 | 66.67% | 10.1564 | 11.1609 | -10.1238 |

## 图件

- `figures/01_optical_layout.png` — SHA-256 `6e905c4ef00a71bee8d826c2d1a04fb9a0c6cce4fa1f04f1b954ed9eb8c44ff0`
- `figures/02_error_vs_distance.png` — SHA-256 `d0c9e8a0da116ed7a50daf77c155224580f3b9b43d57d4debc9111cf5fb1283d`
- `figures/03_candidate_comparison.png` — SHA-256 `89acca17664b90c62b4562cf6047e289e38bf8e20f21960ec64b8a9127a066eb`
- `figures/04_kernel_support.png` — SHA-256 `f6df05b127f510c0e384e4a6574db25e482de1178e95dcb101f6b1f674c62a91`

## 边界

- 无实测数据；证据层级上限 `SIMULATED` / `CROSS_CHECKED`。
- G4（976 nm）是独立模拟案例；本 G2 run 不包含 G4 结果。
- 主面板仅 medium 条件，不得跨条件外推。
- Strategy A/B 不可直接相减；配对 A/B bootstrap 为 `NOT_RUN`。
