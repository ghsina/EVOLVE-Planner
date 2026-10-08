"""Hybrid offshore-onshore capacity-expansion model (Pyomo LP/MILP).

Physics and cost structure follow the v9 model (AAU EVOLVE WP2). The time
axis is a ``TimeStructure``: the full hourly year, or the TDA blocks of
``tda.tpca`` (variable-length steps in calendar order).

Additions for the planner:
  * technology switches (any asset can be excluded);
  * sea area for wind and PV and deck area for island equipment, as two
    separate limits;
  * electricity revenue as PPA, merchant (hourly price) or two-sided CfD;
  * delivery as an annual volume, a firm hourly band, or an hourly profile;
  * shortfall slacks (used to verify a design on the full year);
  * per-component cost breakdown and hourly result extraction.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pyomo.environ as pyo

from .params import crf
from .timestructure import TimeStructure

CAP_VARS = ["C_wt", "C_pv", "C_ez_off", "C_ez_on", "C_cmp_off", "C_cmp_on", "C_fc_off",
            "C_fc_on", "C_cab", "E_bat_off", "P_bat_off", "E_bat_on", "P_bat_on",
            "E_tank_off", "E_tank_on"]
FLOWS = ["p_we", "p_cab_f", "p_cab_r", "p_curt_off", "bat_off_ch", "bat_off_dis",
         "h2_off", "h2_pipe", "h2fc_off", "tank_off_in", "tank_off_out", "p_pe", "p_grid",
         "bat_on_ch", "bat_on_dis", "h2_on", "h2fc_on", "h2_sell", "tank_on_in", "tank_on_out"]


def build(ts: TimeStructure, p: dict, allow_shortfall: bool = False, relax_pipe: bool = False):
    R, L = ts.R, ts.L
    sw = ts.sw * ts.dt                      # hours represented by each step
    W = ts.weight_r()                       # occurrences of each period per year
    wt, pv = ts.reps["wind_cf"], ts.reps["pv_cf"]
    price = ts.reps.get("price")
    m = pyo.ConcreteModel()
    m.R = pyo.RangeSet(0, R - 1)
    m.H = pyo.RangeSet(0, L - 1)
    m.B = pyo.RangeSet(0, L)
    m.S = pyo.RangeSet(0, len(ts.slots) - 1)
    NN = pyo.NonNegativeReals
    ub, rub = p["cap_ub_mw"], p["cap_renewable_ub_mw"]
    Bt, Tk = p["batt"], p["tank"]
    on = lambda key: ub if p.get(key, True) else 0.0

    # ---- capacities -----------------------------------------------------------
    m.C_wt = pyo.Var(bounds=(0, rub))
    m.C_pv = pyo.Var(bounds=(0, rub if p["enable_pv"] else 0.0))
    m.C_ez_off = pyo.Var(bounds=(0, on("enable_ez_off")))
    m.C_ez_on = pyo.Var(bounds=(0, on("enable_ez_on")))
    m.C_cmp_off = pyo.Var(bounds=(0, ub if p["pipe_allowed"] else 0.0))
    m.C_cmp_on = pyo.Var(bounds=(0, on("enable_ez_on")))
    m.C_fc_off = pyo.Var(bounds=(0, on("enable_fc_off")))
    m.C_fc_on = pyo.Var(bounds=(0, on("enable_fc_on")))
    m.C_cab = pyo.Var(bounds=(0, ub if p["elec_export_allowed"] else 0.0))
    m.E_bat_off = pyo.Var(bounds=(0, Bt["off"]["max_e"])); m.P_bat_off = pyo.Var(bounds=(0, Bt["off"]["max_p"]))
    m.E_bat_on = pyo.Var(bounds=(0, Bt["on"]["max_e"])); m.P_bat_on = pyo.Var(bounds=(0, Bt["on"]["max_p"]))
    m.E_tank_off = pyo.Var(bounds=(0, Tk["off"]["max_kg"])); m.E_tank_on = pyo.Var(bounds=(0, Tk["on"]["max_kg"]))
    m.K = pyo.Set(initialize=p["pipe_allowed"])
    m.y_pipe = pyo.Var(m.K, domain=pyo.UnitInterval if relax_pipe else pyo.Binary)
    if p["pipe_allowed"]:
        m.one_pipe = pyo.Constraint(expr=sum(m.y_pipe[k] for k in m.K) <= 1)

    # ---- operation --------------------------------------------------------------
    for n in FLOWS:
        setattr(m, n, pyo.Var(m.R, m.H, domain=NN))
    ce, comp, fc, h2k = p["cable_eff"], p["comp_mwh_per_kg"], p["fc_mwh_per_kg"], p["h2_kg_per_mwh"]
    gen = lambda r, h: m.C_wt * float(wt[r, h]) + m.C_pv * float(pv[r, h])

    m.off_bal = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        gen(r, h) + ce * mm.p_cab_r[r, h] + fc * mm.h2fc_off[r, h] + mm.bat_off_dis[r, h]
        == mm.p_we[r, h] + comp * mm.h2_pipe[r, h] + mm.p_cab_f[r, h] + mm.p_curt_off[r, h] + mm.bat_off_ch[r, h])
    m.on_bal = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        ce * mm.p_cab_f[r, h] + fc * mm.h2fc_on[r, h] + mm.bat_on_dis[r, h]
        == mm.p_pe[r, h] + comp * mm.h2_on[r, h] + mm.p_cab_r[r, h] + mm.p_grid[r, h] + mm.bat_on_ch[r, h])
    m.off_h2 = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        mm.h2_off[r, h] + mm.tank_off_out[r, h] == mm.h2_pipe[r, h] + mm.h2fc_off[r, h] + mm.tank_off_in[r, h])
    m.on_h2 = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        mm.h2_on[r, h] + p["pipeline_efficiency"] * mm.h2_pipe[r, h] + mm.tank_on_out[r, h]
        == mm.h2_sell[r, h] + mm.h2fc_on[r, h] + mm.tank_on_in[r, h])
    m.off_prod = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.h2_off[r, h] == h2k * mm.p_we[r, h])
    m.on_prod = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.h2_on[r, h] == h2k * mm.p_pe[r, h])
    lim = [("p_we", "C_ez_off", 1.0), ("p_pe", "C_ez_on", 1.0), ("h2_pipe", "C_cmp_off", comp),
           ("h2_on", "C_cmp_on", comp), ("h2fc_off", "C_fc_off", fc), ("h2fc_on", "C_fc_on", fc),
           ("p_cab_f", "C_cab", 1.0), ("p_cab_r", "C_cab", 1.0), ("bat_off_ch", "P_bat_off", 1.0),
           ("bat_off_dis", "P_bat_off", 1.0), ("bat_on_ch", "P_bat_on", 1.0), ("bat_on_dis", "P_bat_on", 1.0)]
    for i, (v, c, f) in enumerate(lim):
        setattr(m, f"lim_{i}", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h, v=v, c=c, f=f:
                f * getattr(mm, v)[r, h] <= getattr(mm, c)))
    if comp <= 0:      # no compression needed: pipe flow still limited by the pipe only
        pass
    m.lim_pipe = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        mm.h2_pipe[r, h] <= sum(p["pipe_classes"][k]["cap_kgh"] * mm.y_pipe[k] for k in mm.K))
    m.lim_grid = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.p_grid[r, h] <= p["grid_injection_cap_mw"])
    m.lim_curt = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.p_curt_off[r, h] <= gen(r, h))
    if p["config"] == "C_floating_decentralized":
        m.dec_ez = pyo.Constraint(expr=m.C_ez_off <= m.C_wt + m.C_pv)

    # ---- deliveries ----------------------------------------------------------------------
    hours = lambda r, h: float(W[r] * sw[h])
    annual = lambda var: sum(hours(r, h) * var[r, h] for r in m.R for h in m.H)
    if allow_shortfall:
        m.short_e = pyo.Var(m.R, m.H, domain=NN); m.short_h = pyo.Var(m.R, m.H, domain=NN)
        m.short_ey = pyo.Var(domain=NN); m.short_hy = pyo.Var(domain=NN)
    volume_free = p["elec_revenue"] in ("merchant", "cfd")

    def deliver(tag, var, D, mode, profile_key, sh_rh, sh_y):
        if mode == "profile" and profile_key in ts.reps:
            prof = ts.reps[profile_key]
            setattr(m, f"prof_{tag}", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
                    var[r, h] + (sh_rh[r, h] if allow_shortfall else 0) == float(prof[r, h])))
        elif D <= 0:
            return
        elif mode == "firm":
            setattr(m, f"firm_{tag}", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
                    var[r, h] + (sh_rh[r, h] if allow_shortfall else 0) == D / 8760.0))
        else:
            setattr(m, f"annual_{tag}", pyo.Constraint(expr=annual(var) + (sh_y if allow_shortfall else 0) == D))

    if not volume_free:
        deliver("e", m.p_grid, p["annual_demand_mwh"], p["elec_delivery"], "elec_demand",
                getattr(m, "short_e", None), getattr(m, "short_ey", None))
    deliver("h", m.h2_sell, p["annual_h2_demand_kg"], p["h2_delivery"], "h2_demand",
            getattr(m, "short_h", None), getattr(m, "short_hy", None))

    # ---- storage: Kotzur min/max bounds (exact for loss-free storage) ------------------------
    slots = ts.slots
    nS = len(slots)

    def storage(name, cap, inflow, outflow, eta_in, eta_out):
        start = pyo.Var(m.S, domain=NN); dev = pyo.Var(m.R, m.B, domain=pyo.Reals)
        dmin = pyo.Var(m.R, domain=pyo.Reals); dmax = pyo.Var(m.R, domain=pyo.Reals)
        for n, o in (("start", start), ("dev", dev), ("dmin", dmin), ("dmax", dmax)):
            setattr(m, f"{name}_{n}", o)
        setattr(m, f"{name}_d0", pyo.Constraint(m.R, rule=lambda mm, r: dev[r, 0] == 0))
        setattr(m, f"{name}_dyn", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
                dev[r, h + 1] == dev[r, h] + float(sw[h]) * (eta_in * inflow[r, h] - outflow[r, h] / eta_out)))
        setattr(m, f"{name}_lo", pyo.Constraint(m.R, m.B, rule=lambda mm, r, b: dmin[r] <= dev[r, b]))
        setattr(m, f"{name}_hi", pyo.Constraint(m.R, m.B, rule=lambda mm, r, b: dev[r, b] <= dmax[r]))
        setattr(m, f"{name}_link", pyo.Constraint(m.S, rule=lambda mm, s:
                start[(s + 1) % nS] == start[s] + slots[s][1] * dev[slots[s][0], L]))
        cons = pyo.ConstraintList()
        setattr(m, f"{name}_bnd", cons)
        for s, (r, w, _) in enumerate(slots):
            k_last = max(int(math.ceil(w - 1e-9)) - 1, 0)
            for k in sorted({0, k_last}):
                cons.add(start[s] + k * dev[r, L] + dmin[r] >= 0)
                cons.add(start[s] + k * dev[r, L] + dmax[r] <= cap)

    storage("bat_off", m.E_bat_off, m.bat_off_ch, m.bat_off_dis, Bt["off"]["eta_ch"], Bt["off"]["eta_dis"])
    storage("bat_on", m.E_bat_on, m.bat_on_ch, m.bat_on_dis, Bt["on"]["eta_ch"], Bt["on"]["eta_dis"])
    storage("tank_off", m.E_tank_off, m.tank_off_in, m.tank_off_out, 1.0, 1.0)
    storage("tank_on", m.E_tank_on, m.tank_on_in, m.tank_on_out, 1.0, 1.0)

    # ---- space: sea area for generation, deck area for island equipment ---------------------
    m.sea_area = pyo.Constraint(expr=m.C_wt / p["wind_density_mw_km2"] + m.C_pv / p["pv_density_mw_km2"]
                                <= p["sea_area_km2"])
    m.deck_area = pyo.Constraint(expr=p["area_elec_m2_mw"] * m.C_ez_off + p["area_comp_m2_mw"] * m.C_cmp_off
        + p["area_fc_m2_mw"] * m.C_fc_off + p["area_batt_m2_mwh"] * m.E_bat_off
        + p["area_tank_m2_kg"] * m.E_tank_off <= p["deck_area_max_m2"])
    m.area_on = pyo.Constraint(expr=p["area_elec_m2_mw"] * m.C_ez_on + p["area_comp_m2_mw"] * m.C_cmp_on
        + p["area_fc_m2_mw"] * m.C_fc_on + p["area_batt_m2_mwh"] * m.E_bat_on
        + p["area_tank_m2_kg"] * m.E_tank_on <= p["area_onshore_max_m2"])

    # ---- costs -------------------------------------------------------------------------------
    op = p["offshore_premium"]
    plat = 1e3 * p["platform_install_factor"] * p["platform_float_factor"]
    cx = {
        "Offshore wind": (p["wind_capex_eur_mw"] * m.C_wt, p["wind_life"], p["wind_fom"]),
        "Floating PV": (p["pv_capex_eur_kw"] * 1e3 * m.C_pv, p["pv_life"], p["pv_fom"]),
        "Electrolyser (island)": (p["elec_capex_eur_kw"] * 1e3 * op * m.C_ez_off, p["elec_life"], p["elec_fom"]),
        "Electrolyser (onshore)": (p["elec_capex_eur_kw"] * 1e3 * m.C_ez_on, p["elec_life"], p["elec_fom"]),
        "Water treatment": (p["wt_capex_eur_mw"] * (m.C_ez_off + m.C_ez_on), p["wt_life"], p["wt_fom"]),
        "Compressors": (p["comp_capex_eur_mw"] * (op * m.C_cmp_off + m.C_cmp_on), p["comp_life"], p["comp_fom"]),
        "Fuel cells": (p["fc_capex_eur_kw"] * 1e3 * (op * m.C_fc_off + m.C_fc_on), p["fc_life"], p["fc_fom"]),
        "Export cable": (p["cable_capex_eur_mw"] * m.C_cab, p["cable_life"], p["cable_fom"]),
        "H2 pipeline": (sum(p["pipe_classes"][k]["capex_per_km"] * p["pipe_distance_km"] * m.y_pipe[k] for k in m.K),
                        p["pipeline_life"], p["pipeline_fom"]),
        "Island platform": ((p["platform_cable_coef"] * m.C_cab + p["platform_elec_coef"]
                             * (m.C_ez_off + m.C_cmp_off + m.C_fc_off + m.P_bat_off)) * plat,
                            p["platform_life"], p["platform_fom"]),
        "Batteries": (Bt["off"]["capex_e"] * m.E_bat_off + Bt["off"]["capex_p"] * m.P_bat_off
                      + Bt["on"]["capex_e"] * m.E_bat_on + Bt["on"]["capex_p"] * m.P_bat_on,
                      Bt["on"]["life"], Bt["on"]["fom"]),
        "H2 tanks": (Tk["off"]["capex_kg"] * m.E_tank_off + Tk["on"]["capex_kg"] * m.E_tank_on,
                     Tk["on"]["life"], Tk["on"]["fom"]),
    }
    r_ = p["discount_rate"]
    m.cost_parts = {k: pyo.Expression(expr=e * (crf(r_, n) + f)) for k, (e, n, f) in cx.items()}
    for k, e in m.cost_parts.items():
        m.add_component("cp_" + "".join(ch for ch in k if ch.isalnum()), e)
    m.capex_total = pyo.Expression(expr=sum(e for e, _, _ in cx.values()))
    m.tso = pyo.Expression(expr=p["tso_fee"] * m.C_cab)
    m.ann_vom = pyo.Expression(expr=Bt["on"]["vom"] * (annual(m.bat_off_dis) + annual(m.bat_on_dis))
                               + Tk["on"]["vom"] * (annual(m.tank_off_in) + annual(m.tank_on_in)))
    if p["elec_revenue"] == "merchant":
        m.rev_e = pyo.Expression(expr=sum(hours(r, h) * float(price[r, h]) * m.p_grid[r, h] for r in m.R for h in m.H))
    elif p["elec_revenue"] == "cfd":
        strike = p["cfd_strike_eur_mwh"]
        m.rev_e = pyo.Expression(expr=sum(hours(r, h) * (strike if price[r, h] >= 0 else float(price[r, h]))
                                          * m.p_grid[r, h] for r in m.R for h in m.H))
    elif p["elec_revenue"] == "ppa":
        m.rev_e = pyo.Expression(expr=p["ppa_price_eur_mwh"] * annual(m.p_grid))
    else:
        m.rev_e = pyo.Expression(expr=0.0)
    m.rev_h = pyo.Expression(expr=p["h2_price_eur_kg"] * annual(m.h2_sell))
    pen = 0.0
    if allow_shortfall:
        pen = (p["shortfall_penalty_eur_mwh"] * (annual(m.short_e) + m.short_ey)
               + p["shortfall_penalty_eur_kg"] * (annual(m.short_h) + m.short_hy))
    m.penalty = pyo.Expression(expr=pen)
    m.total_cost = pyo.Expression(expr=sum(m.cost_parts.values()) + m.tso + m.ann_vom)
    m.net_cost = pyo.Expression(expr=m.total_cost - m.rev_e - m.rev_h + m.penalty)
    m.obj = pyo.Objective(expr=m.net_cost, sense=pyo.minimize)
    m._ts, m._p, m._hours = ts, p, np.outer(W, sw)
    return m


# ---------------------------------------------------------------------------
# solving
# ---------------------------------------------------------------------------

def _solver(name: str, ipm: bool):
    if name == "highs":
        from pyomo.contrib.appsi.solvers import Highs
        s = Highs()
        s.highs_options["presolve"] = "on"
        s.highs_options["threads"] = 1
        if ipm:
            s.highs_options["solver"] = "ipm"
            s.highs_options["run_crossover"] = "on"
        s.config.load_solution = False
        return s
    if name == "glpk":
        s = pyo.SolverFactory("glpk")
        s.options["tmlim"] = 3600
        return s
    raise ValueError(name)


def solve(m, solver: str = "highs") -> dict:
    t0 = time.time()
    if solver == "highs":
        res = _solver("highs", True).solve(m)
        ok = res.termination_condition.name == "optimal"
        if not ok:      # IPM can misreport badly scaled LPs; confirm with simplex
            res = _solver("highs", False).solve(m)
            ok = res.termination_condition.name == "optimal"
        status = res.termination_condition.name
        if ok:
            res.solution_loader.load_vars()
    else:
        res = _solver("glpk", False).solve(m)
        status = str(res.solver.termination_condition)
        ok = status == "optimal"
    if not ok:
        raise RuntimeError(f"The solver stopped without an optimal solution ({status}). "
                           "Check that the contracts can be met with the technologies allowed.")
    return {"solve_s": time.time() - t0, "status": status}


def solve_sizing(ts, p, solver="highs"):
    """Sizing on a reduced year with exact handling of the pipeline classes.

    1. solve without a pipeline; 2. if pipelines are allowed, solve the LP
    relaxation of the class choice, which bounds every pipeline option from
    below; 3. only if that bound beats the no-pipeline cost are the classes
    enumerated one by one. Usually 1-2 LPs.
    """
    def fixed(choice):
        mm = build(ts, p, relax_pipe=True)
        for k in mm.K:
            mm.y_pipe[k].fix(1.0 if k == choice else 0.0)
        return mm, solve(mm, solver)["solve_s"]

    best, tot = fixed(None)
    if not p["pipe_allowed"]:
        return best, {"solve_s": tot, "status": "optimal", "n_lp": 1}
    relax = build(ts, p, relax_pipe=True)
    tot += solve(relax, solver)["solve_s"]
    obj0, lb = pyo.value(best.obj), pyo.value(relax.obj)
    n = 2
    if lb < obj0 - 1e-6 * abs(obj0) - 1.0:
        for k in p["pipe_allowed"]:
            mm, t = fixed(k)
            tot += t; n += 1
            if pyo.value(mm.obj) < pyo.value(best.obj):
                best = mm
    return best, {"solve_s": tot, "status": "optimal", "n_lp": n}


def design_of(m) -> dict:
    d = {v: max(float(pyo.value(getattr(m, v))), 0.0) for v in CAP_VARS}
    d["pipe"] = {k: int(round(pyo.value(m.y_pipe[k]))) for k in m.K}
    return d


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

def _val(x):
    v = x.value
    return 0.0 if v is None else float(v)


def hourly(m) -> dict:
    """Hourly arrays (length = steps of the time structure, R=1)."""
    out = {n: np.array([_val(getattr(m, n)[0, h]) for h in m.H]) for n in FLOWS}
    ts = m._ts
    out["gen_wind"] = _val(m.C_wt) * ts.reps["wind_cf"][0]
    out["gen_pv"] = _val(m.C_pv) * ts.reps["pv_cf"][0]
    for name in ("tank_on", "tank_off", "bat_on", "bat_off"):
        start = _val(getattr(m, f"{name}_start")[0])
        dev = np.array([_val(getattr(m, f"{name}_dev")[0, b]) for b in range(ts.L + 1)])
        out[f"soc_{name}"] = start + dev[1:]
    if hasattr(m, "short_e"):
        out["short_e"] = np.array([_val(m.short_e[0, h]) for h in m.H])
        out["short_h"] = np.array([_val(m.short_h[0, h]) for h in m.H])
    if "price" in ts.reps:
        out["price"] = ts.reps["price"][0]
    return out


def summary(m) -> dict:
    v = pyo.value
    p = m._p
    hrs = m._hours
    d = design_of(m)
    out = {k: d[k] for k in CAP_VARS}
    out["pipe"] = next((k for k, x in d["pipe"].items() if x == 1), "none")
    out["cost_parts"] = {k: float(v(e)) for k, e in m.cost_parts.items()}
    out["cost_parts"]["TSO fee"] = float(v(m.tso))
    out["cost_parts"]["Variable O&M"] = float(v(m.ann_vom))
    out["capex_total"] = float(v(m.capex_total))
    out["total_cost"] = float(v(m.total_cost))
    out["rev_e"], out["rev_h"] = float(v(m.rev_e)), float(v(m.rev_h))
    out["penalty"] = float(v(m.penalty))
    out["net_cost"] = float(v(m.net_cost))
    tot = lambda name: float((hrs * np.array([[_val(getattr(m, name)[r, h]) for h in m.H] for r in m.R])).sum())
    out["grid_mwh"], out["h2_kg"] = tot("p_grid"), tot("h2_sell")
    out["curt_mwh"] = tot("p_curt_off")
    wt, pv = m._ts.reps["wind_cf"], m._ts.reps["pv_cf"]
    out["gen_wind_mwh"] = float((hrs * wt).sum() * out["C_wt"])
    out["gen_pv_mwh"] = float((hrs * pv).sum() * out["C_pv"])
    out["short_e_mwh"] = out["short_h_kg"] = 0.0
    if hasattr(m, "short_e"):
        out["short_e_mwh"] = tot("short_e") + _val(m.short_ey)
        out["short_h_kg"] = tot("short_h") + _val(m.short_hy)
    for k in ("p_we", "p_pe", "p_cab_f", "h2_pipe", "h2fc_off", "h2fc_on", "bat_on_dis", "bat_off_dis"):
        out[f"sum_{k}"] = tot(k)
    out["config"], out["link_mode"] = p["config"], p["link_mode"]
    out["grid_distance_km"], out["pipe_distance_km"] = p["grid_distance_km"], p["pipe_distance_km"]
    # unit costs (v9 definitions, net of the other product's revenue)
    out["lcoe_net"] = (out["total_cost"] - out["rev_h"]) / out["grid_mwh"] if out["grid_mwh"] > 1 else float("nan")
    out["lcoh_net"] = (out["total_cost"] - out["rev_e"]) / out["h2_kg"] if out["h2_kg"] > 1 else float("nan")
    return out
