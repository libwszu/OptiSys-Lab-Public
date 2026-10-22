# S6 执行计划（结果前冻结）

1. **PRE**：记录 HEAD、完整既有 dirty/untracked 文件哈希、PDF/S5 ZIP 与 G0–G4/S5 基线；写定本文件、范围、验收、配置和计算策略并哈希冻结。
2. **A 参考链**：新增局部系和世界系独立的有限厚度 P1 球面 ray tracer；固定前顶点 pivot 与固定接收面；在脚本中执行全矩阵和失败分类；保存逐面 CSV、负例和参考差异。只有 `S6_A_RIGID_BODY_REFERENCE=PASS` 才准进入 C。
3. **算力 profile**：用 A 的真实非共轴负载测冷启动、warmup 及 256/512/2048 rays × 1/2/4 workers，保存 wall、throughput、p50/p95、RSS、worker startup 和 output SHA。单任务硬超时 120 s；线程环境限制为 1；仅当 4-worker speedup ≥1.3× 且 RSS 低于软门才采用并行。profile 结束后、读取正式 holdout 前按预算决定一次样本规模；必要时追加不覆盖的 amendment。
4. **B 边界**：用独立 development seed `8061001`，分别执行固定镜位的焦面网格及固定目标的 L2 位置网格。只作登记的廉价敏感性诊断，不用 S5 seed 976053，不自动延伸搜索域。
5. **C 装配**：先运行 32 assembly × 256 rays/design 的 pilot，只用于验证参数生效、checkpoint 和吞吐，不看候选收益调整标准。holdout 使用独立 assembly seed `8062101`、每装配独立 source seed `80630000+assembly_id`、bootstrap seed `8064001`。两个候选各自名义几何上施加同一随机扰动向量，接收面固定；按 assembly checkpoint，恢复前验证 config/backend hash；无效装配不得重抽。只执行预先声明的零/紧/名义/压力四情景。
6. **D 发布**：只创建 `RELEASE_CANDIDATE_V2/`；修复 Windows 命令、保存可复跑五分钟演示脚本和核验过的 S6 图表/截图；新 venv 执行安装、两个低成本 demo 和派生报告。运行 6 页 AppTest、真实 Streamlit serve/health/root/port cleanup；检测可用 Edge E2E 和真实录屏能力，无法提供时清楚说明。
7. **E 收口**：在新的 basetemp 执行全量 pytest；重新哈希历史保护集；固定机器可读 run status 和偏差清单；构造一次 S6 GPT ZIP，做成员/manifest/hash/path 安全检查、`testzip`、安全独立解压重放、篡改和删除否决验证。最终只报告实际测量值和失败状态。

## 冻结种子及用途

| 用途 | seed |
|---|---:|
| A 对抗性新源射线 | 8065001 |
| B boundary development | 8061001 |
| C pilot assembly | 8062001 |
| C assembly holdout | 8062101 |
| C 每装配 source seed base | 80630000 |
| paired assembly bootstrap | 8064001 |
| 未参与计算的负向验证 | 8067001 |

A 为满足 S5 零位逐 ray 对照可读取 S5 的 976053 heldout 记录；它只用于 reference equivalence，不进入 B 选点、C assembly 样本、source seed 选择或 C 统计。
