"""Conditionally run the frozen S5-C equal-aperture P1 position comparison."""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optisys.config_g4 import load_pump976_config
from optisys.optics.pump_optiland import OptilandPumpTracer
from optisys.optics.s5_reference import (
    build_model,
    lens_geometry_rows,
    shift_lens2_principal_plane,
    trace_rays,
)
from optisys.sources.multimode_fiber import sample_multimode_fiber
from scripts.s5_run_reference import G4, S5, _write_csv

GRID_Z_MM = (115.0, 120.0, 125.0, 130.0, 135.0)
SEARCH_N = 512
SEARCH_SEED = 976052
HOLDOUT_N = 4096
HOLDOUT_SEED = 976053
BOOTSTRAP_N = 5000
BOOTSTRAP_SEED = 976054


def _capture_fraction(ray_rows: list[dict[str, Any]]) -> float:
    total = float(sum(float(r["source_weight"]) for r in ray_rows))
    captured = float(sum(float(r["source_weight"]) for r in ray_rows
                         if r["terminal_outcome"] == "CAPTURED"))
    return captured / total


def _geometry_config(design_id: str, z_l2: float) -> tuple[Any, dict[str, Any], Any]:
    cfg_path = ROOT / "configs/pump976_g4_l0.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    loaded = load_pump976_config(cfg_path)
    beamline = replace(loaded.beamline,
                       l2=replace(loaded.beamline.l2, z_mm=float(z_l2)))
    return loaded, raw, beamline


def _optiland_trace(loaded, beamline, bundle):
    tracer = OptilandPumpTracer(beamline, wavelength_nm=loaded.wavelength_nm,
                                lens_thickness_mm=2.0, material="N-BK7")
    result = tracer.trace(bundle)
    if result.backend_version != "0.6.3" or result.status not in ("OK", "TRACE_FAILED"):
        raise RuntimeError(f"unexpected Optiland result: {result.status} / {result.message}")
    return result


def main() -> int:
    ref_verdict=json.loads((S5/"full_na_verdict.json").read_text(encoding="utf-8"))
    b_status=json.loads((S5/"s5_b_analysis_status.json").read_text(encoding="utf-8"))
    if (ref_verdict.get("status")!="PASS"
        or b_status.get("S5_A_REFERENCE_VERIFICATION")!="PASS"
        or b_status.get("S5_B_HIGH_NA_CAUSE_STATUS") not in ("EXPLAINED_WITH_SCOPE","PARTIAL")):
        result={"schema":"optisys.s5.design_status/1","run_id":"20261020_210201_S5_HNA",
                "status":"NOT_RUN_DUE_TO_SCIENTIFIC_GATE","reason":"S5-A or S5-B science gate was not satisfied"}
        (S5/"s5_c_design_status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0

    start=time.perf_counter()
    optics_json=json.loads((G4/"optics_model.json").read_text(encoding="utf-8"))
    cfg_loaded,raw,base_beamline=_geometry_config("baseline",125.0)
    base_model=build_model(optics_json,raw)
    search_bundle=sample_multimode_fiber(SEARCH_N,0.105,0.22,output_index=1.0,seed=SEARCH_SEED,
                                         angular_distribution="uniform_solid_angle")
    search_source_rows=[{"ray_id":int(search_bundle.ray_id[i]),"x0_mm":float(search_bundle.origin_mm[i,0]),
                         "y0_mm":float(search_bundle.origin_mm[i,1]),"z0_mm":float(search_bundle.origin_mm[i,2]),
                         "dx":float(search_bundle.direction[i,0]),"dy":float(search_bundle.direction[i,1]),
                         "dz":float(search_bundle.direction[i,2]),"weight":float(search_bundle.weight[i]),
                         "seed":SEARCH_SEED,"numerical_aperture":0.22,
                         "angular_distribution":"uniform_solid_angle","evidence":"SIMULATED_SEARCH"}
                        for i in range(SEARCH_N)]
    search_rows=[]
    models={}
    for z_l2 in GRID_Z_MM:
        shifted=shift_lens2_principal_plane(base_model,z_l2-125.0)
        _,ray_rows,ledger=trace_rays(shifted,search_bundle.ray_id,search_bundle.origin_mm,
                                     search_bundle.direction,search_bundle.weight,
                                     target_z_mm=225.0,target_radius_mm=1.0)
        frac=_capture_fraction(ray_rows)
        models[z_l2]=shifted
        search_rows.append({"phase":"search_512","design_id":"s5_equal_aperture_candidate" if z_l2!=125 else "baseline",
                            "l1_principal_z_mm":25.0,"l2_principal_z_mm":z_l2,
                            "l1_f_mm":25.0,"l2_f_mm":100.0,
                            "l1_clear_aperture_mm":12.0,"l2_clear_aperture_mm":12.0,
                            "l1_center_thickness_mm":2.0,"l2_center_thickness_mm":2.0,
                            "material_id":"N-BK7","target_z_mm":225.0,"target_radius_mm":1.0,
                            "lens_spacing_mm":z_l2-25.0,"search_seed":SEARCH_SEED,"n_rays":SEARCH_N,
                            "capture_fraction_input":frac,
                            "captured_weight":frac*ledger["source_weight_total"],
                            "blocked_l1_fraction":ledger["aperture_blocked_l1_weight"],
                            "blocked_l2_fraction":ledger["aperture_blocked_l2_weight"],
                            "trace_failure_weight":ledger["trace_failed_weight"]+ledger["no_intersection_weight"]
                                                    +ledger["tir_or_refraction_failure_weight"],
                            "ledger_status":ledger["status"],
                            "edge_thickness_min_mm":min(float(r["edge_thickness_mm"])
                                                         for r in lens_geometry_rows(shifted)),
                            "constraint_id":"fixed_12mm_clear_apertures_25/100mm_2mm_NBK7_target225_r1",
                            "evidence":"SIMULATED_SEARCH_NOT_HOLDOUT"})
    best=max(r["capture_fraction_input"] for r in search_rows)
    tied=[r for r in search_rows if np.isclose(r["capture_fraction_input"],best,rtol=0,atol=1e-15)]
    selected=min(tied,key=lambda r:(abs(r["l2_principal_z_mm"]-125.0),r["l2_principal_z_mm"]))
    selected_z=float(selected["l2_principal_z_mm"])

    holdout=sample_multimode_fiber(HOLDOUT_N,0.105,0.22,output_index=1.0,seed=HOLDOUT_SEED,
                                   angular_distribution="uniform_solid_angle")
    holdout_source_rows=[{"ray_id":int(holdout.ray_id[i]),"x0_mm":float(holdout.origin_mm[i,0]),
                          "y0_mm":float(holdout.origin_mm[i,1]),"z0_mm":float(holdout.origin_mm[i,2]),
                          "dx":float(holdout.direction[i,0]),"dy":float(holdout.direction[i,1]),
                          "dz":float(holdout.direction[i,2]),"weight":float(holdout.weight[i]),
                          "seed":HOLDOUT_SEED,"numerical_aperture":0.22,
                          "angular_distribution":"uniform_solid_angle","evidence":"SIMULATED_INDEPENDENT_HOLDOUT"}
                         for i in range(HOLDOUT_N)]
    holdout_models={"baseline":models[125.0],"s5_equal_aperture_candidate":models[selected_z]}
    holdout_results={}
    holdout_detail_rows=[]
    for did,model in holdout_models.items():
        _,rows,ledger=trace_rays(model,holdout.ray_id,holdout.origin_mm,holdout.direction,
                                 holdout.weight,target_z_mm=225.0,target_radius_mm=1.0)
        z_l2=125.0 if did=="baseline" else selected_z
        _,_,beamline=_geometry_config(did,z_l2)
        opti=_optiland_trace(cfg_loaded,beamline,holdout)
        by_id={int(r["ray_id"]):r for r in rows}
        pos_deltas=[];status_mismatch=0
        for idx,ray_id in enumerate(holdout.ray_id):
            rr=by_id[int(ray_id)];ox=float(opti.x_mm[idx]);oy=float(opti.y_mm[idx])
            refx=rr["target_x_mm"];refy=rr["target_y_mm"]
            delta=float(np.max(np.abs(np.array([ox,oy])-np.array([refx,refy])))) \
                if refx is not None and refy is not None and np.all(np.isfinite([ox,oy,refx,refy])) else None
            if delta is not None:pos_deltas.append(delta)
            if delta is None:opti_status="TRACE_FAILED"
            else:opti_status="CAPTURED" if opti.valid[idx] else \
                "OUTSIDE_TARGET" if str(opti.blocked_at[idx])=="TARGET" else \
                "APERTURE_BLOCKED_L1" if str(opti.blocked_at[idx])=="L1" else \
                "APERTURE_BLOCKED_L2" if str(opti.blocked_at[idx])=="L2" else "TRACE_FAILED"
            status_mismatch += int(opti_status!=rr["terminal_outcome"])
            holdout_detail_rows.append({"design_id":did,"ray_id":int(ray_id),"source_weight":float(holdout.weight[idx]),
                                 "l2_principal_z_mm":z_l2,"terminal_outcome":rr["terminal_outcome"],
                                 "optiland_terminal_outcome":opti_status,"optiland_reference_status_match":opti_status==rr["terminal_outcome"],
                                 "target_x_mm":refx,"target_y_mm":refy,"optiland_x_mm":ox,"optiland_y_mm":oy,
                                 "coordinate_delta_max_mm":delta,"evidence":"SIMULATED_HOLDOUT"})
        capture=np.asarray([r["terminal_outcome"]=="CAPTURED" for r in rows],dtype=float)
        holdout_results[did]={"rows":rows,"by_id":by_id,"ledger":ledger,"optiland":opti,
                              "capture":capture,"fraction":_capture_fraction(rows),
                              "r90_conditional":None,"coord_max":max(pos_deltas) if pos_deltas else None,
                              "terminal_mismatch":status_mismatch}

    base=holdout_results["baseline"];candidate=holdout_results["s5_equal_aperture_candidate"]
    paired_delta=candidate["capture"]-base["capture"]
    rng=np.random.default_rng(BOOTSTRAP_SEED)
    boot=np.empty(BOOTSTRAP_N,dtype=float)
    for b in range(BOOTSTRAP_N):
        index=rng.integers(0,HOLDOUT_N,size=HOLDOUT_N)
        boot[b]=float(np.mean(paired_delta[index]))
    ci=[float(np.quantile(boot,0.025)),float(np.quantile(boot,0.975))]
    mean=float(np.mean(paired_delta))
    if candidate["coord_max"] is None or candidate["coord_max"]>1e-6 or candidate["terminal_mismatch"]!=0:
        design_status="NOT_COMPARABLE"
    elif ci[0]>0.0:
        design_status="P1_SUPPORTED_TRADEOFF"
    elif ci[1]<0.0:
        design_status="NO_SUPPORTED_IMPROVEMENT"
    else:
        design_status="NOT_ENOUGH_EVIDENCE"

    comparison=[]
    for did,result in (("baseline",base),("s5_equal_aperture_candidate",candidate)):
        row={"phase":"independent_holdout_4096","design_id":did,
             "l1_principal_z_mm":25.0,"l2_principal_z_mm":125.0 if did=="baseline" else selected_z,
             "l1_f_mm":25.0,"l2_f_mm":100.0,
             "l1_clear_aperture_mm":12.0,"l2_clear_aperture_mm":12.0,
             "l1_center_thickness_mm":2.0,"l2_center_thickness_mm":2.0,
             "material_id":"N-BK7","target_z_mm":225.0,"target_radius_mm":1.0,
             "lens_spacing_mm":(125.0 if did=="baseline" else selected_z)-25.0,
             "holdout_seed":HOLDOUT_SEED,"n_rays":HOLDOUT_N,
             "capture_fraction_input":result["fraction"],
             "source_weight_denominator":result["ledger"]["source_weight_total"],
             "blocked_l1_fraction":result["ledger"]["aperture_blocked_l1_weight"],
             "blocked_l2_fraction":result["ledger"]["aperture_blocked_l2_weight"],
             "trace_failure_fraction":(result["ledger"]["trace_failed_weight"]+result["ledger"]["no_intersection_weight"]
                                       +result["ledger"]["tir_or_refraction_failure_weight"]),
             "ledger_status":result["ledger"]["status"],
             "optiland_reference_max_target_delta_mm":result["coord_max"],
             "optiland_terminal_mismatch_count":result["terminal_mismatch"],
             "edge_thickness_min_mm":min(float(r["edge_thickness_mm"])
                                          for r in lens_geometry_rows(holdout_models[did])),
             "constraint_id":"fixed_12mm_clear_apertures_25/100mm_2mm_NBK7_target225_r1",
             "evidence":"SIMULATED_HOLDOUT; ray-level not assembly-level"}
        comparison.append(row)
    paired_rows=[]
    for idx,ray_id in enumerate(holdout.ray_id):
        b=base["by_id"][int(ray_id)];c=candidate["by_id"][int(ray_id)]
        paired_rows.append({"ray_id":int(ray_id),"source_weight":float(holdout.weight[idx]),
                            "baseline_terminal_outcome":b["terminal_outcome"],
                            "candidate_terminal_outcome":c["terminal_outcome"],
                            "baseline_capture":int(base["capture"][idx]),
                            "candidate_capture":int(candidate["capture"][idx]),
                            "paired_capture_delta":float(paired_delta[idx]),
                            "l2_z_baseline_mm":125.0,"l2_z_candidate_mm":selected_z,
                            "holdout_seed":HOLDOUT_SEED,"evidence":"SIMULATED_PAIRED_HOLDOUT"})

    summary={"schema":"optisys.s5.bootstrap_summary/1","run_id":"20261020_210201_S5_HNA",
             "status":design_status,"estimand":"candidate minus baseline source-denominated capture at fixed 1mm circular target z=225mm",
             "candidate_id":"s5_equal_aperture_candidate","selected_l2_principal_z_mm":selected_z,
             "search_grid_mm":list(GRID_Z_MM),"search_seed":SEARCH_SEED,"search_rays":SEARCH_N,
             "holdout_seed":HOLDOUT_SEED,"paired_holdout_rays":HOLDOUT_N,
             "bootstrap_replicates":BOOTSTRAP_N,"bootstrap_seed":BOOTSTRAP_SEED,
             "bootstrap_type":"paired ray-resampling; sampling uncertainty only, not assembly-level tolerance",
             "baseline_capture_fraction":base["fraction"],"candidate_capture_fraction":candidate["fraction"],
             "paired_capture_difference":mean,"ci95":ci,
             "baseline_geometry":{"l1_f_mm":25,"l1_clear_aperture_mm":12,"l1_t_mm":2,
                                  "l2_f_mm":100,"l2_clear_aperture_mm":12,"l2_t_mm":2,"l2_z_mm":125},
             "candidate_geometry":{"l1_f_mm":25,"l1_clear_aperture_mm":12,"l1_t_mm":2,
                                    "l2_f_mm":100,"l2_clear_aperture_mm":12,"l2_t_mm":2,"l2_z_mm":selected_z},
             "mechanical_cost_boundary":"same optics/apertures/target; L2 position moves within registered 90-110 mm spacing range",
             "physical_tolerance_claim":"NOT_MADE","evidence":"SIMULATED_ASSUMED_P1"}

    # Keep a separate per-ray paired table; coordinate evidence is in the same
    # artifact file and every failed ray remains in the denominator.
    search_out=S5/"design_search.csv";comp_out=S5/"design_comparison.csv"
    _write_csv(search_out,search_rows);_write_csv(comp_out,comparison)
    _write_csv(S5/"design_search_source_samples.csv",search_source_rows)
    _write_csv(S5/"design_holdout_source_samples.csv",holdout_source_rows)
    _write_csv(S5/"design_holdout_ray_results.csv",holdout_detail_rows)
    _write_csv(S5/"paired_samples.csv",paired_rows)
    (S5/"bootstrap_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (S5/"s5_c_design_status.json").write_text(json.dumps({
        "schema":"optisys.s5.design_status/1","run_id":"20261020_210201_S5_HNA",
        "status":design_status,"search_rows":len(search_rows),"holdout_rows":len(comparison),
        "selected_l2_principal_z_mm":selected_z,"paired_delta":mean,"ci95":ci,
        "reason":"S5-A and S5-B gates passed; same-aperture position-only search completed under frozen plan",
        "empirical_status":"NOT_AVAILABLE"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    elapsed=time.perf_counter()-start
    (S5/"s5_c_execution.json").write_text(json.dumps({"outer_wall_s":elapsed,"hard_timeout_s":180,
                                                          "search_configs":len(search_rows),"holdout_designs":2,
                                                          "status":design_status},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":design_status,"selected_l2_z_mm":selected_z,
                      "baseline_capture":base["fraction"],"candidate_capture":candidate["fraction"],
                      "paired_delta":mean,"ci95":ci,"outer_wall_s":elapsed,
                      "search_rows":len(search_rows),"paired_rows":len(paired_rows),
                      "holdout_detail_rows":len(holdout_detail_rows)},ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
