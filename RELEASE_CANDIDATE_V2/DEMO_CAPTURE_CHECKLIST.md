# S6-R 演示与验收清单

## 工程验证

- [x] 新环境安装命令已执行并保存安装日志、`pip freeze`。
- [x] 650 nm demo 与真实运行目录报告已执行并保存退出码。
- [x] 976 nm demo 与真实运行目录报告已执行并保存退出码；此缩小样本 run 自身状态为 `PARTIAL`。
- [x] 六页 Streamlit AppTest 已执行，A–F 每页 `at.exception` 为空。
- [x] Streamlit 服务 smoke 已记录实测 loopback URL、`/_stcore/health`、`/` 响应和端口释放。
- [x] 全量 pytest 使用新的空 basetemp 执行并保存原始 stdout、JUnit、退出码、wall clock 与测试计数；482 passed，0 failed/errors/skipped。

## 浏览器与媒体

- [ ] S6 浏览器 E2E：`NOT_RUN_POLICY_BLOCKED`。IAB 已部分显示 A/C/F 并切换 Pareto 标签，但浏览器版本、live console/error log 和可保存 PNG 均未取得。
- [ ] S6 新截图：`NOT_DELIVERED`。如生成，需保留此次浏览器会话的 URL、时间、页面、截图 SHA-256 和操作日志。
- [ ] 视频：`NOT_DELIVERED`。不以图表动画或拼接静态截图冒充真实录屏。
- [x] S5 历史截图的来源已识别：`screenshot_evidence/A_overview.png`、`C_optimization.png`、`F_pump976.png`。
- [x] `screenshot_evidence/browser_e2e.json` 是 S5 运行 `20261020_210201_S5_HNA` 的历史记录，不能用于证明本轮 S6 浏览器验收。

## 审计发布

- [x] S6-C 逐装配统计、配对、权重守恒和 bootstrap 已独立重算；四个情景的 8,000 个 replicate 行已用冻结种子逐条复放。
- [x] Amendment 03、冻结验收条件与程序自动标签的时间线已复核；单独预注册文件缺失已如实记录，但冻结规则在验收条件和 holdout freeze 中可复核。
- [x] 新 GPT 审计 ZIP 已完成内容哈希、独立解压复现、篡改拒绝、缺失文件拒绝与同环境字节重建验证；路径和外部 SHA-256 sidecar 见 `docs/s6r/S6R_FINAL_STATUS.json`。
- [ ] GitHub 目标仓库和可见性已确认；提交前排除本机虚拟环境、临时数据与个人记忆文件。

原始候选把 S5 浏览器 PASS 混在 S6 发布材料中；S6 本轮仅完成 IAB 页面交互的部分检查，完整 E2E 标记为 `NOT_RUN_POLICY_BLOCKED`。系统 Chrome 的截图捕获路径被 Computer Use URL 安全检查停止；没有绕过，S6 PNG 仍标 `NOT_DELIVERED`。入场文件哈希及更正依据见 `docs/s6r/BASELINE_HASHES.json` 与 `docs/s6r/R0_CLAIM_CORRECTIONS.md`。
