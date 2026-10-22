# 独立复现指南

## 在 Windows 环境重跑小案例

```powershell
cd <PROJECT_ROOT>
.venv\Scripts\python.exe -m optisys validate --config configs\pump976_g4_l0.yaml
.venv\Scripts\python.exe -m optisys pump976 --rays 512 --assemblies 2
.venv\Scripts\python.exe -m optisys report --run runs\<G4_run_id>
```

低成本 run 应为 `PARTIAL`，因为它不等于注册的 100+100 assemblies；这不是错误。正式结果使用 `run/config_snapshot.yaml`、`run/split_manifest.json`、`run/provenance.json` 和源配置 hashes。

## 仅凭 ZIP 复算

在独立目录解压后：

```powershell
python repro\verify_g4.py
```

该脚本只使用 Python 标准库和 ZIP 内 CSV/JSON：重算源权重、P0 baseline target coordinates、r80/r90、source/target energy closure、tolerance 分母和 holdout summary。无需访问项目外路径或加载 OptiSys 模块。

## 校验 ZIP

```powershell
python scripts\verify_g4_audit_package.py _AUDIT\<G4_run_id>\OptiSysLab_G4_<G4_run_id>_GPT_AUDIT.zip --cross-python D:\py3.11.9\python.exe
```

脚本分别报告内容完整、独立解压复算、篡改拒绝、same-environment 与 cross-environment byte rebuild。ZIP 使用 `ZIP_STORED`，外部 sha256 sidecar 位于同目录。结果详见 `AUDIT_VERIFY_LOG.txt`。
