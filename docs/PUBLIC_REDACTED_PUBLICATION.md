# 公开脱敏候选说明

本目录源于 PUBLIC_REDACTED R2 工程快照；当前仓库入口和发布范围见 [公开副本范围](PUBLIC_RELEASE_SCOPE.md)，实际发布状态以 GitHub 记录为准。旧私有 Git 历史、Actions 日志/构件与原审计 ZIP 不随本候选分发。

公开审计副本使用新 ID `OptiSysLab_S6R_PUBLIC_REDACTED_R2`、新 schema 和新 SHA；[副本校验值](../_AUDIT/PUBLIC_REDACTED_R2/OptiSysLab_S6R_PUBLIC_REDACTED_R2.sha256) 与 [副本 ZIP](../_AUDIT/PUBLIC_REDACTED_R2/OptiSysLab_S6R_PUBLIC_REDACTED_R2.zip) 对应。原件留在私有保全目录，不能以新包替代旧包哈希证明。私有提交与逐成员映射不在此候选内。

`docs/g2` 至 `docs/s6r`、运行快照与发布报告保留历史验证时点和科学裁决。涉及本机路径与私有 Git 修订标识的公开元数据使用明确占位符；不改参数、种子、阈值、原始数组、样本或不利结论。新的派生 release manifest 明确标记公开副本身份，不能当作原预注册清单。

G2 为 FAIL / QUALIFIED_ONLY；G4 为 QUALIFIED、NO_SUPPORTED_IMPROVEMENT；S6 名义均值 +18.05 pp、stress 配对 P05 -5.69 pp，四情景 TRADEOFF_OR_NO_SUPPORTED_GAIN。所有结果为模拟/独立交叉核验，无真实实验数据。

Windows Python 3.11：先运行 README 安装命令，再执行 `python scripts/verify_published_frozen_inputs.py`（原 G4 六项字节输入）和 `python scripts/verify_public_audit.py _AUDIT/PUBLIC_REDACTED_R2/OptiSysLab_S6R_PUBLIC_REDACTED_R2.zip`（新审计副本）。独立统计复算使用 `python repro/verify_s6r.py --root . --output artifacts/public-s6.json`。旧 S6-R 原件检查器不适用于新 schema。

当前安全反馈渠道尚未启用；正式公开时按照 GitHub 的 Settings → Security and quality → Advanced Security → Private vulnerability reporting 启用，并在 Security → Advisories 验证 Report a vulnerability 可用后更新 SECURITY.md。
