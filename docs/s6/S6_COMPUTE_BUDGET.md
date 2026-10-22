# S6 计算预算与调度（初始冻结方案）

## 现场资源

初查：Windows PowerShell；CPython 3.14.3 已安装，`py` 启动器可用；可见 31.41 GiB RAM 和 12 逻辑处理器；Optiland 0.6.3 可用。GPU 设备信息未确认，GPU 不用于 S6。正式 profile 前记录可用 RAM、CPU 名称、依赖和 BLAS 线程设置。

## 预算上限

- 本轮 S6 科学计算 wall budget：1,500 s；README/install/test/ZIP 封包等工程验收墙钟单独实测，不抵扣科学预算。
- 每个 profile / assembly chunk / scan 子任务父进程 hard timeout 120 s；若必要任务超时，记录状态并停止该块，不能静默延长。
- 峰值 process-tree RSS 软门：`min(8 GiB, profile 启动可用 RAM 的 50%)`。父进程负责 watchdog 与整个进程树的退出核对。
- NumPy/BLAS 线程变量 `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS` 均设为 1。
- profile 测得整体 4-worker speedup 未达到 1.3×或 RSS 超门时，正式计算采用单 worker。

## 在正式 holdout 前执行的 profile

非共轴真实 P1 A 参考链冷启动、warmup；1/2/4 workers 分别测试 256/512/2048 rays，保留三次 warm repeat，计算 wall p50/p95、throughput、启动成本、进程树 RSS、任务输入和输出 hash、串/并行结果一致性。任何数值结果只作为算力 profile，不用于选择候选。

## 初始可行样本计划（可由一次有记录 amendment 缩小）

- correctness/throughput pilot：32 assembly × 256 rays/design；独立 pilot seed，仅看程序诊断与吞吐。
- 正式 holdout：4 个公差情景 × 200 assemblies/scenario × 1,024 rays/design × 2 designs，共 1,638,400 ray-design traces；情景为 zero、0.5× nominal、nominal、2× nominal。
- 每个 assembly 配对两设计，checkpoint 粒度 assembly；每 chunk 最多 32 assemblies；至少 2,000 次 assembly-cluster paired bootstrap。
- 固定边界扫描：两设计各 8 个焦面网格和 5 个 L2 位置网格；按数据前固定 rays；正式 profile 后确认每项可在 120 s 内完成。

profile 后用实测吞吐与其 p95 时间估算每块墙钟、合计 science wall 和内存。若超 1,500 s 或单块超 120 s，必须先写 `S6_AMENDMENT_01.md`，说明原配额、新配额、精度限制和对状态的影响，再冻结新预算 hash；不得读取正式候选收益后调整。
