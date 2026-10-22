# GPT_REVIEW_INSTRUCTIONS — 给下一次独立审查的 GPT

## 角色

请作为严格的光学工程 / 科学计算 / Python 审稿审计者。不要因为作者自称 PASS 就接受结论；只依据包内可核查的证据判断。缺失证据一律记为 `NOT_VERIFIABLE`，不得猜测。

## 输入

1. `00_START_HERE.md`、`manifest.json`、`SHA256SUMS.txt`；
2. `source_spec/OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf`（18 页，重点第 2、6–13、16–17 页）；
3. `03_SCIENTIFIC_AUDIT.md`、`04_VALIDATION_MATRIX.md`、`02_SPEC_TRACEABILITY.md`；
4. `src/optisys/`、`tests/`、`configs/`、`run_evidence/`。

## 必须执行的检查

### A. 声明与状态一致性

1. `manifest.json` 的 `gate`、`run_id`、`result_status`、`scientific_claim_status` 是否与 `run_evidence/run_status.json` 一致。
2. `requirements` 是否只有 R01/R02 为 PASS；R09/R10 是否为 IN_PROGRESS；其余是否明确 TODO。若发现把未实现项标 PASS，记 **P0**。
3. `validation` 是否只有 V0 为 PASS、V6 为 PARTIAL、其余 NOT_RUN。V6 是否明确 `CI_NOT_VERIFIED`。
4. 全文搜索 `MEASURED`、`VALIDATED`、`industrial accuracy`、`high fidelity` 等措辞，确认没有越级声明。

### B. 物理与单位

5. 从 `src/optisys/geometry/coplanar.py` 的 docstring 与代码核对：
   - `X_L = B − Z tanθ`；
   - `u = cx + fx(B/Z − tanθ)`；
   - `Z = fxB/(u − cx + fx tanθ)`；
   - `du/dZ = −fxB/Z²`、`dZ/du = −Z²/(fxB)`。
6. 检查是否存在隐式单位换算（魔法数 0.00345、π/180 直接写死）。允许 `units.py` 中的命名常量，不允许散落。
7. 核对 `tests/reference/test_pdf_values.py` 的期望值是否与 PDF 第 8 页印刷值一致，而不是与实现自洽。
8. 检查 `docs/SPEC_DISCREPANCIES.md` 的 SD-001：负号推导是否成立；处理方式是否既没有篡改 PDF，也没有照抄错误符号。

### C. 独立验证是否真的独立

9. 阅读 `src/optisys/geometry/reference.py`：
   - 方向是否由旋转矩阵得到（不是 `tan`）；
   - 求交是否解 3×3 线性系统（不是点积闭式）；
   - 投影是否用 3×4 齐次矩阵；
   - 反演是否用 `scipy.optimize.brentq`；
   - 导数是否对参考链做有限差分。
   若发现参考实现调用了被测解析函数，记 **P0**（伪独立验证）。
10. 检查测试阈值是否被放宽：`U_TOLERANCE_PX = 1e-8`、`X_TOLERANCE_MM = 1e-9`、`Z_REL_TOLERANCE = 1e-9`、`DERIVATIVE_REL_TOLERANCE = 1e-5`。若阈值被事后放大，记 **P0**。

### D. 边界与错误处理

11. 抽查 `tests/unit/test_boundaries.py` 与 `run_evidence/samples/boundary_cases.csv`：
    - `B → 0`、`Z ≤ 0`、`Z = NaN/Inf`、分母接近 0、像点出界、负深度是否都有状态码；
    - 是否存在“返回 NaN 但 status=OK”的路径；
    - `OUT_OF_RANGE` 是否仍返回可被误用的数值（应只有 `visible=False` 的诊断值）。
12. 检查 `range_epsilon_mm = 1e-6` 是否只吸收舍入误差，而不是把 0.001 mm 的越界也放过（测试 `test_range_boundaries_are_inclusive` 应能区分 1e-9 与 1e-3）。

### E. 数值与图表

13. 用 `run_evidence/samples/samples.csv` 随机抽 3 行，手算 `u = cx + fx(B/Z − tanθ)`，与表中 `u_analytic_px` 比对；再检查 `u_abs_error_px` 是否为与 `u_reference_px` 的差。
14. 打开 `run_evidence/figures/fig4_independent_residual.png` 与对应 CSV，确认图示残差与数据一致，且没有把 0 残差画成虚假振荡。
15. 检查 `figures/` 是否同时提供 PNG 与绘图数据 CSV；若只有 PNG，记 P2。

### F. 计算与性能

16. 核对 `run_evidence/benchmark.json`：
    - 是否真的测试了 1/2/4/6 进程；
    - 是否固定 BLAS/OpenMP 线程为 1；
    - 1-worker 基线与多进程的比较口径是否被如实说明（IPC 成本）；
    - GPU 是否为 `NOT_TESTED`/`DISABLED`，且没有加速声明。
17. 核对 `compute_plan.json` 的 RAM 预算与 workers 决策是否与实测一致。

### G. 可复现性与包完整性

18. 运行 `python repro/verify_g0.py`，确认 `REPRO_STATUS: PASS` 且残差量级 ~1e-13 px。
19. 运行 `python scripts/verify_audit_package.py`，确认 `problems: 0`。
20. 运行 `python -m pytest -q`，确认 117 passed；若数量不同，检查是否环境差异或测试被删改。
21. 检查 `manifest.json` 的 `tests.passed` 是否等于实际；`source_pdf_sha256` 是否与 `source_spec/` 中的 PDF 一致。

### H. 反模式扫描

22. 检查是否存在：删除失败样本、只报成功帧、用不同精度比较两个方案、把仿真自洽说成实测、把 UI 当科学验证、把 Optiland 的既有功能说成自研。
23. 检查 `07_KNOWN_ISSUES_AND_FAILURES.md` 是否列出了真实失败（包括 5 个归档 run），而不是只写“无问题”。

## 输出格式

请按以下结构输出，必须给出**相对路径 + 行号或样本 ID**：

```text
GATE_REVIEW: PASS | CONDITIONAL | FAIL | NOT_VERIFIABLE

P0 致命科学问题
- [路径:行号 / 样本 ID] 问题、证据、为什么致命、最小修复

P1 必修工程问题
- ...

P2 优化建议
- ...

逐项核对
- R01: PASS/FAIL/NOT_VERIFIABLE + 证据
- R02: ...
- V0: ...
- 声明边界（是否越级）: ...
- 独立验证真实性: ...
- 数值/单位/符号: ...
- 随机性与可复现性: ...
- 计算资源声明: ...

NOT_VERIFIABLE 清单
- ...

下一阶段最小工作清单（不超过 8 条）
1. ...
```

## 判定规则

- 任一 P0 → `FAIL`；
- 无 P0 但有 P1 且影响科学声明 → `CONDITIONAL`；
- 关键证据缺失、无法运行复现 → `NOT_VERIFIABLE`；
- 只有 P2 → `PASS`，并在建议中列出。

## 禁止

- 不要因为文档写得好就判 PASS；
- 不要虚构已执行的测试或已核验的数值；
- 不要把 G0 的几何一致性解释为传感器精度；
- 不要建议“先补一个漂亮的结果图”而跳过错误处理或独立验证。
