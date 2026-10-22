# G4 算力与性能

硬件快照与原始环境见 `test_evidence/environment.json`、`g4/G4_COMPUTE_MEASURED.md`。

- Ryzen 5 4600G 6C/12T，31.41 GB RAM；GTX 1660 SUPER 6 GB 可见，但 PyTorch/CUDA workload 未测。
- 真实 Optiland 512-ray profile 测试 1/2/4/6 workers；2 workers 约 1.06×，未到 1.3×门限，正式只用单进程。
- 正式 run：外层 CLI 13.798 s；run 内部 10.1323 s；峰值 RSS 405.08 MB；G4 阶段总预算 300 s、子任务预算 180 s。
- 计算结果仅适用于此机器、依赖和已声明样本。GPU 为 `NOT_TESTED`，远端 CI 为 `NOT_RUN`。
- 负向 timeout 控制真实终止了睡眠子进程并记录 TIMEOUT；完整日志在全量 JUnit。
