# 公开派生版与再现

OptiSys-Lab-Public 提供 650 nm 激光三角测量和 976 nm 多模光纤泵浦两个可审查、可运行的工程仿真案例。源码采用独立根提交，文档和工作流围绕该新仓库维护；私有原件不随此工程副本公开。

## 审计副本

发行材料使用 `OptiSysLab_S6R_PUBLIC_REDACTED_R2.zip`，schema 为 `optisys.public_redacted_audit/2`。这是明确标识的新脱敏副本，不是未修改的历史原件：441 个成员，439 项由 manifest/SHA256SUMS 管理。逐成员私有映射、原始归档、旧 Git/Actions 历史不分发。

SHA-256：`f1d7e04121659e9b632e79a5cbdd73ff5425e6e1feaa89ac0d719d860f29ed5c`。

[副本 ZIP](../_AUDIT/PUBLIC_REDACTED_R2/OptiSysLab_S6R_PUBLIC_REDACTED_R2.zip) · [校验文件](../_AUDIT/PUBLIC_REDACTED_R2/OptiSysLab_S6R_PUBLIC_REDACTED_R2.sha256)

从仓库根目录运行（Windows 将 `python` 换为 `.venv/Scripts/python.exe`；Ubuntu 使用 `.venv/bin/python`）：

```bash
python scripts/verify_public_audit.py _AUDIT/PUBLIC_REDACTED_R2/OptiSysLab_S6R_PUBLIC_REDACTED_R2.zip --expected-sha256 f1d7e04121659e9b632e79a5cbdd73ff5425e6e1feaa89ac0d719d860f29ed5c
python scripts/verify_published_frozen_inputs.py
python repro/verify_s6r.py --root . --output artifacts/quick/s6-science.json
```

新包内的核验器识别新 schema；旧原始包检查器不用于认证它。G4 的六项原始冻结字节检查与新审计包的成员清单各有范围，不能互相替代。公开元数据中的本机路径和旧修订标识已使用明确占位符；科学数组、CSV、配置、种子和阈值保持不变。

## 示例与测试范围

默认 UI 浏览预置样本，无需重新模拟。650 nm 最短路径为 validate 与 repro/verify_g0.py；976 nm 低成本路径为 `python -m optisys pump976 --rays 512 --assemblies 2 --runs-dir artifacts/quick/pump976`。该命令输出 PARTIAL 是明确的缩减采样状态，不能提升为完整 G4 科学结论。

CI 配置见 [工作流](../.github/workflows/ci.yml)，实际执行见 [Actions](https://github.com/libwszu/OptiSys-Lab-Public/actions)。可分发回归覆盖 unit/reference/UI 与所列 12 个集成模块；两项 G0/G1 原始运行缺失可导致已声明的 skip。完整历史原树回归、正式 S6 浏览器 E2E、新截图和视频不能据此宣称完成。README 的截图是 S5 历史真实截图，S6 图为仿真统计图。

## 科学解释

G2 为 FAIL / QUALIFIED_ONLY；G4 为 QUALIFIED / NO_SUPPORTED_IMPROVEMENT；S5 为假设 P1 的条件性 trade-off。S6 1× 名义均值配对收益 +18.05 pp，2× stress 配对 P05 -5.69 pp，四情景 TRADEOFF_OR_NO_SUPPORTED_GAIN。均为模拟或独立交叉核验，无真实实验、厂家镜片验证或绝对光功率标定。

根目录 [MIT](../LICENSE) 覆盖项目有权分发的原创部分；第三方能力与许可见 [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)。版本与资产仅以 [Release 记录](https://github.com/libwszu/OptiSys-Lab-Public/releases) 的实际内容为准，不将本地测试或计划中的发版冒充已公开记录。
