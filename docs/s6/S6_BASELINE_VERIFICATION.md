# S6 基线核验（接管时点）

**Run ID:** `20261021_024715_S6_P1`  
**Git HEAD:** `PRIVATE_SOURCE_REVISION`  
**工作区:** 接管时已有 240 条 porcelain v1 `-uall` 变更；逐文件 SHA-256 与字节数保存在 `runs/20261021_024715_S6_P1/preexisting_worktree.json`。这些文件不属于 S6 修改集。

## 已核验的冻结输入

| 对象 | 现场结果 | 核验方式 |
|---|---|---|
| 原始项目 PDF | SHA-256 `25d0a727fbf047e8b399be8bd1ab670149b4a32377ff8edcef63e41ca4e6319d` | 与 S5 冻结值一致 |
| S6 任务书 | SHA-256 `7d0489af259e15cd62f02042bfe75d1b2eac9374ef22b0a329561b5fa574d351` | 仓库内 `1md/` 与 Downloads 副本一致 |
| S5 审计 ZIP | 15,773,717 bytes；SHA-256 `18d946e3c3d9cecadab558a05c262c8b1c286fa062ae11050037b6ed3df13ec5` | 现场 ZIP 哈希、侧车值一致；`testzip()` 返回 `None` |
| S5 ZIP 成员 | 164 总成员；162 个 manifest 管理成员；`manifest.json` 与 `SHA256SUMS.txt` 为 2 个自引用例外 | 现场读取 ZIP 并核对 manifest |
| G2/G4/S5 科学状态 | G2 `QUALIFIED_ONLY`；G4 `QUALIFIED`；S5 `P1_SUPPORTED_TRADEOFF` | 分别继承原状态，不合并升级 |
| S5 P1 装配交叉验证 | 尚无 | S5 只核验居中球面；需由 S6-A 新建并独立交叉验证 |

G0–G3 的 21 项保护清单、G4 run tree / 审计 ZIP、S5 run tree 的本轮重算结果和 S5 ZIP 独立解压重放结果，稍后写入本 run 的 `baseline/` 与执行记录。任何基线失败都会保留失败输出，不会改写旧证据。

## 本机环境初查

- `py` 启动器存在；工作区 `.venv` 为 CPython 3.14.3。
- 已安装 NumPy 2.5.4、Optiland 0.6.3、Streamlit 1.66.0、pytest 9.1.1。
- 可见内存约 31.41 GiB、12 个逻辑处理器；GPU 型号本轮初查未读到，GPU 状态仍为 `NOT_TESTED`。
- S5 的冷/热计算 profile 可作背景参考，但不替代 S6 的非共轴实测 profile。

## 保护规则

只向本 run、`docs/s6/`、`artifacts/s6/`、`_AUDIT/20261021_024715_S6_P1/` 与 `RELEASE_CANDIDATE_V2/` 写本轮证据。G0–G4、S5 run、历史 PDF、历史 ZIP 与其原始报告保持只读。新报告写入新路径；不在已有 `runs/_derived/` 或冻结 run 内写文件。
