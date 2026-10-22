# G4 验证矩阵

详细阈值、观察值和源文件路径见 `g4/G4_VALIDATION_MATRIX.md`。核心结果如下：

| 检查 | 结果 |
|---|---|
| 源采样统计、NA、归一方向/权重、非法输入 | PASS |
| P0 scalar independent reference | PASS；8192 rays，位置/方向差分别 0.0 mm / 0 |
| P1 Optiland 0.6.3 实际两个 singlets | 低 NA cross-check PASS；全 NA 模型 `QUALIFIED` |
| 权重账本与 density 积分 | PASS；全部正式账本闭合 |
| 2k/8k/32k ray-count uncertainty | PASS；8k→32k r80 变化约 0.389% |
| OAT / precheck / independent holdout | PASS；30 OAT、100+100装配/设计、400行 |
| Streamlit / CLI / JobService timeout | PASS；AppTest 与 HTTP server smoke 分开报告 |
| 全量 pytest | PASS；449 /0/0/0，exit 0 |
| 外部测量 | NOT_AVAILABLE / NOT_RUN |
| 内容完整、独立解压复算、篡改拒绝、同/跨环境 ZIP_STORED 重建 | PASS；见外部 `AUDIT_VERIFY_LOG.txt` |

全量 JUnit/stdout/stderr/exit/墙钟原始证据位于 `test_evidence/`。
