# 已知限制

- G2 的历史科学状态保持 `QUALIFIED_ONLY`；G4 保持 `QUALIFIED`；S5 的 `P1_SUPPORTED_TRADEOFF` 只涉及名义假设 P1 光线。S6 不升级任何历史 Gate。
- S6-A 的 PASS 只说明两条独立球面/折射实现与对抗性测试在已登记假设几何上相符，不代表厂商镜片资格认证或实际装配测量。
- S6-B 焦面扫描与 L2 位置扫描都未括定全域最优；145 mm 在 L2 搜索边界仍最高，焦面包含捕获平台。
- S6-C 总结论是 `TRADEOFF_OR_NO_SUPPORTED_GAIN`：名义 1×误差下平均捕获有优势；2×压力情景的 assembly-paired P05 差为负且出现少量候选 L2 aperture clipping。
- 芯径 105 µm、NA 0.22、均匀面积近场、均匀立体角远场、N-BK7 2 mm singlet、1 mm 接收半径和公差 sigma 都是仿真假设。
- 绝对 source power `UNKNOWN`；厂商镜片料号和图纸 `NOT_VERIFIED`；真实模态/远场、涂层/Fresnel 损耗、晶体尺寸、安装行程、实际泵浦效率与热效应 `NOT_AVAILABLE`。
- 全部捕获率是以输入源权重为分母的几何统计，不是实际传输功率或制造良率。
- S6 使用 assembly bootstrap，而 S5 历史区间使用 ray bootstrap；两种不确定性不能混为一谈。
- 本地 Streamlit、AppTest 和浏览器 E2E 仅验证软件交付；远端 CI 未运行，GPU 仅检测到设备但未执行计算，实物测量不可用，视频未交付。
