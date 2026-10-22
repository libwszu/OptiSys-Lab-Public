# 给下一轮 GPT 的独立审计任务

请只依据本 ZIP 内文件审查，不读取源工作区来补数据。

1. 先验证 `manifest.json`、`SHA256SUMS.txt`、ZIP testzip、路径安全、成员重复和 ZIP_STORED 类型。
2. 阅读 `run/run_status.json`、`g4/G4_FINAL_STATUS.json`、00–08 文档，核对工程状态、模型验证、公差、实验、作品与 audit 状态是否一致。不得将 `PASS_WITH_DECLARED_DEVIATIONS` 简写为 `G4_ALL_PASS`。
3. 运行 `python repro/verify_g4.py`。该脚本必须只读 ZIP 内 CSV/JSON 并独立复算 P0 rays、baseline spot radius、权重闭合、tolerance 分母和 holdout aggregate。
4. 核查 400 行 `run/tolerance_samples.csv` 全部 assembly/design/phase/扰动及失败记录；不得只看摘要。
5. 评估 P0/P1 NA=0.22 差异是否足以阻止 full-NA 物理主张；核对 `source_power=UNKNOWN` 和接收密度不是 W/mm²。
6. 独立确认 G2 的 `QUALIFIED_ONLY`、G3 历史 P1问题和 G3 时测时差异被保留。
7. 若发现问题，给出文件路径、数据行/字段和可复现步骤；不得建议用放宽阈值、删失败行或改写历史证据来“修绿”。

只凭本 ZIP 可复算：P0 nominal ray positions、source/target weight ledger、r80/r90、400 tolerance denominator、holdout means、P0/P1 transmitted weights。需外部数据才能判断：真实材料/料号、绝对功率、实验 spot/吸收/热效应和真实器件适用性。
