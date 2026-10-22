# G4 开放问题

| ID | 严重度 | 问题 | 影响/处理 |
|---|---|---|---|
| G4-01 | P0 | 缺光纤厂家料号/手册、LD绝对功率、镜片料号/涂层、晶体有效尺寸 | 全部作为 ASSUMED/UNKNOWN；无 W/mm²、吸收、温升或效率主张 |
| G4-02 | P0 | P0 ideal thin-lens 对 NA=0.22 预测100%到达1mm target；假设 Optiland N-BK7 singlet P1 约68.19%/67.50% | 高 NA 光学主张 `QUALIFIED`；P1几何模型与P0简化不一致，需要真实镜片设计或实测才能裁决 |
| G4-03 | P1 | P1 adapter 只建中心等凸 singlet，不含偏心/倾斜坐标断点、镀膜/Fresnel、衍射/相干 | OAT/公差 misalignment 只基于 P0；报告限制 |
| G4-04 | P0 | 无经授权的 976 nm 实验光斑与绝对辐射标定 | `G4_EMPIRICAL_VALIDATION_STATUS=NOT_AVAILABLE`; 未启动设备 |
| G4-05 | P1 | 1mm active target 是任意接收区，不是经核实 Er:YAP 晶体尺寸 | 所有 target capture 的解释仅条件于该模型尺寸 |
| G4-06 | P2 | 实际演示视频与浏览器 WebSocket E2E 截图未交付 | `VIDEO_STATUS=NOT_DELIVERED`; AppTest与HTTP server smoke已分开测试 |
| G4-07 | P2 | G2 原预注册/距离泄漏/HC3 争议依旧 | 旧科学线保持 `QUALIFIED_ONLY`; 本轮没有重跑 G2 来更新它 |
| G4-08 | P2 | 远端 CI / CUDA / GPU加速 | `REMOTE_CI=NOT_RUN`; GPU `NOT_TESTED` |

`G4-02` 是负结果/模型范围差异，不是打包失败。G4工程状态通过不意味着 P1 对全 NA 真实光路已验证。
