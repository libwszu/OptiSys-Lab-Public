# S6 Amendment 02：总科学预算的运行时硬截止

**登记时间：** 2026-10-21 03:18 America/New_York（2026-10-21T07:18Z）  
**原始冻结与 Amendment 01：** 保持不变。  
**修改前状态：** S6-C pilot 已通过；正式 holdout 尚未开始，holdout 样本和 seed 已冻结。  
**修改原因：** 将已冻结的 1,500 s 总科学预算落到实际父进程 watchdog，避免只有限制每个子任务却没有全局截止。

## 实测前序墙钟和预算切分

`runs/20261021_024715_S6_P1/compute_measured_preholdout.json` 累计了本轮已执行的 S6-A 两次尝试、1/2/4-worker profile 两次尝试、S6-B 扫描和 C pilot：**63.2557207 s**。单独图像重绘、pytest 与作品集验收属于工程/验证开销，不计入科学 MC wall。

保持总科学预算 **1,500 s**。正式 C holdout 父进程 hard cap 冻结为 **1,200 s**；按当前实测前序 wall 留有 **236.7442793 s** 预算余量。holdout 中最多 **1,170 s** 用于 assembly worker chunks，另预留 **30 s** 用于 bootstrap、报告和 checkpoint 收口。每个 assembly chunk 仍最多 32 个 assembly，父进程等待上限仍为 **120 s**；两者中先到的截止生效。外层 watchdog 超时会终止整个 worker 进程树并将未完成样本保留为 `TIMEOUT/CANCELLED/NOT_STARTED`，不得静默重跑。显式 `--resume` 只能验证 hash 后跳过已 checkpoint 的 assembly；原超时 assembly 不会重试。

## 科学影响

无变化：4 个情景、每情景 200 assemblies、每 design/assembly 1,024 rays、配对 source、误差 sigma、bootstrap 单位与 2,000 次重复、阈值和主要 estimand 全部不变。该 amendment 只补足原预算的执行截止，正式结果在这份 amendment 与新代码哈希冻结之后才开始。
