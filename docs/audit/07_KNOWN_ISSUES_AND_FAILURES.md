# 07_KNOWN_ISSUES_AND_FAILURES

本文件记录所有未关闭问题、失败运行、负结果与审计包无法离线复核的内容。**不隐藏失败**。

## 1. 未关闭问题（摘要）

| ID | 严重度 | 问题 | 对结论的影响 | 状态 |
|---|---|---|---|---|
| OI-001 / SD-001 | P1 | PDF 式 (3) 导数符号与式 (2) 矛盾 | 幅值结论不受影响；有符号用法已按负值实现并测试 | 已披露，待任务书作者确认措辞 |
| OI-002 | P2 | `min_baseline_mm = 1.0 mm` 无机械依据 | B ∈ (0,1) mm 被拒绝，阈值本身未经物理验证 | OPEN |
| OI-003 | P2 | θ 独立对照仅 −3°/0°/+3° | 更大角度的正确性未被本 Gate 覆盖 | OPEN |
| OI-004 | P1 | Optiland 未运行任何镜头案例 | 不能声称 L1 光学能力 | DEFERRED（G2） |
| OI-005 | P1 | GitHub Actions 未在远端执行 | R10 只能 PARTIAL，不能称跨平台已验证 | OPEN |
| OI-009 | P1 | 无实测数据 | 最高证据等级 CROSS-CHECKED | OPEN（外部条件） |
| OI-011 | P2 | 200k 单次调用慢于 8×25k 分块（缓存效应） | 不影响正确性；G2 将分块实现 | OPEN |

完整表见项目内 `docs/OPEN_ISSUES.md`（本包 `docs/OPEN_ISSUES.md`）。

## 2. 失败与返工记录（开发运行）

这些 run 未进入审计证据，但保留在项目 `runs/_dev_archive/`，原因如下：

| run_id | 结果 | 失败原因 | 修复 |
|---|---|---|---|
| `20261019_124503_G0_1e375903` | ABORTED | NumPy 2.x `np.linalg.solve` 把二维 rhs 当矩阵，batched 解析失败 | rhs 增加尾轴 `[:, :, None]` |
| `20261019_124523_G0_1e375903` | ABORTED | 齐次 4 维点乘 3×3 内参，维度不匹配 | 改为显式 3×4 `K[R|t]` |
| `20261019_124544_G0_1e375903` | FAIL | 端点反演得 `300.00000000000006`，被严格闭区间判为 OUT_OF_RANGE（4/123 点） | 增加 `range_epsilon_mm = 1e-6` 与端点测试 |
| `20261019_125527_G0_78fa364f` | PASS（作废） | 图 3 裁切注释错误、图 4 对数坐标把零残差画成锯齿 | 改进绘图；重建 run |
| `20261019_125908_G0_78fa364f` | PASS（作废） | 测试摘要按 “tests” 聚合，模块分组错误 | 修正 summarizer；重建 run |
| `20261019_130035_G0_78fa364f` | PASS（作废） | 报告把测试统计渲染成 Python dict 字面量 | 修正报告模板；重建 run |
| `20261019_130035_G0_78fa364f` | PASS（作废） | 报告把测试统计渲染成 Python dict 字面量 | 修正报告模板；重建 run |

作废原因均为**证据质量问题**或**代码已变更导致 provenance 不再匹配**，不是数值结论改变。

## 3. 负结果

| 项 | 结果 | 解释 |
|---|---|---|
| 进程并行 2 workers | 0.53×（慢） | 200k 数组 pickle + 进程启动成本 > 计算收益 |
| 进程并行 4 workers | 0.60× | 同上 |
| 进程并行 6 workers | 0.51× | 同上，且 6 物理核已无余量 |
| GPU | NOT_TESTED | 无张量负载，torch 未安装；不声称加速 |
| 优化/公差 | 未执行 | G2 范围；`tolerance` 命令返回 3 是正确行为 |

这些负结果没有被“换种子/调权重”掩盖；`benchmark.json` 保存原始中位耗时与池启动时间。

## 4. 审计包不能离线复核的内容

| 项 | 原因 | 包内替代证据 |
|---|---|---|
| 完整 `runs/` 下所有历史 run | 体积与历史噪声 | 仅冻结 run 的关键文件与样本 |
| 逐字节重建 PNG/HTML | 字体、matplotlib 版本、时间戳 | 原始绘图数据 CSV + 生成脚本 |
| 远端 CI 结果 | 未执行 | `.github/workflows/ci.yml` 与 `CI_NOT_VERIFIED` 标记 |
| GPU 基准 | 无可运行路径 | `NOT_TESTED` 明确记录 |
| Optiland 镜头案例 | 未运行 | `lens_case_executed: false` |
| 真实相机/实测数据 | 不存在 | 无 `MEASURED` 标签 |

## 5. 报告与文档的自指问题

- `report.html` 第 9 节的文件索引是生成时刻的快照，不含 `report.html` 自身与之后写入的文件；完整清单以 `manifest.json` 为准。
- `manifest.json` 不列出自身哈希；`SHA256SUMS.txt` 不列出自身。这是为了避免自引用，已在 `00_START_HERE.md` 说明。

## 6. 如果审计者只看到本包

仍然可以独立完成：

1. 阅读 `03_SCIENTIFIC_AUDIT.md` 的公式与独立方法；
2. 运行 `repro/verify_g0.py` 复算残差；
3. 运行 `pytest` 验证 117 项测试；
4. 用 `scripts/verify_audit_package.py` 校验包完整性；
5. 抽查 `samples.csv` 与 `formula_comparison.csv` 的数字。

不能完成：实测验证、镜头像质、CMOS 噪声统计、公差收益评估——因为这些在 G0 根本不存在。
