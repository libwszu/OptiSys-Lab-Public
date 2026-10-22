"""PRE-G3-03: regression tests for the condition-stratified sub-panel.

The bug
-------
``gates/g2.py::_final_stage`` ran three loops over ``candidate_names``:

1. strategy A main panel   - binds ``design = candidate.design``
2. strategy B subset       - binds ``design = candidate.design``
3. condition-stratified    - **rebinds ``candidate`` but not ``design``**

So the third loop assembled every candidate with the design left over from the
last iteration of loop 2, which is always ``robust``.  ``_assemble`` and
``_assembly_payload`` then built a robust-geometry instrument and scored it
against baseline/nominal rows.

The fix extracts the panel construction into ``_stratified_panel_plan``, which
binds each candidate's own design by construction.

Test layers
-----------
* structural: every loop in ``_final_stage`` that assembles or builds payloads
  must bind ``design`` inside its own body.  This is what caught the bug and it
  cannot be satisfied by lucky data.
* behavioural: ``_stratified_panel_plan`` is exercised with three deliberately
  distinguishable designs; each candidate's assemblies must carry its own
  B / f / theta, and the three must be distinct.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

G2_SOURCE = Path(__file__).resolve().parents[2] / "src" / "optisys" / "gates" / "g2.py"
ROOT = Path(__file__).resolve().parents[2]


def _source_tree() -> ast.Module:
    return ast.parse(G2_SOURCE.read_text(encoding="utf-8"))


def _function_node(name: str) -> ast.FunctionDef:
    for node in ast.walk(_source_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found in {G2_SOURCE}")


def _assigns_design_from_local(loop: ast.For) -> bool:
    """``design = <something>.design`` or ``design = <name>["design"]``."""

    for child in ast.walk(loop):
        if not isinstance(child, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "design"
                   for t in child.targets):
            continue
        value = child.value
        if (isinstance(value, ast.Attribute) and value.attr == "design"):
            return True
        if (isinstance(value, ast.Subscript)
                and isinstance(value.slice, ast.Constant)
                and value.slice.value == "design"):
            return True
    return False


def _calls(node: ast.AST, names: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id in names:
                return True
    return False


def test_every_assembling_loop_binds_its_own_design() -> None:
    """No loop in ``_final_stage`` may use a design from a previous iteration."""

    final = _function_node("_final_stage")
    assembling = [
        loop for loop in ast.walk(final)
        if isinstance(loop, ast.For)
        and _calls(loop, {"_assemble", "_assembly_payload"})
    ]
    assert len(assembling) >= 3, (
        f"expected at least 3 assembling loops, found {len(assembling)}; the test "
        "itself is stale and must be updated rather than silently passing")

    bad = [loop.lineno for loop in assembling if not _assigns_design_from_local(loop)]
    assert not bad, (
        "these loops assemble units without binding their own design, so they "
        f"inherit the previous candidate's geometry: lines {bad}")


def test_stratified_plan_binds_design_per_candidate() -> None:
    """``_stratified_panel_plan`` is the extracted, provably-correct constructor."""

    plan_fn = _function_node("_stratified_panel_plan")
    loops = [node for node in ast.walk(plan_fn) if isinstance(node, ast.For)]
    assert loops, "_stratified_panel_plan must loop over candidates"
    assert all(_assigns_design_from_local(loop) for loop in loops), (
        "_stratified_panel_plan does not bind design = candidate.design")


def test_stratified_plan_independent_of_loop_order() -> None:
    """Three distinguishable designs must produce three distinct panels."""

    import math

    from optisys.config_g2 import load_config_g2
    from optisys.gates.g2 import _stratified_panel_plan
    from optisys.optimization.search_space import Design
    from optisys.tolerance.perturbations import AssemblyPerturbation

    config = load_config_g2(ROOT / "configs" / "triangulation_g2_l1.yaml")
    perturbations = [
        AssemblyPerturbation(
            assembly_id=f"FIX{index:03d}",
            d_baseline_mm=0.02 * (index % 3),
            d_theta_rad=0.0005 * index,
            d_focal_relative=0.001 * (index % 2),
            d_cx_px=0.1 * index,
            d_focus_mm=0.02 * index,
        )
        for index in range(4)
    ]

    expected = {
        "baseline": (20.0, 8.0, 0.0),
        "nominal": (15.0, 11.1, 4.0),
        "robust": (34.4, 7.272384615618831, 4.0),
    }

    class _Cand:
        def __init__(self, name: str) -> None:
            b, f, theta = expected[name]
            self.name = name
            self.design = Design(baseline_mm=b, focal_length_mm=f, theta_deg=theta)

    class _Registry:
        def __init__(self) -> None:
            self._items = {name: _Cand(name) for name in expected}

        def get(self, name: str) -> _Cand:
            return self._items[name]

    names = ("baseline", "nominal", "robust")
    plan = _stratified_panel_plan(_Registry(), names, perturbations, config)

    assert [item["name"] for item in plan] == list(names)

    fingerprints: dict[str, str] = {}
    for item in plan:
        name = item["name"]
        b, f, theta = expected[name]
        assert item["design"].baseline_mm == pytest.approx(b)
        assert item["design"].focal_length_mm == pytest.approx(f)
        assert item["design"].theta_deg == pytest.approx(theta)
        assert len(item["assemblies"]) == len(perturbations)

        for index, assembly in enumerate(item["assemblies"]):
            # the assembly inherits the candidate design plus the shared offset
            assert assembly.baseline_mm == pytest.approx(
                b + perturbations[index].d_baseline_mm)
            assert assembly.focal_length_mm == pytest.approx(
                f * (1.0 + perturbations[index].d_focal_relative))
            assert assembly.theta_rad == pytest.approx(
                math.radians(theta) + perturbations[index].d_theta_rad)

        payload = json.dumps([a.describe() for a in item["assemblies"]],
                             sort_keys=True, default=str)
        fingerprints[name] = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    assert len(set(fingerprints.values())) == 3, (
        "three distinct designs produced identical assembly panels: "
        f"{fingerprints}")


def test_stratified_measurement_rebind_bug_would_be_caught() -> None:
    """Guard the guard: a stale-design plan must be detectable.

    Simulates the historical bug by building all three panels from the robust
    design and asserts that the distinctness check above rejects it.  Without
    this, a future refactor could weaken the test and nobody would notice.
    """

    import math

    from optisys.config_g2 import load_config_g2
    from optisys.gates.g2 import _assemble
    from optisys.optimization.search_space import Design
    from optisys.tolerance.perturbations import AssemblyPerturbation

    config = load_config_g2(ROOT / "configs" / "triangulation_g2_l1.yaml")
    perturbations = [
        AssemblyPerturbation(
            assembly_id=f"FIX{index:03d}", d_baseline_mm=0.0, d_theta_rad=0.0,
            d_focal_relative=0.0, d_cx_px=0.0, d_focus_mm=0.0)
        for index in range(2)
    ]
    stale_design = Design(baseline_mm=34.4, focal_length_mm=7.272384615618831,
                          theta_deg=4.0)
    buggy_panels = [_assemble(perturbations, stale_design, config)
                    for _ in ("baseline", "nominal", "robust")]
    fingerprints = {
        name: hashlib.sha256(json.dumps([a.describe() for a in panel],
                                        sort_keys=True, default=str).encode()).hexdigest()
        for name, panel in zip(("baseline", "nominal", "robust"), buggy_panels)
    }
    assert len(set(fingerprints.values())) == 1, (
        "the stale-design simulation must produce one identical panel")
    assert not math.isnan(stale_design.theta_deg)