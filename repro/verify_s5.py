"""Independent, standard-library replay for the portable Stage 5 evidence set.

Run from an extracted S5 GPT audit package with ``python repro/verify_s5.py``.
This verifier does not import Optiland, NumPy, SciPy, or project ray-tracing code.
"""

from __future__ import annotations

import csv
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "baseline_g4"
EVID = ROOT / "run_evidence"
SURFACES = ("L1_FRONT", "L1_REAR", "L2_FRONT", "L2_REAR")
ANGLE_EDGES = (0.0, 3.0, 6.0, 9.0, 11.0, 12.7099)
FOCUS_OFFSETS = (-25.0, -10.0, 0.0, 10.0, 25.0)
R_TARGETS = (0.5, 1.0, 1.5, 2.0)


class AuditError(RuntimeError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise AuditError(message)


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"required JSON missing: {path.relative_to(ROOT).as_posix()}")
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON root is not an object: {path.name}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    _require(path.is_file(), f"required CSV missing: {path.relative_to(ROOT).as_posix()}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(row: dict[str, Any], name: str) -> float:
    value = row.get(name)
    if value in (None, ""):
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"non-numeric {name}: {value!r}") from exc


def _same(actual: float, expected: float, tol: float, label: str) -> None:
    if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual - expected) > tol:
        raise AuditError(f"{label}: actual={actual!r} expected={expected!r} tol={tol:g}")


def _n_bk7(wavelength_nm: float) -> float:
    _require(300.0 <= wavelength_nm <= 2500.0, "N-BK7 wavelength outside registered range")
    u2 = (wavelength_nm / 1000.0) ** 2
    b = (1.03961212, 0.231792344, 1.01046945)
    c = (0.00600069867, 0.0200179144, 103.560653)
    return math.sqrt(1.0 + sum(x * u2 / (u2 - y) for x, y in zip(b, c)))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    return math.sqrt(_dot(v, v))


def _unit(v):
    n = _norm(v)
    _require(n > 0 and math.isfinite(n), "zero/non-finite direction")
    return tuple(x / n for x in v)


def _sphere_intersect(p, d, vertex_z, radius):
    cz = vertex_z + radius
    rel = (p[0], p[1], p[2] - cz)
    b = _dot(rel, d)
    c = _dot(rel, rel) - radius * radius
    disc = b * b - c
    if disc < 0:
        return None
    root = math.sqrt(max(disc, 0.0))
    for t in sorted((-b - root, -b + root)):
        if t <= 1e-12:
            continue
        hit = (p[0] + t*d[0], p[1] + t*d[1], p[2] + t*d[2])
        if radius * (hit[2] - cz) >= 0.0:
            continue
        residual = abs(_norm((hit[0], hit[1], hit[2]-cz)) - abs(radius))
        return t, hit, disc, residual
    return None


def _snell(d, normal, n1, n2):
    dot = _dot(d, normal)
    if dot > 1e-12:
        return None, "WRONG_INTERFACE_SIDE"
    ci = -dot
    eta = n1 / n2
    k = 1.0 - eta*eta*max(0.0, 1.0-ci*ci)
    if k < -1e-12:
        return None, "TIR_OR_REFRACTION_FAILURE"
    ct = math.sqrt(max(0.0, k))
    v = tuple(eta*d[i] + (eta*ci-ct)*normal[i] for i in range(3))
    return _unit(v), "PASS"


def _sellmeier2_power(radius_front, radius_rear, thickness, n):
    # Reduced-angle ABCD matrix; thin to thick translation occurs in n glass.
    phi1 = (n - 1.0) / radius_front
    phi2 = (1.0 - n) / radius_rear
    a1, c1 = 1.0, -phi1
    a2, b2, c2, d2 = 1.0, thickness/n, -phi2, 1.0
    # M = R2 @ T @ R1; only A and C are needed for EFL/BFL.
    a = a2*(a1 + b2*c1)
    c = c2*(a1 + b2*c1) + d2*c1
    return -1.0/c, -a/c


def _design_model(design_id, optical_model, design_configs, *, l2_z_override=None):
    if design_id == "baseline":
        key = "P1_baseline"
    elif design_id == "engineering_candidate":
        key = "P1_candidate"
    elif design_id == "s5_equal_aperture_candidate":
        key = "P1_baseline"
    else:
        raise AuditError(f"unregistered design: {design_id}")
    lens_data = optical_model["P1"]["lens_models"][key]
    cfg = design_configs[design_id]
    n = _n_bk7(float(design_configs["wavelength_nm"]))
    for lens in lens_data:
        _same(n, float(lens["index_sellmeier_976"]), 1e-12, "N-BK7 index")
    output = []
    shift = 0.0
    if design_id == "s5_equal_aperture_candidate":
        shift = float(l2_z_override) - float(design_configs["baseline"]["l2"]["principal_z_mm"])
    for i, lens in enumerate(lens_data):
        name = lens["name"]
        c = cfg["l1"] if i == 0 else cfg["l2"]
        dz = shift if i == 1 else 0.0
        row = {
            "name": name,
            "f": float(c["focal_length_mm"]),
            "diameter": float(c["clear_aperture_mm"]),
            "thickness": float(c["center_thickness_mm"]),
            "material": cfg["material_id"],
            "r1": float(lens["radius_1_mm"]),
            "r2": float(lens["radius_2_mm"]),
            "z1": float(lens["front_vertex_z_mm"]) + dz,
            "z2": float(lens["rear_vertex_z_mm"]) + dz,
            "n": n,
        }
        if design_id == "s5_equal_aperture_candidate" and i == 1:
            _same(row["z1"], float(lens["front_vertex_z_mm"]) + shift, 1e-12, "shifted L2 front z")
        _require(row["r1"] > 0 and row["r2"] < 0, f"invalid signed radii for {name}")
        efl, bfl = _sellmeier2_power(row["r1"], row["r2"], row["thickness"], n)
        _same(efl, float(lens["matrix_efl_mm"]), 1e-8, f"{name} EFL")
        _same(bfl, float(lens["matrix_bfl_mm"]), 1e-8, f"{name} BFL")
        output.append(row)
    _require(output[1]["z1"] > output[0]["z2"], "lens overlap/order violation")
    target = cfg["target"]
    target_z = float(target["z_mm"])
    target_r = float(target["active_radius_mm"])
    _require(target_z > output[1]["z2"] and target_r > 0, "target geometry invalid")
    return output, n, target_z, target_r


def _trace_ray(ray, lenses, n_glass, target_z, target_radius):
    p = (float(ray["x0_mm"]), float(ray["y0_mm"]), float(ray["z0_mm"]))
    d = _unit((float(ray["dx"]), float(ray["dy"]), float(ray["dz"])))
    theta_launch_deg=math.degrees(math.acos(max(-1.0,min(1.0,d[2]))))
    weight = float(ray["weight"])
    _require(weight > 0 and math.isfinite(weight), "source weight is not positive finite")
    surfaces = []
    terminal = "PASS" if d[2] > 0 else "INVALID_SOURCE"
    for li, lens in enumerate(lenses):
        for face in (0, 1):
            index = li*2 + face
            sid = SURFACES[index]
            radius = lens["r1"] if face == 0 else lens["r2"]
            vertex = lens["z1"] if face == 0 else lens["z2"]
            semi = lens["diameter"] / 2.0
            n1,n2 = ((1.0,n_glass) if face == 0 else (n_glass,1.0))
            result={"surface_id":sid,"status":None,"hit":None,"normal":None,"out":None,
                    "residual":None,"n1":n1,"n2":n2}
            if terminal != "PASS":
                result["status"] = "NOT_REACHED_AFTER_" + terminal
                surfaces.append(result)
                continue
            hit_result=_sphere_intersect(p,d,vertex,radius)
            if hit_result is None:
                result["status"]="NO_INTERSECTION"
                surfaces.append(result);terminal="NO_INTERSECTION";continue
            _,hit,disc,residual=hit_result
            result["hit"]=hit;result["residual"]=residual
            cz=vertex+radius
            q=_unit((hit[0],hit[1],hit[2]-cz))
            normal=tuple((1.0 if radius>0 else -1.0)*x for x in q)
            result["normal"]=normal
            if _dot(d,normal)>1e-12:
                result["status"]="WRONG_INTERFACE_SIDE"
                surfaces.append(result);terminal="TRACE_FAILED";continue
            radial=math.hypot(hit[0],hit[1])
            if radial*radial > semi*semi+1e-12:
                terminal="APERTURE_BLOCKED_L1" if li==0 else "APERTURE_BLOCKED_L2"
                result["status"]=terminal;surfaces.append(result);continue
            outgoing,status=_snell(d,normal,n1,n2)
            result["status"]=status
            if status!="PASS" or outgoing is None:
                terminal=status;surfaces.append(result);continue
            result["out"]=outgoing;surfaces.append(result)
            p,d=hit,outgoing
    tx=ty=None
    if terminal=="PASS":
        if d[2] <= 1e-14:
            terminal="NO_INTERSECTION"
        else:
            t=(target_z-p[2])/d[2]
            if t<=0:
                terminal="NO_INTERSECTION"
            else:
                tx=p[0]+t*d[0];ty=p[1]+t*d[1]
                terminal="OUTSIDE_TARGET" if tx*tx+ty*ty>target_radius*target_radius+1e-12 else "CAPTURED"
    return {"ray_id":int(ray["ray_id"]),"source_weight":weight,
            "theta_deg":theta_launch_deg,
            "source_radius_mm":math.hypot(float(ray["x0_mm"]),float(ray["y0_mm"])),
            "target_x_mm":tx,"target_y_mm":ty,"terminal_outcome":terminal,
            "exit":(p,d) if terminal in ("CAPTURED","OUTSIDE_TARGET") else None,
            "surfaces":surfaces}


def _compare_surface_record(calc, saved, design, ray_id):
    _require(calc["status"]==saved["status"],f"surface status mismatch {design}/{ray_id}/{calc['surface_id']}")
    if calc["hit"] is not None:
        for idx,axis in enumerate(("x","y","z")):
            val=_f(saved,f"hit_{axis}_mm")
            _same(calc["hit"][idx],val,1e-8,f"surface position {design}/{ray_id}/{calc['surface_id']}/{axis}")
            opfield=(f"optiland_hit_{axis}_mm" if axis in ("x","y") else "optiland_hit_z_world_mm")
            ov=_f(saved,opfield)
            _same(calc["hit"][idx],ov,1e-8,f"Optiland position {design}/{ray_id}/{calc['surface_id']}/{axis}")
        _require(calc["residual"]<=1e-8,f"sphere residual > 1e-8 mm at {design}/{ray_id}/{calc['surface_id']}")
    if calc["normal"] is not None:
        for idx,axis in enumerate(("x","y","z")):
            _same(calc["normal"][idx],_f(saved,f"normal_{axis}"),1e-9,
                  f"surface normal {design}/{ray_id}/{calc['surface_id']}/{axis}")
    if calc["out"] is not None:
        for idx,axis in enumerate(("x","y","z")):
            _same(calc["out"][idx],_f(saved,f"outgoing_d{axis}"),1e-9,
                  f"independent direction {design}/{ray_id}/{calc['surface_id']}/{axis}")
            _same(calc["out"][idx],_f(saved,f"optiland_exit_d{axis}"),1e-9,
                  f"Optiland direction {design}/{ray_id}/{calc['surface_id']}/{axis}")
    _same(calc["n1"],_f(saved,"n_before"),1e-12,"incident index")
    _same(calc["n2"],_f(saved,"n_after"),1e-12,"transmitted index")


def _weighted_quantile(values, weights, q):
    data=sorted((float(v),float(w)) for v,w in zip(values,weights) if math.isfinite(v) and w>0)
    if not data:return None
    total=sum(w for _,w in data);target=q*total;acc=0.0
    for value,weight in data:
        acc+=weight
        if acc>=target:return value
    return data[-1][0]


def _linear_quantile(values,q):
    data=sorted(values)
    if not data:return None
    pos=(len(data)-1)*q;lo=int(math.floor(pos));hi=int(math.ceil(pos));frac=pos-lo
    return data[lo]*(1-frac)+data[hi]*frac


def _audit_bootstrap(delta, seed, reps):
    # Independent stdlib resampling of the paired -1/0/+1 ray indicators.
    counts=[delta.count(-1.0),delta.count(0.0),delta.count(1.0)]
    population=[-1.0,0.0,1.0]
    weights=[float(x) for x in counts]
    rng=random.Random(seed); n=len(delta); boot=[]
    for _ in range(reps):
        sample=rng.choices(population,weights=weights,k=n)
        boot.append(sum(sample)/n)
    return [_linear_quantile(boot,.025),_linear_quantile(boot,.975)]


def verify() -> dict[str,Any]:
    optical=_read_json(BASE/"optics_model.json")
    design_configs=_read_json(ROOT/"configs/design_configs.json")
    full_samples=_read_csv(BASE/"source_samples.csv")
    g4_rows=_read_csv(BASE/"raytrace_reference.csv")
    surf_rows=_read_csv(EVID/"full_na_surface_reference.csv")
    ray_saved=_read_csv(EVID/"full_na_ray_reference.csv")
    s5_verdict=_read_json(EVID/"full_na_verdict.json")
    _require(len(full_samples)==4096,"G4 source sample row count mismatch")
    _require(len(surf_rows)==32768,"full NA surface evidence row count mismatch")
    _require(len(ray_saved)==8192,"full NA ray result row count mismatch")
    source_total=sum(float(r["weight"]) for r in full_samples)
    _same(source_total,1.0,1e-12,"G4 source weight denominator")
    surf_map={(r["design_id"],int(r["ray_id"]),r["surface_id"]):r for r in surf_rows}
    saved_ray_map={(r["design_id"],int(r["ray_id"])):r for r in ray_saved}
    g4_map={(r["design_id"],int(r["ray_id"])):r for r in g4_rows if r["angular_case"]=="NA_0.22"}
    p1_by_design={}; results=[]; max_surf=0.0; max_dir=0.0; terminal_mismatches=0

    for design_id in ("baseline","engineering_candidate"):
        lenses,n,z_target,r_target=_design_model(design_id,optical,design_configs)
        computed=[]; weights_by_outcome={}
        for source in full_samples:
            out=_trace_ray(source,lenses,n,z_target,r_target);computed.append(out)
            rid=int(source["ray_id"])
            saved=saved_ray_map[(design_id,rid)]
            _require(out["terminal_outcome"]==saved["terminal_outcome"],f"terminal mismatch {design_id}/{rid}")
            grecord=g4_map[(design_id,rid)]
            mapped=grecord["p1_status"]
            blocked=grecord.get("p1_blocked_at","")
            g4_outcome=("APERTURE_BLOCKED_L1" if blocked=="L1" else
                        "APERTURE_BLOCKED_L2" if blocked=="L2" else
                        "TRACE_FAILED" if blocked=="TRACE" else
                        "CAPTURED" if mapped=="OK" else
                        "OUTSIDE_TARGET" if mapped=="OUTSIDE_TARGET" else mapped)
            if out["terminal_outcome"]!=g4_outcome:terminal_mismatches+=1
            if out["target_x_mm"] is not None:
                _same(out["target_x_mm"],_f(saved,"target_x_mm"),1e-6,"saved target x")
                _same(out["target_y_mm"],_f(saved,"target_y_mm"),1e-6,"saved target y")
                _same(out["target_x_mm"],float(grecord["p1_x_mm"]),1e-6,"G4 target x")
                _same(out["target_y_mm"],float(grecord["p1_y_mm"]),1e-6,"G4 target y")
            for s in out["surfaces"]:
                _compare_surface_record(s,surf_map[(design_id,rid,s["surface_id"])],design_id,rid)
                if s["hit"] is not None:
                    saved_s=surf_map[(design_id,rid,s["surface_id"])]
                    dp=max(abs(s["hit"][i]-_f(saved_s,f"optiland_hit_{a}_mm" if a in ("x","y") else "optiland_hit_z_world_mm"))
                           for i,a in enumerate(("x","y","z")))
                    max_surf=max(max_surf,dp)
                if s["out"] is not None:
                    saved_s=surf_map[(design_id,rid,s["surface_id"])]
                    dd=max(abs(s["out"][i]-_f(saved_s,f"optiland_exit_d{a}"))
                           for i,a in enumerate(("x","y","z")))
                    max_dir=max(max_dir,dd)
            weights_by_outcome[out["terminal_outcome"]]=weights_by_outcome.get(out["terminal_outcome"],0.0)+out["source_weight"]
        p1_by_design[design_id]=computed
        _require(sum(weights_by_outcome.values())==source_total,"source outcome ledger is not closed")
        declared=next(x for x in s5_verdict["designs"] if x["design_id"]==design_id)
        _same(weights_by_outcome["CAPTURED"],declared["ledger"]["captured_weight"],1e-12,"captured source weight")
        _same(weights_by_outcome.get("OUTSIDE_TARGET",0.0),declared["ledger"]["outside_target_weight"],1e-12,"outside target source weight")
        results.append({"design_id":design_id,"n_rays":len(computed),"terminal_weights":weights_by_outcome,
                        "capture_fraction":weights_by_outcome["CAPTURED"]/source_total,
                        "ledger_residual":source_total-sum(weights_by_outcome.values())})

    _require(terminal_mismatches==0,"G4 terminal outcomes differ from independent replay")
    _require(max_surf<=1e-8 and max_dir<=1e-9,"surface/exit-state delta exceeds registered tolerance")

    # Angle-resolved P0/P1 capture with an all-source-weight denominator.
    angle_table=_read_csv(EVID/"angle_resolved_p0_p1_capture.csv")
    angle_map={(r["design_id"],r["angle_bin"]):r for r in angle_table}
    for design_id in ("baseline","engineering_candidate"):
        for lo,hi in zip(ANGLE_EDGES[:-1],ANGLE_EDGES[1:]):
            subset=[]
            for src in full_samples:
                theta=math.degrees(math.acos(max(-1.0,min(1.0,float(src["dz"])))))
                if lo<=theta<hi or (hi==ANGLE_EDGES[-1] and theta<=hi):subset.append(src)
            label=f"{lo:g}-{hi:g}deg";denom=sum(float(r["weight"]) for r in subset)
            p1cap=sum(float(r["source_weight"]) for r in p1_by_design[design_id]
                      if _angle_group(float(r["theta_deg"]))==label and r["terminal_outcome"]=="CAPTURED")
            original=[g4_map[(design_id,int(r["ray_id"]))] for r in subset]
            p0cap=sum(float(r["weight"]) for r in original if r["p0_status"]=="OK")
            row=angle_map[(design_id,label)]
            _same(_f(row,"p1_capture_fraction_within_angle"),p1cap/denom,1e-12,"angle-bin P1 capture")
            _same(_f(row,"p0_capture_fraction_within_angle"),p0cap/denom,1e-12,"angle-bin P0 capture")

    # Target geometry and unconditional encircled-weight curves.
    target_rows=_read_csv(EVID/"target_geometry_sensitivity.csv")
    for row in target_rows:
        did=row["design_id"];model=row["model_level"];geometry=row["geometry"]
        radius=float(row["target_radius_mm"]) if row["target_radius_mm"] else None
        cap=0.0
        if model=="P1_INDEPENDENT":
            candidates=p1_by_design[did]
            for r in candidates:
                if r["target_x_mm"] is None:continue
                x,y=r["target_x_mm"],r["target_y_mm"]
                inside=(x*x+y*y<=radius*radius+1e-12) if geometry=="circle" else (abs(x)<=1.0+1e-12 and abs(y)<=1.0+1e-12)
                if inside:cap+=r["source_weight"]
        else:
            for src in full_samples:
                gr=g4_map[(did,int(src["ray_id"]))]
                if gr["p0_status"] not in ("OK","OUTSIDE_TARGET"):continue
                x,y=float(gr["p0_x_mm"]),float(gr["p0_y_mm"])
                inside=(x*x+y*y<=radius*radius+1e-12) if geometry=="circle" else (abs(x)<=1+1e-12 and abs(y)<=1+1e-12)
                if inside:cap+=float(src["weight"])
        _same(cap/source_total,_f(row,"capture_fraction_input"),1e-12,"target sensitivity capture")

    enc_rows=_read_csv(EVID/"encircled_weight.csv")
    for row in enc_rows:
        radius=float(row["radius_mm"]);did=row["design_id"];model=row["model_level"];enc=0.0
        if model=="P1_INDEPENDENT":
            for r in p1_by_design[did]:
                if r["target_x_mm"] is not None and r["target_x_mm"]**2+r["target_y_mm"]**2<=radius*radius+1e-12:
                    enc+=r["source_weight"]
        else:
            for src in full_samples:
                gr=g4_map[(did,int(src["ray_id"]))]
                if gr["p0_status"] in ("OK","OUTSIDE_TARGET") and float(gr["p0_x_mm"])**2+float(gr["p0_y_mm"])**2<=radius*radius+1e-12:
                    enc+=float(src["weight"])
        _same(enc/source_total,_f(row,"encircled_weight_fraction_input"),1e-12,"encircled input weight")

    # Mechanical sag/edge thickness, independent of the optical ray loop.
    geometry_rows=_read_csv(EVID/"lens_geometry_feasibility.csv")
    for row in geometry_rows:
        r1=abs(float(row["radius_front_mm"]));r2=abs(float(row["radius_rear_mm"]))
        a=float(row["clear_aperture_diameter_mm"])/2.0;t=float(row["center_thickness_mm"])
        s1=r1-math.sqrt(r1*r1-a*a);s2=r2-math.sqrt(r2*r2-a*a)
        edge=t-s1-s2
        _require(edge>0.0,f"non-positive lens edge thickness in {row['design_id']}/{row['lens_id']}")
        _same(edge,_f(row,"edge_thickness_mm"),1e-9,"lens edge thickness")

    # Focus re-traces: propagate independent L2-rear exits to every registered plane.
    focus_rows=_read_csv(EVID/"focus_sweep.csv")
    for row in focus_rows:
        did=row["design_id"];offset=float(row["focus_offset_from_as_built_mm"])
        cfg=design_configs[did];z_target=float(cfg["target"]["z_mm"])+offset
        capture=0.0
        for ray in p1_by_design[did]:
            if ray["exit"] is None:continue
            p,d=ray["exit"];t=(z_target-p[2])/d[2]
            if t>0:
                x,y=p[0]+t*d[0],p[1]+t*d[1]
                if x*x+y*y<=1.0+1e-12:capture+=ray["source_weight"]
        _same(capture/source_total,_f(row,"capture_fraction_input"),1e-12,"focus-sweep capture")

    # Source-distribution sensitivity, using raw saved input rays and fixed lens geometry.
    sens_source=_read_csv(EVID/"source_assumption_source_samples.csv")
    sens_ref=_read_csv(EVID/"source_assumption_ray_reference.csv")
    sens_map={(r["numerical_aperture"],r["angular_distribution"],int(r["ray_id"])):r for r in sens_ref}
    sens_out=[]
    for na,angular in ((0.05,"uniform_solid_angle"),(0.22,"uniform_solid_angle"),(0.22,"edge_biased_sin_theta")):
        inputs=[r for r in sens_source if abs(float(r["numerical_aperture"])-na)<1e-12 and r["angular_distribution"]==angular]
        lens,n,z,rt=_design_model("baseline",optical,design_configs)
        outs=[]
        for ray in inputs:outs.append(_trace_ray(ray,lens,n,z,rt))
        capture=sum(r["source_weight"] for r in outs if r["terminal_outcome"]=="CAPTURED")
        for out in outs:
            saved=sens_map[(str(na),angular,int(out["ray_id"]))]
            _require(out["terminal_outcome"]==saved["terminal_outcome"],"source sensitivity ray outcome mismatch")
            if out["target_x_mm"] is not None:
                _same(out["target_x_mm"],_f(saved,"target_x_mm"),1e-6,"source sensitivity target x")
                _same(out["target_y_mm"],_f(saved,"target_y_mm"),1e-6,"source sensitivity target y")
        expected=next(r for r in _read_csv(EVID/"source_assumption_sensitivity.csv")
                      if abs(float(r["numerical_aperture"])-na)<1e-12 and r["angular_distribution"]==angular)
        _same(capture/sum(float(r["weight"]) for r in inputs),_f(expected,"p1_capture_fraction_input"),1e-12,"source sensitivity capture")
        sens_out.append({"na":na,"angular_distribution":angular,"capture":capture})

    # Equal-aperture position search and independent holdout.
    config=design_configs["s5_equal_aperture_candidate"]
    search_source=_read_csv(EVID/"design_search_source_samples.csv")
    search_rows=_read_csv(EVID/"design_search.csv")
    search_capture=[]
    for zrow in search_rows:
        z=float(zrow["l2_principal_z_mm"])
        lenses,n,zt,rt=_design_model("s5_equal_aperture_candidate",optical,design_configs,l2_z_override=z)
        out=[_trace_ray(ray,lenses,n,225.0,1.0) for ray in search_source]
        captured=sum(r["source_weight"] for r in out if r["terminal_outcome"]=="CAPTURED")
        _same(captured/_sum_weights(search_source),_f(zrow,"capture_fraction_input"),1e-12,"candidate search capture")
        search_capture.append((z,captured/_sum_weights(search_source)))
    best=max(x[1] for x in search_capture)
    tied=[x for x in search_capture if abs(x[1]-best)<=1e-15]
    selected=min(tied,key=lambda x:(abs(x[0]-125.0),x[0]))[0]
    bootstrap=_read_json(EVID/"bootstrap_summary.json")
    _same(selected,float(bootstrap["selected_l2_principal_z_mm"]),1e-12,"selected candidate position")

    holdout=_read_csv(EVID/"design_holdout_source_samples.csv")
    holdout_base=[_trace_ray(r,*_design_model("baseline",optical,design_configs)[0:1],) for r in []] if False else None
    base_lens,base_n,_,_=_design_model("baseline",optical,design_configs)
    cand_lens,cand_n,_,_=_design_model("s5_equal_aperture_candidate",optical,design_configs,l2_z_override=selected)
    base_results=[_trace_ray(r,base_lens,base_n,225.0,1.0) for r in holdout]
    cand_results=[_trace_ray(r,cand_lens,cand_n,225.0,1.0) for r in holdout]
    paired=_read_csv(EVID/"paired_samples.csv")
    _require(len(paired)==len(holdout)==4096,"paired holdout row count mismatch")
    holdout_detail=_read_csv(EVID/"design_holdout_ray_results.csv")
    _require(len(holdout_detail)==8192,"holdout per-ray detail row count mismatch")
    detail_map={(r["design_id"],int(r["ray_id"])):r for r in holdout_detail}
    deltas=[]
    for index,(b,c,p) in enumerate(zip(base_results,cand_results,paired)):
        _require(b["terminal_outcome"]==p["baseline_terminal_outcome"],"paired baseline outcome mismatch")
        _require(c["terminal_outcome"]==p["candidate_terminal_outcome"],"paired candidate outcome mismatch")
        delta=float(c["terminal_outcome"]=="CAPTURED")-float(b["terminal_outcome"]=="CAPTURED")
        _same(delta,_f(p,"paired_capture_delta"),0.0,"paired capture delta")
        deltas.append(delta)
        for did,out in (("baseline",b),("s5_equal_aperture_candidate",c)):
            saved=detail_map[(did,int(out["ray_id"]))]
            _require(out["terminal_outcome"]==saved["terminal_outcome"],"candidate holdout terminal detail mismatch")
            if out["target_x_mm"] is not None:
                _same(out["target_x_mm"],_f(saved,"target_x_mm"),1e-6,"holdout target x")
                _same(out["target_y_mm"],_f(saved,"target_y_mm"),1e-6,"holdout target y")
                _require(_f(saved,"coordinate_delta_max_mm")<=1e-6,"holdout independent/Optiland coordinate mismatch")
                _require(saved["optiland_reference_status_match"]=="True","holdout Optiland status mismatch")
    observed=sum(deltas)/len(deltas)
    _same(observed,float(bootstrap["paired_capture_difference"]),1e-12,"paired holdout difference")
    approx_ci=_audit_bootstrap(deltas,int(bootstrap["bootstrap_seed"]),int(bootstrap["bootstrap_replicates"]))
    stored_ci=bootstrap["ci95"]
    _require(abs(approx_ci[0]-float(stored_ci[0]))<=0.005 and abs(approx_ci[1]-float(stored_ci[1]))<=0.005,
             f"independent ray bootstrap disagrees: {approx_ci} vs {stored_ci}")

    return {"S5_A_REFERENCE_VERIFICATION":"PASS","S5_B_HIGH_NA_CAUSE_STATUS":"EXPLAINED_WITH_SCOPE",
            "S5_C_DESIGN_STATUS":bootstrap["status"],"designs":results,
            "full_na_surface_rows":len(surf_rows),"full_na_final_ray_rows":len(ray_saved),
            "max_surface_coordinate_delta_mm":max_surf,"max_surface_direction_delta":max_dir,
            "terminal_mismatches_against_g4":terminal_mismatches,
            "target_geometry_rows_verified":len(target_rows),"encircled_weight_rows_verified":len(enc_rows),
            "mechanical_geometry_rows_verified":len(geometry_rows),"focus_rows_verified":len(focus_rows),
            "source_sensitivity_cases_verified":len(sens_out),"candidate_search_rows_verified":len(search_rows),
            "selected_l2_principal_z_mm":selected,"holdout_paired_rows_verified":len(paired),
            "paired_capture_difference":observed,"paired_bootstrap_ci95_stdlib_independent":approx_ci,
            "audit_repro":"PASS"}


def _sum_weights(rows):
    return sum(float(r["weight"]) for r in rows)


def _angle_group(theta):
    for i,(lo,hi) in enumerate(zip(ANGLE_EDGES[:-1],ANGLE_EDGES[1:])):
        if lo<=theta<hi or (i==len(ANGLE_EDGES)-2 and theta<=hi):return f"{lo:g}-{hi:g}deg"
    return "OUTSIDE_REGISTERED_ANGLE_RANGE"


ANGLE_EDGES=(0.0,3.0,6.0,9.0,11.0,12.7099)


def main() -> int:
    try:
        result=verify()
    except Exception as exc:
        print(f"REPRO_STATUS: FAIL\n{type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print("REPRO_STATUS: PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
