# G4 计算预算（结果前冻结）

**版本**：1.0  **冻结日期**：2026-10-20  **硬上限**：任一 G4 计算阶段 300 s；单子任务 180 s。  
这是预算，不是实测。测得值写入单独的 `G4_COMPUTE_MEASURED.md`。

## 环境起点

`artifacts/g4/pre/environment.json`：Python 3.14.3、Ryzen 5 4600G 6C/12T、31.41 GB RAM（快照可用 13.66 GB）、GTX 1660 SUPER 6 GB。torch 未安装，因此 GPU/CUDA 不在本轮启用。CPU 快照负载 37.1%；内存与负载是采样瞬间，不是恒定值。

## 预算分配

| 子任务 | 预注册规模 | 硬预算 | 当前资源策略 |
|---|---:|---:|---|
| G4 source/profile probe | 3 组几何条件 × 512 rays × 1/2/4/6 workers | 120 s | 先测进程启动/IPC；最终并行数以实测为准 |
| P0 source convergence | 2k/8k/32k × 3 seeds × 2 分布 | 180 s | NumPy 向量化，单进程起步 |
| P0 nominal + OAT | 2 designs × 4,096 rays；OAT ≤30 条 × 4,096 | 180 s | 复用随机源和几何数组，不逐 ray Python 循环 |
| P0 tolerance precheck | 100 assemblies × 2 designs × 2,048 rays | 180 s | chunk=10 assemblies，逐 chunk checkpoint |
| P0 independent holdout | 100 assemblies × 2 designs × 2,048 rays | 180 s | 独立 seed，只评估固定设计，不返调 |
| P1 Optiland cross-check | 3 geometry conditions × 2,048 rays + 两个候选各 4,096 rays | 180 s | 先实际 profile；默认 1 worker，不预设加速 |
| Full G4 analysis | source + P0 + OAT + tolerance + report | 300 s | CLI/JobService 父进程 timeout；超时立即保存 checkpoint |
| Full pytest / app checks | 依实测 | 300 s 规划上限，不作旧测试验收替代 | 本地独立全量回归，保留原始证据 |

## 执行规则

1. 小型性能 probe 在最终分析之前运行，记录每个条件耗时、吞吐、peak RSS、workers 与 BLAS 环境变量。
2. 基于至少 3 种工况的中位/P90/P95 耗时和 ray count 线性外推，确认最终任务规模仍在 300 s 内；否则只可在运行前登记新规模版本，不可删掉失败样本。
3. 每 chunk checkpoint 绑定 config hash、code commit、seed、索引范围和模型版本；恢复不得重复计数。
4. JobService/父进程通过 timeout 杀整个子进程树；负向控制使用短 timeout 中止睡眠子进程，预期状态 `TIMEOUT`。
5. G3 曾发生 600 s 预算被超 3.16 倍；本轮任何任务不得只在事后解释超时。
6. G4 workload 的 1/2/4/6 worker profile 尚未完成时，记 `NOT_TESTED`，不沿用 G0/G1 或 G3 的并行结论。
