# 已知问题与失败

- P1 与 P0 full-NA 模型差异明显：假设 N-BK7 singlets 下约 32% weighted rays 落在假设的 1 mm target 外；这是本轮最重要的负结果。
- P1 低角度 cross-check 通过，但不构成 full-NA 真实镜片验证。
- P1 adapter 尚无偏心/倾斜坐标断点；misalignment/tolerance 只在 P0 表示。
- 没有测得的镜片料号、fiber datasheet、pump power、晶体尺寸、外部光斑图或辐射标定。
- P0 holdout 的 candidate r90 更小，但 P1 高角度预测和 aperture package 不支持外推为真实系统改善；overall claim 保持 `NO_SUPPORTED_IMPROVEMENT`。
- 演示视频 `NOT_DELIVERED`；远端 CI `NOT_RUN`；GPU/CUDA `NOT_TESTED`。
- G2 的 HC3/数据泄漏/模型选择偏离保持 `QUALIFIED_ONLY`，没有在 G4 中重跑或改写。
- 旧 G3 有 141.655 vs 145.545 s 测时冲突；JUnit/stdout suite duration 是 141.655/141.66，外层 145.545 仍 `HISTORICAL_DURATION_NOT_ADJUDICATED`。
