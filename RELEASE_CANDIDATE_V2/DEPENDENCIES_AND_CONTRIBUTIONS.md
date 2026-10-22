# 依赖与项目贡献

## 第三方依赖

| 依赖 | 在项目中的作用 | 本轮使用版本/范围 |
|---|---|---|
| CPython | CLI、数据处理、仿真和 UI 的运行时 | `>=3.11`；S6-R 全新安装验证 3.11.9 |
| NumPy / SciPy / pandas | 向量、随机抽样、统计、几何运算和结果表 | NumPy 2.4.6 / SciPy 1.17.1 / pandas 3.0.6 |
| Optiland | 既有 P1 居中几何交叉核验依赖 | 0.6.3；非共轴 S6-A 双参考由项目代码实现 |
| Streamlit | 六页本地交互界面 | 1.66.0 |
| Matplotlib | 结果图 | 3.11.2 |
| PyYAML | YAML 配置读取 | 6.0.3 |
| psutil | 进程树 RSS、超时与清理记录 | 7.2.2 |
| pytest | 自动化测试与 JUnit 证据 | 9.1.1 |

依赖的许可与安装约束由各上游项目决定；本项目根目录 `LICENSE` 为 MIT。S6-R 实际安装版本见 `artifacts/s6r/environment/pip_freeze.txt`；安装命令为 `python -m pip install -e ".[dev,ui,optics]"`。安装结果不修改项目历史的 `requirements.lock.txt`。

## 仓库内项目贡献

- 650 nm 三角测量、CMOS/定位、校准和公差仿真流水线，以及 G2/G3 历史审计工具。
- 976 nm 光纤采样、P1 有限厚度双球面追迹、射线权重账本和 S5 名义对照。
- S6 刚体位姿、局部坐标球面与独立世界坐标球面两条追迹参考；assembly-level 配对模拟、公差登记、assembly cluster bootstrap 和 checkpoint。
- CLI、JSON/CSV provenance、HTML 报告、Streamlit 六页 UI、测试与离线 GPT 审计封包。

以上描述的是仓库实现，不代表第三方库由项目作者开发，也不暗示任何真实硬件验证。
