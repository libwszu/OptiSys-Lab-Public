# 五分钟本地演示流程

本稿是实际演示的讲解顺序；只有在真实 Streamlit UI 中操作时才算录制素材。若没有可用录屏工具，保留脚本和截图并标记 `VIDEO_NOT_DELIVERED`。

## 0:00–0:40 — 项目定位

打开 Overview。说明这是 Python 光电系统仿真、运行数据和报告平台，页面读入实际 run 与裁决数据，不在 UI 中伪造科学指标。分别指出 650 nm 三角测量主案例和 976 nm 多模泵浦第二案例。

## 0:40–1:35 — 650 nm 案例

打开 Optical Bench，使用 FAST_PREVIEW 展示单帧的几何成像、CMOS 采样与定位结果，指出预览标记和执行状态。切换到 Optimization Comparison 展示多指标对照；说明 G2 为 `QUALIFIED_ONLY`，历史科学结论没有因为 UI 完成而升级。

## 1:35–2:20 — 运行与报告

在 PowerShell 运行 README 中的低成本 `g3-demo`，展示 CLI 返回的 run_id、输出目录与状态。为该 run 生成 HTML 报告，展示 run 目录可复现的 JSON/CSV 与报告，而不是屏幕上的临时数字。

## 2:20–3:35 — 976 nm 光路

打开 976 nm pump 页面，展示来源假设、光路图和固定 1 mm 接收区。说明光纤近场/远场、N-BK7 镜片、公差与源功率均不是实测输入，绝对功率 `UNKNOWN`。

## 3:35–4:30 — S6 装配敏感性

打开 S6-C 图，先说明每个误差情景有 200 个 assembly、每设计 1,024 rays，配对 bootstrap 按 assembly 重采样。指出名义误差下平均差为正，再展示 2× stress 的 paired P05 反转；据此说明总裁决为 `TRADEOFF_OR_NO_SUPPORTED_GAIN`。

## 4:30–5:00 — 证据与限制

打开 Evidence Center，再到 About/Limitations。说明 A 通过的是假设 P1 几何双参考，不是厂家镜片或真实装配资格认证；S6-B 搜索边界未括定；无真实光功率、晶体尺寸、泵浦效率或热测试。展示 S6 审计报告路径与只读历史状态。
