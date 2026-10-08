"""The planner workflow on one year of hourly data.

    1. REDUCE   the year with topology-preserving chronological aggregation (tda.tpca);
    2. SIZE     every asset on the reduced year (LP; pipeline classes handled exactly);
    3. VERIFY + REPAIR on the full hourly year: the design is operated over all
                8,760 hours and three group scale factors >= 1 (generation,
                conversion and export, storage) may enlarge it. Shortfalls are
                allowed only at a penalty and are reported.

Step 2 of the project validated this workflow against full-year optima:
cost within 0.3 %, contracts delivered, 5-10x faster.
"""
from __future__ import annotations

import time

import numpy as np
import pyomo.environ as pyo

from . import model as M
from . import params as P
from . import tda
from . import timestructure as tsm

GROUPS = {
    "generation": ["C_wt", "C_pv"],
    "conversion": ["C_ez_off", "C_ez_on", "C_cmp_off", "C_cmp_on", "C_fc_off", "C_fc_on", "C_cab"],
    "storage": ["E_bat_off", "P_bat_off", "E_bat_on", "P_bat_on", "E_tank_off", "E_tank_on"],
}
SERIES = ("wind_cf", "pv_cf", "price", "elec_demand", "h2_demand")


def check_series(series: dict, p: dict) -> list[str]:
    """Plain-language problems with the time series for these inputs (empty = fine)."""
    msgs = []
    for k in ("wind_cf", "pv_cf") if p.get("enable_pv", True) else ("wind_cf",):
        x = series.get(k)
        if x is None or len(x) != 8760:
            msgs.append(f"{k}: 8,760 hourly values are needed.")
        elif np.isnan(x).any() or x.min() < 0 or x.max() > 1:
            msgs.append(f"{k}: values must be capacity factors between 0 and 1, without gaps.")
    if p["elec_revenue"] in ("merchant", "cfd") and (series.get("price") is None or len(series["price"]) != 8760):
        msgs.append("Merchant and CfD revenue need an hourly price series (column price).")
    if p["elec_delivery"] == "profile" and p["annual_demand_mwh"] > 0 and series.get("elec_demand") is None:
        msgs.append("Electricity profile delivery needs column elec_demand_mw.")
    if p["h2_delivery"] == "profile" and p["annual_h2_demand_kg"] > 0 and series.get("h2_demand") is None:
        msgs.append("Hydrogen profile delivery needs column h2_demand_kgh.")
    return msgs


def _data(series: dict) -> dict:
    return {k: np.asarray(series[k], float).reshape(1, 8760) for k in SERIES if series.get(k) is not None}


def _cut_attrs(series: dict, p: dict) -> list[str]:
    attrs = ["wind_cf", "pv_cf"] if p.get("enable_pv", True) else ["wind_cf"]
    if p["elec_revenue"] in ("merchant", "cfd") and series.get("price") is not None:
        attrs.append("price")
    if p["elec_delivery"] == "profile" and series.get("elec_demand") is not None:
        attrs.append("elec_demand")
    if p["h2_delivery"] == "profile" and series.get("h2_demand") is not None:
        attrs.append("h2_demand")
    return attrs


def verify_and_repair(data: dict, p: dict, design: dict, solver: str = "highs", max_scale: float = 3.0):
    m = M.build(tsm.full(data), p, allow_shortfall=True, relax_pipe=True)
    for k in m.K:
        m.y_pipe[k].fix(design["pipe"].get(k, 0))
    m.lam = pyo.Var(list(GROUPS), bounds=(1.0, max_scale))
    m.lam_link = pyo.ConstraintList()
    for g, vs in GROUPS.items():
        for v in vs:
            m.lam_link.add(getattr(m, v) == m.lam[g] * design[v])
    info = M.solve(m, solver)
    return m, {**info, "scale": {g: (m.lam[g].value or 1.0) for g in GROUPS}}


def tda_diagnostics(data: dict, ts, attr: str = "wind_cf", max_points: int = 1500) -> dict:
    """What the TDA reduction preserved, for plotting."""
    x = data[attr][0]
    S = np.cumsum(x - x.mean())
    ends = np.cumsum(ts.sw).astype(int) - 1
    S_red = np.cumsum(ts.reps[attr][0] * ts.sw - x.mean() * ts.sw)
    S_interp = np.interp(np.arange(8760), np.r_[-1, ends], np.r_[0.0, S_red])
    lo = tda.persistence_pairs(S)[:-1]
    lo_r = tda.persistence_pairs(S_interp)[:-1]
    keep = lambda P_: P_[np.argsort(-(P_[:, 1] - P_[:, 0]))[:max_points]]
    return {"S": S, "S_reduced": S_interp, "block_ends": ends, "block_len": ts.sw,
            "dgm_full": keep(lo)[:, :2], "dgm_reduced": keep(lo_r)[:, :2]}


def plan(user: dict, series: dict, n_blocks: int = 1460, solver: str = "highs", progress=None) -> dict:
    """Run the full workflow. `progress(stage, text)` is called between stages."""
    say = progress or (lambda *a: None)
    p = P.derive(user)
    problems = check_series(series, p)
    if problems:
        raise ValueError(" ".join(problems))
    if not p.get("enable_pv", True) and series.get("pv_cf") is None:
        series = {**series, "pv_cf": np.zeros(8760)}
    data = _data(series)
    t0 = time.time()
    say("reduce", f"Reducing 8,760 hours to {n_blocks:,} blocks with TDA")
    ts = tda.tpca(data, n_blocks, _cut_attrs(series, p))
    t_reduce = time.time() - t0
    say("size", f"Sizing the system on {ts.L:,} blocks (shape error {100 * ts.meta['eps_achieved']:.2f} % "
                f"of the energy-balance range)")
    m, info = M.solve_sizing(ts, p, solver)
    reduced = M.summary(m)
    design = M.design_of(m)
    say("verify", "Verifying and repairing the design on the full hourly year")
    mf, rep = verify_and_repair(data, p, design, solver)
    final = M.summary(mf)
    say("done", "Done")
    return {
        "inputs": dict(user), "derived": {k: p[k] for k in (
            "config", "link_mode", "grid_distance_km", "pipe_distance_km", "floating", "cable_capex_eur_mw",
            "comp_mwh_per_kg", "h2_kg_per_mwh", "fc_mwh_per_kg", "pipe_allowed", "elec_revenue",
            "annual_demand_mwh", "annual_h2_demand_kg")},
        "tda": {"blocks": ts.L, "eps": ts.meta["eps_achieved"], "bottleneck": ts.meta["bottleneck_norm"],
                "n_fixed": ts.meta["n_fixed"], "attrs": _cut_attrs(series, p),
                "diag": tda_diagnostics(data, ts)},
        "reduced": reduced, "final": final, "scale": rep["scale"], "hourly": M.hourly(mf),
        "timing": {"reduce_s": t_reduce, "size_s": info["solve_s"], "verify_s": rep["solve_s"],
                   "total_s": time.time() - t0},
        "solver": solver,
    }
