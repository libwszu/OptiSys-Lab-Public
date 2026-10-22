# 参与贡献

欢迎改进光电系统仿真的可复现性、CLI、界面、测试和文档。650 nm 三角测量与 976 nm 泵浦是两个独立案例；提交时请说明涉及哪条链路。

## 开发环境与检查

使用 Python 3.11，从仓库根目录创建独立环境并安装：

```bash
python -m venv .venv
# Windows 使用 .venv/Scripts/python.exe；Ubuntu/macOS 使用 .venv/bin/python
.venv/bin/python -m pip install -e ".[dev,ui,optics]"
.venv/bin/python scripts/verify_published_frozen_inputs.py
.venv/bin/python -m pytest -q tests/unit tests/reference tests/ui
.venv/bin/python repro/verify_s6r.py --root . --output artifacts/contributing/s6-science.json
```

Windows 的完整安装命令见 [README](README.md)。项目目前没有强制格式化器；遵循相邻代码风格，使用清晰的类型、单位与命名，避免无关重排。新增依赖须说明用途、版本与许可证，不主动升级冻结模型所依赖的 Optiland。

发布快照没有全部原始历史运行。云端执行的集成模块以 [ci.yml](.github/workflows/ci.yml) 为准；`test_g3_tbase`、`test_g3_tdata`、`test_g3_tfinal`、`test_g3_trepro` 需要完整历史工作区。不要把这些材料的缺失解释为科学验证通过，也不要修改断言来绕过它们。详见 [发布范围](docs/GITHUB_PUBLICATION.md)。

## 报告问题与提交修改

- Bug 请包含最小复现命令、操作系统、Python/依赖版本、预期和实际现象。分享日志前移除姓名、邮箱、本机用户路径、访问令牌和非公开数据。
- 功能需求请描述使用场景、当前困难与可验证的改进目标；涉及模型时同时写明假设和证据需求。
- 在独立分支提交小而完整的修改，在 PR 中给出实际测试命令和结果；未执行的检查标为 `NOT_RUN`。
- 安全问题遵循 [SECURITY.md](SECURITY.md)，不要在公开 Issue 粘贴漏洞细节或凭据。

## 科学证据与许可

`configs/` 中的冻结配置、`docs/g2` 至 `docs/s6r` 的历史裁决/清单、`runs/`、`_AUDIT/` 和 `RELEASE_CANDIDATE*` 是可追溯证据。未经维护者明确审查，不改写历史数据、种子、门限、配置、归档或哈希；新的实验与修复应使用新的运行标识、输出目录与清单。发现历史问题时保留原件，并另行说明更正及影响。

必须区分工程运行状态与科学结论，保留 G2 预注册 `FAIL / QUALIFIED_ONLY`、G4 条件性结论和 S6 尾部风险。仿真结果标为 `SIMULATED`；独立核验不等于实测。

只提交有权以本项目 MIT 许可分发的内容，标明第三方代码、图像或数据的来源及原许可证。不要提交个人资料、机构内部材料、厂商受限资料或密钥。依赖贡献边界见 [第三方说明](THIRD_PARTY_NOTICES.md)。
