# G4 算力实测（阶段性）

所有数值为本机实际采样；预算仍以冻结的 `G4_COMPUTE_BUDGET.md` 为准。

## 环境快照

- Windows 11 build 26100；Python 3.14.3；NumPy 2.5.4；SciPy 1.18.1；Optiland 0.6.3。
- AMD Ryzen 5 4600G，6 physical / 12 logical cores；31.41 GB 可见 RAM。初始快照时 13.66 GB 可用，CPU 利用率瞬时读数 37.1%。
- NVIDIA GeForce GTX 1660 SUPER，6,144 MB；当时已用 1,449 MB；`nvidia-smi` 可读，但 PyTorch 未安装，CUDA 工作负载 `NOT_TESTED`。
- OMP/OPENBLAS/MKL/NUMEXPR 线程变量在基线采样时均为 UNSET；专用 profile 子进程固定为 1。
- 环境原始记录：`artifacts/g4/pre/environment.json`；profile 环境和线程记录：`artifacts/g4/pre/compute_profile.json`。

## 实际两透镜 P1 workload 并行剖析

Optiland 0.6.3，N-BK7 假设 singlet L1/L2，均为 512 条真实 `RealRays`；18 个调用覆盖 baseline/candidate/小口径+轴向偏差工况、NA=0.05/0.22、3 个 source seeds。profile 只记录时延/RSS，舍弃几何性能汇总。父进程计时包含 worker 创建和初始化开销。

| worker 数 | trace 调用 | 总 rays | 墙钟 [s] | rays/s | 峰值进程树 RSS [MB] |
|---:|---:|---:|---:|---:|---:|
| 1 | 18 | 9,216 | 7.639 | 1,206.52 | 370.4 |
| 2 | 18 | 9,216 | 7.215 | 1,277.30 | 695.3 |
| 4 | 18 | 9,216 | 7.405 | 1,244.64 | 1,345.9 |
| 6 | 18 | 9,216 | 10.265 | 897.80 | 1,996.4 |

结论仅针对本次真实 Optiland 双透镜负载：2 worker 仅比 1 worker 快 1.06×，低于事先采用的 1.3×并行扩展门槛；4/6 worker 也无实质收益，且 RSS 随 worker 增长。正式阶段固定 1 worker，不宣称并行提速或 GPU 支持。18 次均返回状态，没有进程异常。

## 光学后端探针记录

- 坐标原点错误在首轮 profile 中被发现：Optiland 把首片前顶点定义为局部 z=0，原适配器未平移从全局 z=0 发出的光线。修正前 probe 保留为失败诊断，不参与任何 G4 物理结论。
- 修正后 P1 在 NA=0.05 的 4,096 条共同射线上完整到达目标区；P0/P1 `r80` 相对差 baseline 0.193%、candidate 0.265%，80%位置差分位数分别 0.00668/0.00428 mm，满足事前冻结的低角度判据。
- 修正后 NA=0.22 探针显示 P1 假设 singlet 的接收区通光与 P0 理想薄透镜不同；这些数字会在正式 G4 run 重算并列为模型差异，不据此改变冻结配置或阈值。
- 冷启动 trace 的首个调用耗时约 5.0 s；同一进程 warm trace 约 0.02–0.03 s。正式预算涵盖子进程/首次 Optiland 初始化。

证据：`artifacts/g4/pre/optiland_g4_smoke.json`（修正前诊断）、`optiland_g4_crosscheck_coordinatefix.json`、`compute_profile.json`。

## 既有平台扩展检查

`artifacts/g4/pre/commands.json` 记录真实 CLI validate exit 0 与既有接口定向 pytest：73 passed / 0 failed / 0 errors / 0 skipped，pytest 自报 93.70 s，外层含进程启动墙钟 97.256 s。测试覆盖 Optiland G2 trace、JobService、ReportService、CLI 与五页 AppTest；本结果不代替最终全量 pytest。

## 注册规模 G4 run 与本轮回归

- 正式 run：`20261020_133555_G4_ec3e2813_0e48`；4,096 nominal rays；2k/8k/32k × 3 seeds source convergence；30 个 OAT 点；100 装配 precheck + 100 独立 paired holdout × 2 designs × 2,048 rays = 400 完整样本行。
- G4 运行器内部墙钟 **10.1323 s**，峰值 RSS **405.08 MB**，1 worker。外层 CLI 含 Python 启动与落盘墙钟 **13.798 s**；exit 0。各阶段：source convergence 0.5168 s、nominal P0/P1 1.2872 s、OAT 0.1432 s、公差 1.4692 s、paired comparison/bootstrap 0.0241 s。report rendering 计入外层时间，不计入 run 的 compute wall 字段。
- 8k→32k 中位 r80 相对变化：baseline 0.3893%，candidate 0.3893%；均低于冻结 5% 门限。每一 ray count 每设计 3 个 seed 的 95% t 区间保存在 `run/ray_count_convergence_summary.json`。
- 全量 pytest 最终记录：**449 passed / 0 failed / 0 errors / 0 skipped**；JUnit suite time 134.520 s，外层墙钟 136.938 s，exit 0。原 G3 425 项未删减、未 skip/xfail；差额为本轮 G4 新测试。日志在 `artifacts/g4/tests/g4_full_*`。
- `streamlit run app/main.py` server smoke：Streamlit 1.66.0，health endpoint `/_stcore/health` 为 HTTP 200 / `ok`，根页 HTTP 200 / 6,467 bytes，启动 2.21 s，进程干净退出。此 HTTP smoke 不覆盖 WebSocket 页面执行；六页 AppTest 在全量 pytest 中通过。
- 真实 G3 小工况 CLI smoke：1 assembly / 63 rows / 27.77 s / exit 0，写入 `runs/_derived/`，不触碰冻结 G3 run。真实 G4 reduced CLI smoke：512 rays / 2 assemblies / 10.97 s / exit 0，run 状态正确为 `PARTIAL`。
- G4 ReportService 派生报告：3.462 s；报告生成前后正式 run 整树摘要相同，冻结 run 未改写。JobService G4 真实 CLI 子进程与睡眠超时负向控制均纳入全量 pytest。
- 远端 CI：`NOT_RUN`。CUDA/GPU workload：`NOT_TESTED`。视频：`NOT_DELIVERED`。
