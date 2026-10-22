# G4 976 nm 泵浦光路审计包

**Run**：`20261020_133555_G4_ec3e2813_0e48` · **状态**：`PASS_WITH_DECLARED_DEVIATIONS` · **模型**：`P1_QUALIFIED` · **证据**：`SIMULATED`

先读：

1. `01_EXECUTIVE_SUMMARY.md`：交付状态、代表结果和结论边界。
2. `03_SCIENTIFIC_AUDIT.md`：源采样、P0/P1 差异、权重分母和半径定义。
3. `run/tolerance_samples.csv`：完整 400 行正式公差记录，包含所有设计/装配/阶段/扰动/失败状态。
4. `run/optical_crosscheck.json`：P0 独立标量对照与 P1 低角度门限。
5. `manifest.json` 与 `SHA256SUMS.txt`：逐文件内容完整性。

## 两条裁决线

- G4 工程执行：`PASS_WITH_DECLARED_DEVIATIONS`。G4 自身物理验证为 `QUALIFIED`；外部实测 `NOT_AVAILABLE`。
- 继承 G2 科学状态：`QUALIFIED_ONLY`。G2 历史执行记录不代表预注册合规；本轮没有重跑 G2。

## 审计状态

ZIP 内容校验、独立解压复算、篡改拒绝与同/跨环境重建均为 `PASS`，日志位于 ZIP 外的 `AUDIT_VERIFY_LOG.txt`；最终 run status 亦记录 `G4_AUDIT_STATUS=PASS`。

本案例不输出真实 W/mm²、吸收功率、温升或 Er:YAP 激光效率；接收面密度是归一化几何射线权重代理量。
