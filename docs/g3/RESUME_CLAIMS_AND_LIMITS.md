# 简历主张与边界（RESUME CLAIMS AND LIMITS）

这份文件存在的唯一目的：让任何一句写进简历的话，都能在本仓库里找到证据，
并且**不会因为说得比证据多而变成虚假陈述**。

规则很简单：右列的证据不存在，左列的话就不能写。

---

## 一、可以写的（每条都有可核验证据）

| 主张 | 证据位置 |
|---|---|
| 实现共面激光三角测量的解析几何内核，并用独立向量/矩阵链交叉验证到 2.27e-13 px | `runs/20261019_130948_G0_78fa364f`、`src/optisys/geometry/reference.py` |
| 实现像元面积积分成像链与 CMOS 噪声/ADC 建模，能量守恒误差为 0 | `docs/VALIDATION_MATRIX.md`、`runs/20261019_145702_G1_54c9e3fb` |
| 实现三种亚像素定位器并量化对比（质心 / 1D 高斯 / 2D 高斯），2D 达 7.81e-5 px | 同上 |
| 实现两参数系统标定（`a = fx·B`、`b = cx − fx·tanθ`）并论证可辨识性边界 | `src/optisys/calibration/system.py`、`docs/OPEN_ISSUES.md` |
| 接入 Optiland 0.6.3 真实单透镜 L1 后端，含装配级公差 Monte Carlo（2000 装配） | `runs/20261019_191117_G2_52369787` |
| 实现按 `assembly_id` 聚类的配对 bootstrap（2000 次，种子 424242） | `src/optisys/evaluation/paired_comparison.py` |
| 构建 Streamlit 五页交互界面，数据层与 UI 解耦（ConfigService / RunRepository / JobService / ReportService） | `app/`、`tests/ui/test_pages_render.py`（17 项） |
| 实现版本化只读解析器，兼容 schema 1.0 / 2.0 / 3.0 三种互不相同的样本布局 | `src/optisys/presentation/run_repository.py` |
| 实现受控后台任务服务：无 shell、参数白名单、超时、取消、重启标 `ORPHANED` | `src/optisys/jobs/service.py`、`tests/integration/test_g3_tjobs.py`（13 项） |
| 构建可独立解压复验的审计包，manifest 逐项 SHA-256，复现脚本从解压副本执行 | `scripts/build_g3_audit_package.py`、`scripts/verify_g3_audit_package.py` |
| 在 G3 中定位并修正 6 项科学缺陷（含公式多乘 1/Z、CSV 截断至 20000 行、分层复用陈旧变量） | `docs/g3/G2_INHERITANCE_VERDICT.json` |
| 主动判定自己上一阶段的**预注册合规性为 FAIL** 并逐条披露，而不是掩盖 | `docs/g3/G2_INHERITANCE_SCIENTIFIC_AUDIT.md` |

最后两条是这个项目里最值得写的东西。**发现自己的门限不可达并公开它，
比多做一个 Gate 更能说明工程判断力。**

---

## 二、不能写的（写了就是虚假陈述）

| 禁止表述 | 为什么 |
|---|---|
| "实测验证"、"实验验证"、"与实测吻合" | **本项目零实测数据。** 全部为仿真。证据上限 `SIMULATED` / `CROSS_CHECKED` |
| "高精度"、"亚微米精度"、"工业级精度" | 仿真 RMSE 在 mm 量级（G2 robust 1.90 mm）。"精度"一词在无实测时无意义 |
| "可直接用于产品设计" | 单透镜 L1-approximate，无消色差、无 Scheimpflug、无真实波前 PSF |
| "完成了 G2 / 项目全部通过" | G2 的预注册合规性是 `FAIL`。只能写"完成 G2 执行并披露其合规偏离" |
| "G4 已完成 / 支持 976 nm" | `NOT_IMPLEMENTED`，本轮未启动 |
| "支持 GPU 加速" | torch 未安装，CUDA 不可用，`NOT_TESTED` |
| "并行加速 2.3×"（针对 G2/G3） | G2 的 4 进程加速属于历史记录；G3 的并行**未验证**，实测 2/4/6 进程均慢于单进程 |
| "robust 是最优设计" | 它 RMSE 最低但失败率最高（+3.14 pp）。任何单一排名都已被界面拒绝 |
| "重标定带来 X% 精度提升" | Strategy A/B 口径不同（2000×3 vs 200×1），`NOT_DIRECTLY_COMPARABLE`，该模块在 UI 中 `DISABLED` |
| "AI 自动完成光学设计" | 搜索是名义/鲁棒预算搜索，不是生成式设计；且仅在 89 个不可行设计被排除后的设计空间内 |
| "已通过 CI" | 本地测试通过 ≠ CI 通过。远端 CI 状态必须分列，未运行时写 `NOT_RUN` |
| "完整复现了 G2" | G2 全量 2000 装配约 5 625 s；G3 demo 是 12 装配的短时链路验证，`comparable_to_g2: false` |

---

## 三、需要加限定词才能写的

| 表述 | 必须补的限定 |
|---|---|
| "设计并实现了激光三角测量仿真平台" | + "仿真；无实测数据" |
| "将 RMSE 从 3.15 mm 降到 1.90 mm" | + "代价是失败率从 22.2% 升到 25.3%，属已知权衡（G2-07 OPEN）" |
| "完成了 2000 装配公差分析" | + "单一 medium 光照条件；不得跨条件外推" |
| "实现了完整测试矩阵" | + "T-BASE/T-SCI/T-DATA/T-UI/T-REPORT/T-JOBS/T-REPRO/T-SECURITY；并行与 GPU 未测" |
| "构建了审计追溯体系" | + "含一项已披露的 ZIP 截断缺陷（PRE-G3-04），G3 已改为整份或排除" |

---

## 四、一句话版本（适合简历摘要栏）

> 独立开发光电系统仿真平台（Python/NumPy/Optiland/Streamlit），覆盖几何内核、
> L0 成像与噪声链、三种亚像素定位、两参数标定、真实镜头公差 Monte Carlo 与
> 配对 bootstrap 评价；构建五页交互界面与可独立复验的审计流水线；
> 主动审计并公开披露上一阶段的预注册合规偏离（HC3 门限在 as-run 口径下不可达）。
> **全部结果为仿真，无实测数据。**

---

## 五、面试时最容易被追问的三点

**Q：你既然知道门限达不到，为什么当初设成 0.999？**

设的时候依据的是几何足迹占比，没有把 PSF 核的窗口裕度算进去。事后实测窗口半宽
由 `6 × 1.4 px + 1 ≈ 9.4 px` 主导，几何足迹只有 3–9 µm，所以 0.999 在
`max_half_px = 40` 下原理上不可达。这是一次预注册阶段的建模错误，不是运行后的
结果挑选。修订写成事后附录并标注 `POST-HOC AMENDMENT`，不改原预注册文本。

**Q：那你的 PASS 算不算数？**

执行记录算数——数据确实是那些行在声明分母下算出来的，126 000 行已独立重算核对。
预注册合规不算数。所以我给两条独立的裁决线，不给一个总 PASS。

**Q：为什么不做实测？**

没有硬件。这是选择不做，不是忘了做——所以证据等级停在 `SIMULATED`，
`MEASURED` 与 `VALIDATED` 在代码里保留为不可达状态，任何试图升级的路径都没有实现。