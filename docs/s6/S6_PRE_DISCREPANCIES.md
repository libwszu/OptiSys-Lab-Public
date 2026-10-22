# S6-PRE 发现的问题与勘误登记

## 1. 发行 README 中的 PowerShell 路径

原 `RELEASE_CANDIDATE/README.md` 的虚拟环境解释器命令实际写成 `..venvScriptspython.exe`，安装、运行和报告命令均不可在 PowerShell 执行。文件在当前 Git HEAD 中是未跟踪文件；仓库没有生成该 README 的脚本（S5 封包脚本只拷贝作品说明、截图和数据），因此无法从代码证明是某种具体转义函数造成。可确认的根因是：发布文档没有可重现的源生成步骤，且把手写命令未经 PowerShell 执行检查就纳入发布包。S6 V2 将写入正确的 `\.venv\Scripts\python.exe` 形式，并加入命令路径回归检查和真实新环境执行记录；旧版本保留原样作审计对象。

## 2. S5 审计包 manifest 数量文字误差

S5 ZIP 内 `07_KNOWN_ISSUES_AND_FAILURES.md` 第 18 行写“161 manifest-covered members”；本机实查 ZIP 为 164 个成员，manifest 管理 162 个文件，另有 `manifest.json` 和 `SHA256SUMS.txt` 两个自引用例外。S6 记录此勘误，不回写 S5 ZIP 或其中的历史文件。

## 3. 两项 S5 搜索边界不是全域最优证明

S5 的 L2 `135 mm` 是 `[115,120,125,130,135] mm` 搜索的上边界；S5 焦面扫描在 `−25 mm` 边界达到 100% 捕获。S6-B 将焦面位置与 L2 镜位分开扫描；如没有内部严格极值证据，分别报告平台或未括定，不改称全域“最优”。135 mm 仍是 S6-C 预注册主要候选。

## 4. S5 非共轴证据缺口

S5 双球面参考与 Optiland 0.6.3 的对照只覆盖居中、未倾斜几何。它不能证明 decenter、tilt 后的球面交点、局部法向、共动光阑和固定接收面。S6-A 将实现局部坐标球面/折射链与独立世界坐标球面/折射链；若矩阵或负例未通过，装配 MC 停止。

## 5. 不合并历史状态

G2 `QUALIFIED_ONLY`、G4 `QUALIFIED` 与 S5 `P1_SUPPORTED_TRADEOFF` 的证据范围不同；任何 S6 软件发布状态都不能被用作物理状态升级。全程没有 S6 实测功率、真实镜片料号、实测光纤远场或实际晶体尺寸。
