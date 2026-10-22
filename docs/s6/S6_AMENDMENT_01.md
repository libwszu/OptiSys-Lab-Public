# S6 Amendment 01：按非共轴真实负载冻结计算规模

**登记时间：** 2026-10-21 03:01 America/New_York（2026-10-21T07:01Z）  
**原始冻结：** `S6_FREEZE_HASHES.json`（不改写）  
**修改前状态：** C 为计划样本，尚未执行 C pilot 或任何 assembly holdout；未查看装配级候选收益。  
**修改原因：** S6-A 双参考链已通过；S6 非共轴负载 profile 已完成，现有性能足以执行预注册的 200×1,024 方案。

## 实测 profile

Profile 使用 CPython 3.14.3、Windows `spawn`、S6 局部坐标真实 P1 追迹、L1/L2 均施加非零 decenter/tilt/axial 位姿、每尺寸 3 次 warm repeat。

| workers | 256 rays p50/p95 | 512 rays p50/p95 | 2,048 rays p50/p95 | 2,048 rays/s p50 | process-tree RSS 峰值 | 首批含启动 wall |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.0807 / 0.0836 s | 0.1548 / 0.1574 s | 0.6045 / 0.6210 s | 3,388 | 112.6 MiB | 3.545 s |
| 2 | 0.0458 / 0.0510 s | 0.0843 / 0.0862 s | 0.3456 / 0.3629 s | 5,926 | 150.3 MiB | 2.346 s |
| 4 | 0.0251 / 0.0351 s | 0.0478 / 0.0681 s | 0.1782 / 0.1919 s | 11,494 | 230.3 MiB | 1.840 s |

4-worker 对 1-worker 的 2,048-ray warm speedup 为 `3.3927×`；三组 size 跨 worker 输出 hash 一致。profile 开始可用 RAM 16,443 MiB；RSS 软门 `8,192 MiB`；4 worker 实测峰值约 230 MiB。GPU 检出 NVIDIA GeForce GTX 1660 SUPER，但未运行 GPU workload，仍为 `DETECTED_NOT_TESTED`。外部 profile 命令墙钟 8.515 s。所有实际原始记录在 `runs/20261021_024715_S6_P1/compute_profile/compute_profile.json`。

## 正式配额和调度（本 amendment 后冻结）

- C holdout 保持原方案：4 个情景（zero、0.5×、nominal、2× nominal），每情景 200 个 assembly、每 assembly/设计 1,024 rays、两设计配对，共 `1,638,400 ray-design traces`。无效或失败 assembly 不重抽。
- 结果前执行 pilot：32 assemblies × 256 rays/design。只检查参数生效、账本、checkpoint、重复行和吞吐；不据其候选差异改条件或样本量。
- 正式 worker 数定为 4；Windows 使用 `spawn`，BLAS 线程全设 1；主 holdout 每 chunk 32 assemblies（每块至多 65,536 ray-design traces），每子任务硬超时 120 s。
- 用 2,048-ray measured p95 归一化，正式 C 追迹预计 `153.5 s`；加 50% I/O、调度和方差余量为 `230 s`。边界扫描 86,016 ray-design traces 的 p95 速率粗估 `8.1 s`；含 A、profile、pilot、bootstrap 和日志的本轮科学总墙钟估计约 `300 s`，仍低于原冻结的 1,500 s cap。以上为估计值，不是运行结果。
- `min(8 GiB, startup-available-RAM×50%)` 当前为 8 GiB。实际测量超出估计仍不能突破 1,500 s；保留超时/中止状态并报告 PARTIAL。

## 影响与状态

样本量和验收阈值没有变更，原 `S6_ACCEPTANCE_CRITERIA.md` 不变。本 amendment 只把 profile 允许后才可定的 worker 与具体 holdout配额冻结下来。依据该 profile 可继续 pilot、B 与 C；S6-C 的最终统计仍须等 pilot 通过后才开始，且不得复用 S5 seed 976053。原冻结文件哈希保持原样，本文件及 `compute_plan.json` 的哈希记录在 `S6_AMENDMENT_01_HASHES.json`。
