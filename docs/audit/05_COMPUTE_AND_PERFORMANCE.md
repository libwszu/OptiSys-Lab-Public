# 05_COMPUTE_AND_PERFORMANCE

所有数字来自 run `20261019_130948_G0_78fa364f`（同一代码的两次运行耗时可有 10–20% 波动；几何结论不受影响） 的 `benchmark.json`、`environment.json`、`compute_plan.json`。没有一项是估计值；无法获取的项标 `UNKNOWN` 或 `NOT_TESTED`。

## 1. 实测硬件与水印

| 项 | 实测值 |
|---|---|
| 平台 | Windows 11，build 10.0.26100，AMD64 |
| CPU | AMD Ryzen 5 4600G with Radeon Graphics |
| 物理核 / 逻辑线程 | 6 / 12 |
| 频率 | 3701 MHz（当前=最大） |
| 内存 | 31.41 GB 总，15.56 GB 可用（启动时），占用 50.5% |
| GPU | NVIDIA GeForce GTX 1660 SUPER，6144 MB，驱动 566.07，compute capability 7.5 |
| 显存占用（快照） | 1797 MB |
| CUDA（本项目可用性） | **不可用**：torch 未安装 → `cuda_available = NOT_INSTALLED` |
| 磁盘 | `E:` 剩余 216.77 GB / 465.51 GB |
| Python | CPython 3.14.3（venv） |
| 关键依赖 | numpy 2.5.4、scipy 1.18.1、matplotlib 3.11.2、pandas 3.0.6、pytest 9.1.1、optiland 0.6.3 |

注意：检测到 GTX 1660 SUPER **不等于** CUDA 可用；本项目没有安装 PyTorch，因此没有任何 GPU 运行证据。

## 2. 工作负载基准

线程环境在基准开始前固定为 1：

```text
OMP_NUM_THREADS=1  OPENBLAS_NUM_THREADS=1  MKL_NUM_THREADS=1  NUMEXPR_NUM_THREADS=1
```

| 负载 | 内容 | 中位耗时 | 吞吐 | 备注 |
|---|---|---|---|---|
| `analytic_forward_41x3` | 3×41 点向量化前向（实际 G0 计算） | **0.161 ms** | 约 7.6e5 点/秒 | 单次调用微秒级，进程池无意义 |
| `reference_vector_chain_41x3` | 3×41 点独立 3×3 求交 + 3×4 投影 | **0.315 ms** | 约 3.9e5 点/秒 | 仅用于验证，约 2× 慢于解析 |
| `mc_proxy_200000` | 200k 随机深度向量化前向 | **7.545 ms** | 约 2.7e7 点/秒 | 仅计时代理，不是公差结果 |
| 观测 RSS 峰值 | 进程 RSS 采样最大值 | **289.5 MB** | — | 含 numpy/scipy/matplotlib 导入 |

## 3. 进程并行测试（1/2/4/6）

负载：200k 点，切成 8 块，每档 3 次重复，Windows `spawn`。

| workers | 模式 | 中位耗时 | 相对 1 worker | 池启动 |
|---|---|---|---|---|
| 1 | 进程内分块（无 IPC） | **3.22 ms** | 1.00× | 0 |
| 2 | spawn 进程池 | 6.03 ms | 0.53× | 2.28 s |
| 4 | spawn 进程池 | 5.40 ms | 0.60× | 2.41 s |
| 6 | spawn 进程池 | 6.33 ms | 0.51× | 2.83 s |

**口径说明（重要）**：1-worker 基线在进程内顺序执行 8 个块，不支付序列化成本；2/4/6 则需把 8 个数组块 pickle 到子进程。这个比较回答的是“是否值得把现有向量化代码改成分进程”，而不是“纯并行效率”。结论仍然明确：**对该负载，多进程净亏**，因此选择单进程。

一致性检查：四档的 `u_sum` 完全相同（178893823.73341522），`visible=200000`，说明并行路径没有改变数值结果。

## 4. 一个值得记录的观察

单次 200k 调用耗时 7.545 ms，而 8×25k 分块在进程内只需 3.22 ms（约 2.3× 更快）。这不是并行收益，而是缓存/内存带宽效应。G2 的公差引擎将按分块实现，而不是一次性传大数组。

该观察尚未做 `perf`/硬件计数器级 profile，标为待深化（OI-011）。

## 5. GPU 决策

| 项 | 状态 |
|---|---|
| GPU 是否用于本 Gate | **否** |
| 原因 | G0 无张量/光学追迹负载；torch 未安装；无同输入 CPU/GPU 一致性证据 |
| 是否测试过 GPU | **NOT_TESTED** |
| 显存余量假设 | 无（未使用） |
| 回退策略 | 不适用 |

没有“GPU 空闲所以计算没发生”这类推断，也没有任何 GPU 加速声明。

## 6. 内存与预算

| 项 | 值 |
|---|---|
| RAM 预算 | 23.56 GB（总内存 75%） |
| G0 峰值 | 289.5 MB（单进程 RSS 观测值） |
| Monte Carlo 单样本上限（未经批准） | 2,000 |
| 单次运行墙钟上限 | 900 s |
| 本 run 实际墙钟 | **约 17 s**（13:09:48 → 13:10:05 UTC，含环境探测、基准、比较、绘图、报告） |

## 7. 恢复与缓存策略

| 项 | G0 状态 |
|---|---|
| checkpoint | 不需要：全部计算 < 1 s；`checkpoints/` 目录为空 |
| 断点续算 | 未实现（G2 需要） |
| 缓存键 | 已定义：配置哈希 + 模型版本 + 种子序列 + 数值精度；G0 无缓存 |
| 随机数流 | `numpy.random.default_rng(seed=20261019)`；仅用于基准采样，几何确定 |

## 8. 未测试路径

- GPU / CUDA：无负载、无 torch。
- Optiland 光线追迹：未运行任何镜头案例（G2）。
- 长时间 Monte Carlo：G0 不涉及。
- 多机/跨平台：仅本机 Windows 11 + CPython 3.14。
- 远端 CI：配置已写，未执行（`CI_NOT_VERIFIED`）。
