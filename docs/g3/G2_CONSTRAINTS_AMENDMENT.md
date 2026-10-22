# G2 约束事后修订（HC3）

生成时间：2026-10-20（UTC）
状态：**事后修订（POST-HOC AMENDMENT）**
不是预注册文本的替换，也不是对历史执行的事后追认。

---

## 0. 这份文件是什么

`docs/g2/G2_PRE_REGISTRATION.md:33` 把 HC3 定为 `kernel support fraction >= 0.999`。
`configs/triangulation_g2_l1.yaml:112` 实际执行的是 `min_kernel_support: 0.950`。

两者冲突。本文件的目的只有一个：**把 0.950 这个 as-run 值解释清楚，并说明为什么 0.999 对该光学模型不可达**。它不修改预注册文本，前者仍是历史事实。

按 `G3-D-007`：预注册文件是历史文件，事后改写即为学术不端。所以修订只能作为**附加文件**存在，且必须处处标注为「事后」。

---

## 1. 冲突事实

| 项 | 值 | 位置 |
|---|---|---|
| 预注册门限 | `>= 0.999` | `docs/g2/G2_PRE_REGISTRATION.md:33` |
| as-run 门限 | `>= 0.950` | `configs/triangulation_g2_l1.yaml:112` |
| 后果码 | `INFEASIBLE(INSUFFICIENT_PSF_SUPPORT)` | `src/optisys/optimization/constraints.py:97-98` |

---

## 2. `kernel_support` 的确切定义

```
kernel_support = geom_frac × airy_frac
```

- `geom_frac`：追迹光线权重落在有限 PSF 窗内的比例
- `airy_frac`：同一窗内 Airy 环围能量比例
- 窗口半宽：`half = ceil(max(|du|,|dv|)) + airy_radius_margin × airy_radius + 1`
- `max_half_px = 40`，`airy_radius_margin = 6.0`

定义处：`src/optisys/optics/psf_or_footprint.py:178-180`
评估处：`src/optisys/optimization/constraints.py:97-98`（可行性门），`src/optisys/optics/optical_image_contract.py:233-237`（仅告警）
探针距离：100 / 200 / 300 mm，medium 条件，nominal 单元

---

## 3. 实测：三个设计全部不可达

`scripts/g3_pre_g3_01_hc3.py`，四档门限 × 三候选 × 3 约束距离 + 全量观测面板。

| 候选 | 设计 (B/f/θ) | probe@100 | probe@200 | probe@300 | 观测中位数 | 观测 min–max | < 0.999 | < 0.990 | < 0.950 |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 20.0 / 8.0 / 0° | 0.97872 | 0.98042 | 0.98201 | 0.98049 | 0.97505–0.98738 | **100 %** | 100 % | 0 % |
| nominal | 15.0 / 11.1 / 4° | 0.98356 | 0.97369 | 0.97834 | 0.97830 | 0.97280–0.98621 | **100 %** | 100 % | 0 % |
| robust | 34.4 / 7.2724 / 4° | 0.98709 | 0.98136 | 0.98136 | 0.98236 | 0.97499–0.99051 | **100 %** | 99.98 % | 0 % |

每候选 42 000 行观测。**126 000 行里没有一行达到 0.999。**

`probe_feasible_under_0.999` 三候选均为 `false`。

---

## 4. 为什么 0.999 不可达（机理）

`kernel_support` 度量的是**有限窗内的能量截断损失**。窗口半宽由**几何足迹**驱动，而几何足迹远小于 Airy 半径：

| 量 | 量级 |
|---|---|
| 单透镜 EPD 下的几何足迹（f/6.7–f/10） | 3–9 µm |
| 对应像素 | 亚像素级 |
| Airy 半径（650 nm，fx ≈ 2319 px） | ~1.4 px |
| `airy_radius_margin` | 6.0 |
| 结果窗口半宽 | 由 `6 × 1.4 + 1 ≈ 9.4 px` 主导 |

也就是说，窗口是被 Airy 项撑开的，几何项贡献很小。Airy 环的旁瓣在 9.4 px 处仍有可观能量，`airy_frac` 因此被钉在 0.972–0.991 区间。想要 0.999 必须把窗口放大一个量级，而那会破坏 `max_half_px=40` 的核截断预算与「核有限」这一前提。

**结论：0.999 不是一条更严格的约束，而是一条对该光学模型病态的约束（ill-posed constraint）。**

---

## 5. 修订内容（建议值，非追溯生效）

| 项 | 原值 | 建议值 | 理由 |
|---|---|---|---|
| HC3 门限 | `>= 0.999` | `>= 0.950` | 0.950 在实测分布（0.9728 最小）下方留 2.3 pp 余量，同时仍能筛掉真正丢失支持的病态设计 |
| HC3 定义 | 单一阈值 | 双阈值 + 分类 | `0.950` 为硬门；`0.990` 以下标记 `SUPPORT_ATTENUATED` 作为**信息披露**而非拒绝 |
| 报告要求 | 无 | 每个候选必须同时显示 0.999 与 0.950 | 两套口径并存，不允许只显示一套 |

**修订的效力范围**：仅对**未来**运行生效。`runs/20261019_191117_G2_52369787` 的 0.950 仍是 as-run 值，其科学主张仍须携带 `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED`。

---

## 6. 为什么这不算「事后合理化」

区分两件事：

1. **事实陈述**：0.999 对该模型不可达（§3 实测 + §4 机理）。这是可复算的客观结论。
2. **规范陈述**：0.950 是正确的门限。这**不是**本文件的主张。

本文件只做 1，并把 2 降级为「建议值，待下一轮预注册采纳」。原始文本仍是 `0.999`，任何声称「G2 完全遵守预注册」的表述依然被禁止。

判断本修订是否成立的可伪证条件：若某个设计在 `max_half_px=40` 下能达到 0.999，则 §4 的机理分析错误，本修订作废。本轮 126 000 行中无此类设计。

---

## 7. 影响

| 面 | 影响 |
|---|---|
| 冻结数值 | **无**。HC3 只决定设计可行性，不改变已记录的任何误差统计 |
| 设计空间 | 0.999 下三个候选全部 `INFEASIBLE`，设计集合为空；0.950 下三者可行。所以这条冲突决定了「G2 到底有没有可行设计」这一根本问题，不是旁枝 |
| 科学主张 | 必须携带 `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED` |
| 后续 Gate | G4 及以后若沿用此光学模型，应直接采用修订后的双阈值 |

---

## 8. 证据

- `docs/g3/evidence/G2_HC3_SUMMARY.json` — 逐候选统计与结论
- `docs/g3/evidence/G2_HC3_THRESHOLD_SCAN.csv` — 四档门限扫描明细
- `docs/g3/evidence/G2_PREREG_VS_ASRUN.csv` — 预注册 vs as-run 逐项对照
- `scripts/g3_pre_g3_01_hc3.py` — 复算脚本
- `src/optisys/optics/psf_or_footprint.py:178-180` — 定义
- `src/optisys/optimization/constraints.py:97-98` — 评估点