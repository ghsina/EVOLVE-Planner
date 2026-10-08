"""All user-editable inputs of the planner, with defaults, units and help text.

One flat dictionary holds every input. ``SPEC`` describes each entry for the
interface and the Excel workbook; ``derive`` turns the flat inputs into the
quantities the optimisation model uses (configuration, export technology,
compression work, nested storage/pipeline tables, ...).

Default values are the v9 techno-economic set (Step 2 validation). Entries
marked ``step3=True`` are placeholders that Step 3 replaces with referenced
values; the interface flags them.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field


@dataclass
class P:
    key: str
    group: str
    label: str
    unit: str
    default: object
    kind: str = "float"            # float | int | bool | choice | text
    options: tuple = ()
    help: str = ""
    step3: bool = False
    advanced: bool = False
    min: float | None = None
    max: float | None = None


SPEC: list[P] = [
    # ------------------------------------------------------------------ use case
    P("use_case", "Use case", "What the island supplies", "-", "Hybrid", "choice",
      ("Power-led", "Hydrogen-led", "Hybrid"),
      "Power-led: electricity to the grid, hydrogen only as internal storage. Hydrogen-led: hydrogen to an "
      "offtaker, electricity optional. Hybrid: both contracts."),
    P("annual_demand_mwh", "Use case", "Electricity to deliver per year", "MWh/yr", 200_000.0, min=0.0,
      help="Contracted electricity at the grid point. Ignored in merchant and CfD modes, where volume is free."),
    P("annual_h2_demand_kg", "Use case", "Hydrogen to deliver per year", "kg/yr", 2.0e6, min=0.0),
    P("elec_delivery", "Use case", "Electricity delivery profile", "-", "annual", "choice",
      ("annual", "firm", "profile"),
      "annual: only the yearly volume counts. firm: the same power every hour. profile: follow the hourly "
      "profile uploaded with the time series (column elec_demand_mw)."),
    P("h2_delivery", "Use case", "Hydrogen delivery profile", "-", "annual", "choice", ("annual", "firm", "profile"),
      "As for electricity; profile uses column h2_demand_kgh."),
    P("elec_revenue", "Use case", "Electricity revenue", "-", "ppa", "choice", ("ppa", "merchant", "cfd"),
      "ppa: fixed volume at the PPA price. merchant: every MWh sold at the hourly day-ahead price. cfd: two-sided "
      "contract for difference, strike price paid in hours with non-negative price (French offshore scheme)."),
    P("ppa_price_eur_mwh", "Use case", "PPA price", "EUR/MWh", 100.0, min=0.0),
    P("cfd_strike_eur_mwh", "Use case", "CfD strike price", "EUR/MWh", 86.45, min=0.0,
      help="Bretagne Sud 1 (Pennavel) award, 15 May 2024: EUR 86.45/MWh."),
    P("h2_price_eur_kg", "Use case", "Hydrogen sales price", "EUR/kg", 6.0, min=0.0),
    P("sell_surplus", "Use case", "Sell the other carrier as a by-product", "-", False, "bool",
      help="Power-led: sell hydrogen made from surplus power at the hydrogen price. Hydrogen-led: sell "
           "surplus electricity (merchant or CfD). Off: only the main product earns revenue."),
    P("grid_injection_cap_mw", "Use case", "Maximum grid injection", "MW", 100.0, min=0.0,
      help="Firm capacity of the grid connection."),
    # ------------------------------------------------------------------ site
    P("site_name", "Site", "Site name", "-", "My floating island", "text"),
    P("site_lat", "Site", "Island latitude", "deg", 47.38, min=-90.0, max=90.0),
    P("site_lon", "Site", "Island longitude", "deg", -3.55, min=-180.0, max=180.0),
    P("grid_name", "Site", "Grid connection point", "-", "Grid substation", "text"),
    P("grid_lat", "Site", "Grid point latitude", "deg", 47.64, min=-90.0, max=90.0),
    P("grid_lon", "Site", "Grid point longitude", "deg", -3.16, min=-180.0, max=180.0),
    P("h2_name", "Site", "Hydrogen offtake point", "-", "Hydrogen offtaker", "text"),
    P("h2_lat", "Site", "Hydrogen offtake latitude", "deg", 47.27, min=-90.0, max=90.0),
    P("h2_lon", "Site", "Hydrogen offtake longitude", "deg", -2.20, min=-180.0, max=180.0),
    P("routing_factor", "Site", "Routing factor (route / straight line)", "-", 1.2, min=1.0, max=3.0,
      help="Cables and pipes rarely run straight; 1.1-1.3 is typical."),
    P("link_distance_override_km", "Site", "Export route length (0 = from the map)", "km", 0.0, min=0.0,
      help="Set a routed length if you know it; otherwise straight-line distance x routing factor."),
    P("avg_water_depth_m", "Site", "Water depth at the island", "m", 75.0, min=0.0,
      help="Up to the fixed/floating threshold the island is bottom-fixed; deeper it floats."),
    P("fixed_floating_depth_m", "Site", "Fixed/floating threshold depth", "m", 60.0, min=0.0, advanced=True),
    P("decentralized_h2", "Site", "Turbine-level electrolysis (no power cable)", "-", False, "bool",
      help="Floating, decentralised concept (Dolphyn type): hydrogen made in each turbine, pipeline export only."),
    P("existing_pipeline_available", "Site", "Existing gas pipeline on the route can be repurposed", "-", False, "bool"),
    P("sea_area_km2", "Site", "Usable sea area", "km2", 38.0, min=0.0,
      help="Polygon available for turbines and floating PV."),
    P("wind_density_mw_km2", "Site", "Wind power density", "MW/km2", 6.3, min=0.1,
      help="Bretagne Sud: 250 MW on 40 km2 and 500 MW on 75 km2 (State brochure, 2026)."),
    P("pv_density_mw_km2", "Site", "Floating PV density", "MW/km2", 60.0, min=0.1, step3=True),
    P("deck_area_max_m2", "Site", "Island deck area available", "m2", 200_000.0, min=0.0,
      help="Area for electrolysers, compressors, fuel cells, batteries and tanks on the island."),
    P("area_onshore_max_m2", "Site", "Onshore plot area", "m2", 1_000_000.0, min=0.0),
    # ------------------------------------------------------------------ technology switches
    P("enable_pv", "Technologies", "Floating PV", "-", True, "bool"),
    P("enable_ez_off", "Technologies", "Electrolyser on the island", "-", True, "bool"),
    P("enable_ez_on", "Technologies", "Electrolyser onshore", "-", True, "bool"),
    P("enable_fc_off", "Technologies", "Fuel cell on the island", "-", True, "bool"),
    P("enable_fc_on", "Technologies", "Fuel cell onshore", "-", True, "bool"),
    P("enable_batt_off", "Technologies", "Battery on the island", "-", True, "bool"),
    P("enable_batt_on", "Technologies", "Battery onshore", "-", True, "bool"),
    P("enable_tank_off", "Technologies", "Hydrogen tank on the island", "-", True, "bool"),
    P("enable_tank_on", "Technologies", "Hydrogen tank onshore", "-", True, "bool"),
    P("enable_cable", "Technologies", "Electricity export cable", "-", True, "bool"),
    P("enable_pipe", "Technologies", "Hydrogen export pipeline", "-", True, "bool"),
    # ------------------------------------------------------------------ finance
    P("discount_rate", "Finance", "Discount rate (real WACC)", "fraction", 0.07, min=0.0, max=0.3),
    P("offshore_premium", "Finance", "Offshore cost premium on island equipment", "x", 1.10, min=1.0, step3=True),
    # ------------------------------------------------------------------ wind
    P("wind_capex_eur_mw", "Offshore wind", "CAPEX, bottom-fixed", "EUR/MW", 2_540_000.0, min=0.0, step3=True),
    P("wind_capex_floating_eur_mw", "Offshore wind", "CAPEX, floating", "EUR/MW", 2_540_000.0, min=0.0, step3=True,
      help="Placeholder equal to bottom-fixed (v9). Step 3 sets the referenced floating value."),
    P("wind_life", "Offshore wind", "Lifetime", "yr", 25, "int", min=1),
    P("wind_fom", "Offshore wind", "Fixed O&M, bottom-fixed", "fraction/yr", 0.025, min=0.0),
    P("wind_fom_floating", "Offshore wind", "Fixed O&M, floating", "fraction/yr", 0.03, min=0.0),
    P("turbine_mw", "Offshore wind", "Turbine rating (for the drawing)", "MW", 15.0, min=1.0, advanced=True),
    # ------------------------------------------------------------------ PV
    P("pv_capex_eur_kw", "Floating PV", "CAPEX", "EUR/kW", 1500.0, min=0.0, step3=True),
    P("pv_life", "Floating PV", "Lifetime", "yr", 25, "int", min=1),
    P("pv_fom", "Floating PV", "Fixed O&M", "fraction/yr", 0.02, min=0.0),
    # ------------------------------------------------------------------ electrolysis
    P("elec_capex_eur_kw", "Electrolysis", "CAPEX (stack + balance of plant)", "EUR/kW", 2000.0, min=0.0, step3=True),
    P("electrolyzer_efficiency", "Electrolysis", "Efficiency (LHV)", "fraction", 0.75, min=0.3, max=1.0),
    P("elec_life", "Electrolysis", "Lifetime (stack replacement)", "yr", 15, "int", min=1),
    P("elec_fom", "Electrolysis", "Fixed O&M", "fraction/yr", 0.015, min=0.0),
    P("area_elec_m2_mw", "Electrolysis", "Deck area", "m2/MW", 200.0, min=0.0, advanced=True),
    P("wt_capex_eur_mw", "Electrolysis", "Water treatment CAPEX", "EUR/MW", 20_750.0, min=0.0, advanced=True),
    P("wt_life", "Electrolysis", "Water treatment lifetime", "yr", 20, "int", advanced=True),
    P("wt_fom", "Electrolysis", "Water treatment O&M", "fraction/yr", 0.10, advanced=True),
    # ------------------------------------------------------------------ compression
    P("comp_p_in_bar", "Compression", "Inlet pressure", "bar", 30.0, min=1.0),
    P("comp_p_out_bar", "Compression", "Outlet pressure", "bar", 70.0, min=1.0),
    P("comp_isentropic_eff", "Compression", "Isentropic efficiency", "fraction", 0.75, min=0.3, max=1.0),
    P("comp_stages", "Compression", "Stages", "-", 2, "int", min=1, advanced=True),
    P("comp_inlet_temp_k", "Compression", "Inlet temperature", "K", 313.0, advanced=True),
    P("comp_z", "Compression", "Compressibility factor", "-", 1.05, advanced=True),
    P("comp_capex_eur_mw", "Compression", "CAPEX", "EUR/MW", 2.0e6, min=0.0, step3=True),
    P("comp_life", "Compression", "Lifetime", "yr", 20, "int", min=1),
    P("comp_fom", "Compression", "Fixed O&M", "fraction/yr", 0.03, min=0.0),
    P("area_comp_m2_mw", "Compression", "Deck area", "m2/MW", 100.0, advanced=True),
    # ------------------------------------------------------------------ fuel cell
    P("fc_efficiency_lhv", "Fuel cell", "Efficiency (LHV)", "fraction", 0.50, min=0.1, max=1.0),
    P("fc_capex_eur_kw", "Fuel cell", "CAPEX", "EUR/kW", 1170.0, min=0.0),
    P("fc_life", "Fuel cell", "Lifetime", "yr", 15, "int", min=1),
    P("fc_fom", "Fuel cell", "Fixed O&M", "fraction/yr", 0.03, min=0.0),
    P("area_fc_m2_mw", "Fuel cell", "Deck area", "m2/MW", 120.0, advanced=True),
    # ------------------------------------------------------------------ batteries
    P("batt_capex_e_eur_mwh", "Battery", "Energy CAPEX", "EUR/MWh", 160_000.0, min=0.0),
    P("batt_capex_p_eur_mw", "Battery", "Power CAPEX", "EUR/MW", 5_343_913.0, min=0.0, step3=True),
    P("batt_eta", "Battery", "Charge and discharge efficiency (each way)", "fraction", 0.95, min=0.5, max=1.0),
    P("batt_life", "Battery", "Lifetime", "yr", 15, "int", min=1),
    P("batt_fom", "Battery", "Fixed O&M", "fraction/yr", 0.02, min=0.0),
    P("batt_vom", "Battery", "Variable O&M", "EUR/MWh", 1.19, min=0.0),
    P("area_batt_m2_mwh", "Battery", "Deck area", "m2/MWh", 25.0, advanced=True),
    # ------------------------------------------------------------------ tanks
    P("tank_capex_eur_kg", "Hydrogen tank", "CAPEX", "EUR/kg", 650.0, min=0.0),
    P("tank_life", "Hydrogen tank", "Lifetime", "yr", 20, "int", min=1),
    P("tank_fom", "Hydrogen tank", "Fixed O&M", "fraction/yr", 0.02, min=0.0),
    P("tank_vom", "Hydrogen tank", "Variable O&M", "EUR/kg", 0.01, min=0.0),
    P("area_tank_m2_kg", "Hydrogen tank", "Deck area", "m2/kg", 1.5, advanced=True),
    # ------------------------------------------------------------------ export cable
    P("hvac_hvdc_threshold_km", "Export cable", "HVAC up to (beyond: HVDC)", "km", 60.0, min=0.0),
    P("hvac_var_eur_mw_km", "Export cable", "HVAC cost per MW per km", "EUR/MW/km", 1360.0, step3=True),
    P("hvac_fix_eur_km", "Export cable", "HVAC fixed cost per km", "EUR/km", 206_130.0, step3=True),
    P("hvac_loss_per_km", "Export cable", "HVAC loss per km", "fraction/km", 6.7e-5),
    P("hvdc_converter_pair_eur_mw", "Export cable", "HVDC converter pair", "EUR/MW", 300_000.0, step3=True,
      help="ACER 2026 median is 0.21 M EUR/MW per station (0.42 per pair); Step 3 updates this."),
    P("hvdc_cable_eur_mw_km", "Export cable", "HVDC cable", "EUR/MW/km", 1000.0, step3=True),
    P("hvdc_converter_loss", "Export cable", "HVDC converter losses (pair)", "fraction", 0.02),
    P("hvdc_cable_loss_per_km", "Export cable", "HVDC cable loss per km", "fraction/km", 3.5e-5),
    P("tso_fee_eur_mw_yr", "Export cable", "TSO connection fee (HVAC hub)", "EUR/MW/yr", 42_000.0),
    P("cable_life", "Export cable", "Lifetime", "yr", 30, "int", min=1),
    # ------------------------------------------------------------------ pipeline
    P("pipe_small_capex_eur_km", "Hydrogen pipeline", "New 12-inch: cost", "EUR/km", 1.0e6, step3=True),
    P("pipe_small_cap_kgh", "Hydrogen pipeline", "New 12-inch: capacity", "kg/h", 33_264.0),
    P("pipe_medium_capex_eur_km", "Hydrogen pipeline", "New 36-inch: cost", "EUR/km", 3.7e6),
    P("pipe_medium_cap_kgh", "Hydrogen pipeline", "New 36-inch: capacity", "kg/h", 141_000.0),
    P("pipe_repurposed_capex_eur_km", "Hydrogen pipeline", "Repurposed 36-inch: cost", "EUR/km", 0.4e6),
    P("pipe_repurposed_cap_kgh", "Hydrogen pipeline", "Repurposed 36-inch: capacity", "kg/h", 108_000.0),
    P("pipeline_efficiency", "Hydrogen pipeline", "Delivery efficiency", "fraction", 0.99),
    P("pipeline_life", "Hydrogen pipeline", "Lifetime", "yr", 40, "int"),
    P("pipeline_fom", "Hydrogen pipeline", "Fixed O&M", "fraction/yr", 0.009),
    # ------------------------------------------------------------------ platform
    P("platform_cable_coef", "Island platform", "Platform cost per MW of export cable", "kEUR/MW", 84.651, step3=True),
    P("platform_elec_coef", "Island platform", "Platform cost per MW of island equipment", "kEUR/MW", 139.281, step3=True),
    P("platform_install_factor", "Island platform", "Installation factor", "x", 1.5),
    P("platform_life", "Island platform", "Lifetime", "yr", 25, "int"),
    P("platform_fom", "Island platform", "Fixed O&M", "fraction/yr", 0.02),
    # ------------------------------------------------------------------ penalties
    P("shortfall_penalty_eur_mwh", "Solver", "Penalty for undelivered electricity", "EUR/MWh", 3000.0, advanced=True),
    P("shortfall_penalty_eur_kg", "Solver", "Penalty for undelivered hydrogen", "EUR/kg", 100.0, advanced=True),
    P("lhv_h2_kwh_kg", "Solver", "Hydrogen LHV", "kWh/kg", 33.3, advanced=True),
    P("cap_ub_mw", "Solver", "Upper bound on any capacity", "MW", 5000.0, advanced=True),
]

BY_KEY = {s.key: s for s in SPEC}
GROUP_ORDER = []
for s in SPEC:
    if s.group not in GROUP_ORDER:
        GROUP_ORDER.append(s.group)


def defaults() -> dict:
    return {s.key: copy.deepcopy(s.default) for s in SPEC}


def crf(r: float, n: float) -> float:
    return r * (1 + r) ** n / ((1 + r) ** n - 1) if r > 0 else 1.0 / n


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def derive(user: dict) -> dict:
    """Flat user inputs -> everything the model needs."""
    p = defaults()
    p.update({k: v for k, v in user.items() if v is not None})
    d = dict(p)
    # use case
    if p["use_case"] == "Power-led":
        d["annual_h2_demand_kg"] = 0.0
        if not p.get("sell_surplus", False):
            d["h2_price_eur_kg"] = 0.0
        if p["h2_delivery"] == "profile":
            d["h2_delivery"] = "annual"
    elif p["use_case"] == "Hydrogen-led":
        d["annual_demand_mwh"] = 0.0
        if p["elec_revenue"] == "ppa" or not p.get("sell_surplus", False):
            d["elec_revenue"] = "none"
    # distances
    straight_grid = haversine_km(p["site_lat"], p["site_lon"], p["grid_lat"], p["grid_lon"])
    straight_h2 = haversine_km(p["site_lat"], p["site_lon"], p["h2_lat"], p["h2_lon"])
    d["grid_distance_km"] = p["link_distance_override_km"] or straight_grid * p["routing_factor"]
    d["h2_distance_km"] = straight_h2 * p["routing_factor"]
    d["link_distance_km"] = d["grid_distance_km"]
    # configuration (v9 rule)
    floating = p["avg_water_depth_m"] > p["fixed_floating_depth_m"]
    if not floating:
        d.update(config="A_fixed", platform_float_factor=1.0, hvdc_float_premium=1.0, elec_export_allowed=True)
    elif not p["decentralized_h2"]:
        d.update(config="B_floating_centralized", platform_float_factor=2.0, hvdc_float_premium=1.5,
                 elec_export_allowed=True)
    else:
        d.update(config="C_floating_decentralized", platform_float_factor=1.0, hvdc_float_premium=1.0,
                 elec_export_allowed=False)
    d["floating"] = floating
    if floating:
        d["wind_capex_eur_mw"] = p["wind_capex_floating_eur_mw"]
        d["wind_fom"] = p["wind_fom_floating"]
    if not p["enable_cable"]:
        d["elec_export_allowed"] = False
    # conversion constants
    d["h2_kg_per_mwh"] = 1000.0 * p["electrolyzer_efficiency"] / p["lhv_h2_kwh_kg"]
    d["fc_mwh_per_kg"] = p["fc_efficiency_lhv"] * p["lhv_h2_kwh_kg"] / 1000.0
    k, n = 1.41, int(p["comp_stages"])
    ratio = (p["comp_p_out_bar"] / p["comp_p_in_bar"]) ** ((k - 1.0) / (n * k))
    w = (p["comp_z"] * 8.314 * p["comp_inlet_temp_k"] / (p["comp_isentropic_eff"] * 2.016e-3)
         * n * (k / (k - 1.0)) * (ratio - 1.0))
    d["comp_mwh_per_kg"] = max(w, 0.0) / 3.6e6 / 1000.0
    # export link (v9 rule: technology from distance)
    L = d["link_distance_km"]
    if L <= p["hvac_hvdc_threshold_km"]:
        d["link_mode"] = "HVAC"
        d["cable_capex_eur_mw"] = (p["hvac_var_eur_mw_km"]
                                   + p["hvac_fix_eur_km"] / max(p["grid_injection_cap_mw"], 1.0)) * L
        d["cable_eff"] = 1.0 - p["hvac_loss_per_km"] * L
        d["cable_fom"] = 0.005
        d["tso_fee"] = p["tso_fee_eur_mw_yr"]
    else:
        d["link_mode"] = "HVDC"
        d["cable_capex_eur_mw"] = (p["hvdc_converter_pair_eur_mw"] * d["hvdc_float_premium"]
                                   + p["hvdc_cable_eur_mw_km"] * L)
        d["cable_eff"] = 1.0 - (p["hvdc_converter_loss"] + p["hvdc_cable_loss_per_km"] * L)
        d["cable_fom"] = 0.01
        d["tso_fee"] = 0.0
    if not d["elec_export_allowed"]:
        d["cable_capex_eur_mw"], d["tso_fee"] = 0.0, 0.0
    # nested tables used by the model
    op = p["offshore_premium"]
    big_e, big_p = 1.0e5, 2.0e4
    d["batt"] = {
        "on": {"capex_e": p["batt_capex_e_eur_mwh"], "capex_p": p["batt_capex_p_eur_mw"], "life": p["batt_life"],
               "max_e": big_e if p["enable_batt_on"] else 0.0, "max_p": big_p if p["enable_batt_on"] else 0.0,
               "eta_ch": p["batt_eta"], "eta_dis": p["batt_eta"], "lam": 0.0, "fom": p["batt_fom"],
               "vom": p["batt_vom"]},
        "off": {"capex_e": p["batt_capex_e_eur_mwh"] * op, "capex_p": p["batt_capex_p_eur_mw"] * op,
                "life": p["batt_life"], "max_e": big_e if p["enable_batt_off"] else 0.0,
                "max_p": big_p if p["enable_batt_off"] else 0.0, "eta_ch": p["batt_eta"],
                "eta_dis": p["batt_eta"], "lam": 0.0, "fom": p["batt_fom"] + 0.005, "vom": p["batt_vom"]},
    }
    d["tank"] = {
        "on": {"capex_kg": p["tank_capex_eur_kg"], "life": p["tank_life"], "fom": p["tank_fom"], "lam": 0.0,
               "max_kg": 5.0e6 if p["enable_tank_on"] else 0.0, "vom": p["tank_vom"]},
        "off": {"capex_kg": p["tank_capex_eur_kg"] * op, "life": p["tank_life"], "fom": p["tank_fom"] + 0.005,
                "lam": 0.0, "max_kg": 5.0e6 if p["enable_tank_off"] else 0.0, "vom": p["tank_vom"]},
    }
    classes = {
        "new_small_12in": {"capex_per_km": p["pipe_small_capex_eur_km"], "cap_kgh": p["pipe_small_cap_kgh"]},
        "new_medium_36in": {"capex_per_km": p["pipe_medium_capex_eur_km"], "cap_kgh": p["pipe_medium_cap_kgh"]},
        "repurposed_36in": {"capex_per_km": p["pipe_repurposed_capex_eur_km"],
                            "cap_kgh": p["pipe_repurposed_cap_kgh"], "repurposed": True},
    }
    d["pipe_classes"] = classes
    d["pipe_allowed"] = [] if not p["enable_pipe"] else [
        kk for kk, c in classes.items() if not c.get("repurposed") or p["existing_pipeline_available"]]
    d["pipe_distance_km"] = d["h2_distance_km"]
    d["cap_renewable_ub_mw"] = 10_000.0
    return d
