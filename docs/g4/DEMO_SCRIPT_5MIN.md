# G4 五分钟演示脚本

**视频状态**：`NOT_DELIVERED`。这是操作脚本，不是录像。

## 0:00–0:45 · 先说明证据边界

打开页面 A。说明 G2 历史执行记录与科学合规是两条线；G2 science 仍为 `QUALIFIED_ONLY`。全项目无实测数据。

## 0:45–1:30 · 打开 976 nm 页面

点击页面 F。指出 105 µm芯径、NA 0.22、空气出射是假设输入；功率未知，图的颜色是归一化射线权重密度，不是 W/mm²。baseline 为 25/100 mm、Ø12/Ø12 mm；engineering candidate 为 35/100 mm、Ø16/Ø17 mm。

## 1:30–2:20 · 看真实源与光路结果

展示实际 run：`runs/20261020_133555_G4_ec3e2813_0e48/`。打开 `figures/01_beamline_layout.png`、`05_source_distributions.png` 与 `02_target_density_p0.png`。强调边缘偏重曲线只是敏感性分布。

## 2:20–3:20 · 解释模型差异

对照 `target_plane_metrics.csv`：P0 ideal thin lens 的 NA=0.22 baseline 通光 1.0、r90 0.199 mm；假设 N-BK7 singlet P1 到 1 mm 接收区约 0.682、r90 0.848 mm。解释这是模型差异，不是实测，也不能把 P0 结果当作器件保证。

## 3:20–4:20 · 公差与设计权衡

打开 OAT 与 tolerance holdout 图/CSV。说明每个候选各100装配、2048 rays/装配、paired common random numbers；较小 P0 焦斑依赖理想薄透镜且候选使用更大口径，因此本轮整体判为 `NO_SUPPORTED_IMPROVEMENT`。

## 4:20–5:00 · 代码/报告/审计

展示页面 F 的后台 JobService、HTML 报告、完整 `tolerance_samples.csv`、`optical_crosscheck.json`。最后打开 G4 audit ZIP。说清楚未做项：无绝对功率、无实验、无完整 Er:YAP、无视频、GPU未测；G2仍 `QUALIFIED_ONLY`。
