"""EVOLVE Planner: lowest-cost design of a floating energy island and its onshore plant.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

from evolve_planner import __version__, params as P, report, weather, workbook, workflow
from evolve_planner.params import SPEC
from ui import charts, theme
from ui.schematic import DEMO, design_from_result, island_svg

ROOT = Path(__file__).parent
EX = ROOT / "examples" / "belle_ile"
BY = {s.key: s for s in SPEC}
STEPS = ["Site", "Use case", "Data", "Technologies", "Run", "Results"]
REPO_URL = "https://github.com/ghsina/evolve-planner"     # edit after you create the repository

NAMES = {
    ("use_case", "Power-led"): "Electricity", ("use_case", "Hydrogen-led"): "Hydrogen",
    ("use_case", "Hybrid"): "Electricity and hydrogen",
    ("elec_delivery", "annual"): "Annual volume, any hour", ("elec_delivery", "firm"): "Constant power every hour",
    ("elec_delivery", "profile"): "Follow my hourly profile",
    ("h2_delivery", "annual"): "Annual volume, any hour", ("h2_delivery", "firm"): "Constant flow every hour",
    ("h2_delivery", "profile"): "Follow my hourly profile",
    ("elec_revenue", "ppa"): "PPA: fixed price for the contracted volume",
    ("elec_revenue", "merchant"): "Merchant: sell at the day-ahead price",
    ("elec_revenue", "cfd"): "Contract for difference (strike price)",
}
ZONES = ["FR", "DE-LU", "NL", "BE", "DK1", "DK2", "NO2", "SE4", "PL", "AT", "CH", "CZ", "IT-North"]

st.set_page_config(page_title="EVOLVE Planner", page_icon=":material/waves:", layout="wide",
                   initial_sidebar_state="expanded")
theme.apply()
ss = st.session_state


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def init():
    ss.setdefault("user", P.defaults())
    ss.setdefault("series", {})
    ss.setdefault("series_src", {})
    ss.setdefault("notes", [])
    ss.setdefault("started", False)
    ss.setdefault("nav", STEPS[0])
    ss.setdefault("result", None)


init()
U = ss.user


def reset_widgets():
    for k in [k for k in ss.keys() if str(k).startswith(("w_", "ed_"))]:
        del ss[k]


def go(step):
    ss.nav = step
    ss.started = True


def load_preset(name: str):
    pre = json.loads((EX / "presets.json").read_text())[name]
    user = P.defaults()
    user.update({k: v for k, v in pre.items() if not k.startswith("_")})
    ss.user = user
    load_example_year(pre.get("_year", 2019))
    ss.result = None
    reset_widgets()
    go("Site")


def load_example_year(year: int):
    df = pd.read_csv(EX / f"timeseries_{year}.csv")
    ss.series = {"wind_cf": df.wind_cf.to_numpy(), "pv_cf": df.pv_cf.to_numpy(),
                 "price": df.price_eur_mwh.to_numpy()}
    src = f"Belle-Ile example, {year} (ERA5 + IEA 15 MW curve, pvlib, Energy-Charts FR prices)"
    ss.series_src = {"wind_cf": src, "pv_cf": src, "price": src}


def new_design():
    ss.user = P.defaults()
    ss.series, ss.series_src, ss.result = {}, {}, None
    reset_widgets()
    go("Site")


# ---------------------------------------------------------------------------
# input widgets bound to the user dict
# ---------------------------------------------------------------------------

def _fmt(v):
    a = abs(float(v))
    if a == 0 or a >= 1000:
        return "%.0f"
    if a >= 10:
        return "%.1f"
    if a >= 0.01:
        return "%.3f"
    return "%.6f"


def w(key, label=None, help=None, scale=1.0, unit=None, disabled=False, fmt=None):
    """Render the input for `key`; the value is kept in ss.user. `scale` shows e.g. MWh as GWh."""
    s = BY[key]
    wk = "w_" + key
    u = ss.user
    unit = unit if unit is not None else s.unit
    lab = (label or s.label) + (f" ({unit})" if unit not in ("-", "", None) else "")
    hp = help if help is not None else (s.help or None)
    if s.step3:
        hp = (hp + " " if hp else "") + "Placeholder value until Step 3 (referenced data)."
    if s.kind == "bool":
        ss.setdefault(wk, bool(u[key]))
        v = st.toggle(lab, key=wk, help=hp, disabled=disabled)
    elif s.kind == "choice":
        ss.setdefault(wk, u[key] if u[key] in s.options else s.options[0])
        v = st.selectbox(lab, s.options, key=wk, help=hp, disabled=disabled,
                         format_func=lambda o: NAMES.get((key, o), o))
    elif s.kind == "text":
        ss.setdefault(wk, str(u[key]))
        v = st.text_input(lab, key=wk, help=hp, disabled=disabled)
    elif s.kind == "int":
        ss.setdefault(wk, int(u[key]))
        v = st.number_input(lab, key=wk, step=1, min_value=0, help=hp, disabled=disabled)
    else:
        shown = float(u[key]) * scale
        ss.setdefault(wk, shown)
        v = st.number_input(lab, key=wk, format=fmt or _fmt(shown or s.default * scale), help=hp,
                            disabled=disabled,
                            min_value=None if s.min is None else s.min * scale,
                            max_value=None if s.max is None else s.max * scale)
        v = float(v) / scale
    u[key] = v
    return v


def svg_block(html):
    """The drawing in its own frame, sized to its content (CSS animations need a real document)."""
    if hasattr(st, "iframe"):
        st.iframe(html, height="content")
    else:                                            # Streamlit before st.iframe
        components.html(html, height=560)


def badge(text, kind="n"):
    return f'<span class="badge {kind}">{text}</span>'


def eur(x, unit=""):
    a = abs(x)
    if a >= 1e9:
        s = f"€{x / 1e9:,.2f} bn"
    elif a >= 1e6:
        s = f"€{x / 1e6:,.1f} M"
    elif a >= 1e3:
        s = f"€{x / 1e3:,.0f} k"
    else:
        s = f"€{x:,.0f}"
    return s + unit


def derived():
    try:
        return P.derive(ss.user)
    except Exception:          # noqa: BLE001  (half-typed inputs)
        return None


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

def sidebar():
    with st.sidebar:
        st.markdown("### EVOLVE Planner")
        st.caption(f"Floating energy islands, sized on one year of hours. Version {__version__}.")
        if ss.started:
            d = derived()
            uc = NAMES[("use_case", U["use_case"])]
            st.markdown(f"**{U['site_name']}**  \n{uc}")
            lines = []
            if d:
                lines.append(f"{'Floating' if d['floating'] else 'Bottom-fixed'}, {U['avg_water_depth_m']:.0f} m deep")
                lines.append(f"{d['link_mode']} export, {d['grid_distance_km']:.0f} km")
            have = [k for k in ("wind_cf", "pv_cf", "price", "elec_demand", "h2_demand") if ss.series.get(k) is not None]
            lines.append(f"Hourly data: {', '.join(have) if have else 'not loaded yet'}")
            if ss.result:
                f = ss.result["final"]
                lines.append(f"Last result: {'surplus' if f['net_cost'] < 0 else 'net cost'} "
                             f"{eur(abs(f['net_cost']), '/yr')}")
            st.markdown("  \n".join(lines))
            st.divider()
        st.markdown("**Inputs workbook**")
        st.download_button("Save all inputs (Excel)", workbook.to_bytes(U, ss.series, ss.notes),
                           file_name=f"EVOLVE_inputs_{U['site_name'][:30].replace(' ', '_')}.xlsx",
                           width="stretch")
        up = st.file_uploader("Open an inputs workbook", type=["xlsx"], key="wb_upload",
                              help="A workbook saved from this app or filled from the template. "
                                   "Restores every input and the hourly series.")
        if up is not None and ss.get("wb_id") != up.file_id:
            ss.wb_id = up.file_id
            try:
                user, series, notes = workbook.from_file(up)
                ss.user, ss.notes, ss.result = user, notes, None
                if series:
                    ss.series = series
                    ss.series_src = {k: f"workbook {up.name}" for k in series}
                reset_widgets()
                go("Site")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"The workbook could not be read: {e}")
        st.divider()
        if st.button("Open the Belle-Île example", width="stretch"):
            load_preset("hybrid_ppa"); st.rerun()
        if st.button("Start a new design", width="stretch"):
            new_design(); st.rerun()
        st.caption(f"[Method and source code]({REPO_URL})")


# ---------------------------------------------------------------------------
# landing
# ---------------------------------------------------------------------------

def landing():
    st.markdown("# Plan a floating energy island, hour by hour")
    st.markdown(
        '<p class="lede">Find the lowest-cost mix of offshore wind, floating PV, electrolysers, batteries, '
        'hydrogen storage, export cable and pipeline, on the island and onshore, for electricity, hydrogen '
        'or both. One year of hourly data is reduced with topological data analysis, so the optimiser keeps '
        'every surplus and deficit that matters, and the design is then checked against all 8,760 hours.</p>',
        unsafe_allow_html=True)
    c1, c2, _ = st.columns([1.3, 1, 3])
    c1.button("Open the Belle-Île example", type="primary", on_click=load_preset, args=("hybrid_ppa",),
              width="stretch")
    c2.button("Start a new design", on_click=new_design, width="stretch")
    svg_block(island_svg(DEMO, animate=True))
    st.caption("Illustration of the kind of system the planner sizes. Every run draws its own design.")
    a, b, c = st.columns(3)
    a.markdown("**1. Describe the project**  \nSite coordinates, water depth, sea area, grid and hydrogen "
               "offtake points, and what you deliver: electricity, hydrogen or both.")
    b.markdown("**2. Add one year of hours**  \nUpload wind and solar capacity factors and prices, download "
               "them from ERA5 by coordinates, or start from the Belle-Île data.")
    c.markdown("**3. Get the design**  \nCapacities, costs, revenues, hourly operation and a drawing of the "
               "island and the onshore plant, checked on the full year.")


# ---------------------------------------------------------------------------
# step 1: site
# ---------------------------------------------------------------------------

def site_map(d, height=430):
    pts = [dict(name=U["site_name"], lat=U["site_lat"], lon=U["site_lon"], col=[14, 42, 59], r=9),
           dict(name=U["grid_name"], lat=U["grid_lat"], lon=U["grid_lon"], col=[227, 167, 47], r=7)]
    arcs = [dict(a=[U["site_lon"], U["site_lat"]], b=[U["grid_lon"], U["grid_lat"]], col=[227, 167, 47])]
    if U["use_case"] != "Power-led" or U["enable_pipe"]:
        pts.append(dict(name=U["h2_name"], lat=U["h2_lat"], lon=U["h2_lon"], col=[63, 193, 201], r=7))
        arcs.append(dict(a=[U["site_lon"], U["site_lat"]], b=[U["h2_lon"], U["h2_lat"]], col=[63, 193, 201]))
    lats, lons = [p["lat"] for p in pts], [p["lon"] for p in pts]
    span = max(max(lats) - min(lats), (max(lons) - min(lons)) * 0.7, 0.05)
    zoom = float(np.clip(np.log2(360 / span) - 1.6, 3, 12))
    radius_m = float(np.sqrt(max(U["sea_area_km2"], 0.01) / np.pi) * 1000)
    layers = [
        pdk.Layer("ScatterplotLayer", data=[dict(lat=U["site_lat"], lon=U["site_lon"])],
                  get_position="[lon, lat]", get_radius=radius_m, get_fill_color=[31, 111, 139, 40],
                  get_line_color=[31, 111, 139, 160], stroked=True, line_width_min_pixels=1),
        pdk.Layer("LineLayer", data=arcs, get_source_position="a", get_target_position="b",
                  get_color="col", get_width=3),
        pdk.Layer("ScatterplotLayer", data=pts, get_position="[lon, lat]", get_fill_color="col",
                  get_radius="r", radius_units="'pixels'", pickable=True, stroked=True,
                  get_line_color=[255, 255, 255], line_width_min_pixels=2),
        pdk.Layer("TextLayer", data=pts, get_position="[lon, lat]", get_text="name", get_size=13,
                  get_color=[19, 35, 46], get_pixel_offset=[0, -18], font_family="IBM Plex Sans, Helvetica, Arial, sans-serif"),
    ]
    view = pdk.ViewState(latitude=float(np.mean(lats)), longitude=float(np.mean(lons)), zoom=zoom)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style="light",
                             tooltip={"text": "{name}"}), height=height)


def step_site():
    st.markdown("## Where is the island?")
    left, right = st.columns([5, 7], gap="large")
    with left:
        w("site_name")
        a, b = st.columns(2)
        with a: w("site_lat", fmt="%.4f", label="Island latitude", unit="°")
        with b: w("site_lon", fmt="%.4f", label="Island longitude", unit="°")
        w("grid_name")
        a, b = st.columns(2)
        with a: w("grid_lat", fmt="%.4f", label="Grid point latitude", unit="°")
        with b: w("grid_lon", fmt="%.4f", label="Grid point longitude", unit="°")
        w("h2_name")
        a, b = st.columns(2)
        with a: w("h2_lat", fmt="%.4f", label="Offtake latitude", unit="°")
        with b: w("h2_lon", fmt="%.4f", label="Offtake longitude", unit="°")
        a, b = st.columns(2)
        with a: w("avg_water_depth_m")
        with b: w("sea_area_km2")
        a, b = st.columns(2)
        with a: w("deck_area_max_m2", "Island deck area")
        with b: w("area_onshore_max_m2", "Onshore plot area")
        with st.expander("Routes, densities and foundations"):
            w("link_distance_override_km")
            w("routing_factor")
            w("wind_density_mw_km2")
            w("pv_density_mw_km2")
            w("fixed_floating_depth_m")
            w("decentralized_h2")
            w("existing_pipeline_available")
    with right:
        d = derived()
        site_map(d)
        if d:
            fnd = (f"Floating foundations ({U['avg_water_depth_m']:.0f} m is deeper than "
                   f"{U['fixed_floating_depth_m']:.0f} m)" if d["floating"]
                   else f"Bottom-fixed foundations ({U['avg_water_depth_m']:.0f} m)")
            src = "entered" if U["link_distance_override_km"] else "from the map × routing factor"
            html = (badge(fnd) + badge(f"{d['link_mode']} export cable, {d['grid_distance_km']:.0f} km ({src})", "p")
                    + badge(f"Pipeline route {d['pipe_distance_km']:.0f} km", "h")
                    + badge(f"Wind up to {U['sea_area_km2'] * U['wind_density_mw_km2']:,.0f} MW in the sea area"))
            st.markdown(html, unsafe_allow_html=True)
            if d["config"].startswith("C"):
                st.caption("Turbine-level electrolysis: no power cable is built; energy leaves as hydrogen.")
            st.caption("The cable technology follows the route length: HVAC up to "
                       f"{U['hvac_hvdc_threshold_km']:.0f} km, HVDC beyond (change it under Technologies).")
    nav_buttons("Site")


# ---------------------------------------------------------------------------
# step 2: use case
# ---------------------------------------------------------------------------

def step_use():
    st.markdown("## What should the island deliver?")
    s = BY["use_case"]
    ss.setdefault("w_use_case", U["use_case"])
    uc = st.radio("Main product", s.options, key="w_use_case", horizontal=True,
                  format_func=lambda o: NAMES[("use_case", o)],
                  captions=["Power to the grid; hydrogen only as a buffer or by-product",
                            "Hydrogen to an offtaker; the cable only if it pays",
                            "A set amount of each"])
    U["use_case"] = uc
    e_col, h_col = st.columns(2, gap="large")
    if uc != "Hydrogen-led":
        with e_col:
            st.markdown("#### Electricity")
            rev = w("elec_revenue")
            if rev == "ppa":
                w("annual_demand_mwh", "Electricity to deliver per year", scale=1e-3, unit="GWh/yr")
                w("elec_delivery")
                w("ppa_price_eur_mwh")
            elif rev == "cfd":
                w("cfd_strike_eur_mwh")
                st.caption("The strike price is paid in hours with a non-negative day-ahead price, the market price "
                           "otherwise. The optimiser chooses how much to sell.")
            else:
                st.caption("Every MWh earns the hourly day-ahead price. The optimiser chooses how much to sell.")
            w("grid_injection_cap_mw")
    if uc != "Power-led":
        with h_col if uc == "Hybrid" else e_col:
            st.markdown("#### Hydrogen")
            w("annual_h2_demand_kg", "Hydrogen to deliver per year", scale=1e-3, unit="t/yr")
            w("h2_delivery")
            w("h2_price_eur_kg")
    with h_col if uc != "Hybrid" else st.container():
        if uc == "Power-led":
            st.markdown("#### Hydrogen as a by-product")
            w("sell_surplus", "Sell hydrogen made from surplus power")
            if U["sell_surplus"]:
                w("h2_price_eur_kg")
        elif uc == "Hydrogen-led":
            st.markdown("#### Electricity as a by-product")
            w("sell_surplus", "Sell surplus electricity")
            if U["sell_surplus"]:
                w("elec_revenue", "How surplus electricity is sold")
                if U["elec_revenue"] == "cfd":
                    w("cfd_strike_eur_mwh")
                w("grid_injection_cap_mw")
                if U["elec_revenue"] == "ppa":
                    st.caption("A PPA needs a contracted volume; choose merchant or CfD for surplus sales.")
    if uc == "Hybrid":
        e_gwh = U["annual_demand_mwh"] / 1e3 if U["elec_revenue"] == "ppa" else 0.0
        h_gwh = U["annual_h2_demand_kg"] * U["lhv_h2_kwh_kg"] / U["electrolyzer_efficiency"] / 1e6
        tot = e_gwh + h_gwh
        if tot > 0:
            pe = 100 * e_gwh / tot
            st.markdown(
                f'<div style="margin-top:.6rem"><div class="note">Split of the contracted energy (before '
                f'losses): {e_gwh:,.0f} GWh to the grid and {h_gwh:,.0f} GWh of electricity for hydrogen</div>'
                f'<div style="display:flex;height:14px;border-radius:3px;overflow:hidden;margin-top:.3rem">'
                f'<div style="width:{pe:.1f}%;background:{theme.PALETTE["power"]}"></div>'
                f'<div style="width:{100 - pe:.1f}%;background:{theme.PALETTE["h2"]}"></div></div></div>',
                unsafe_allow_html=True)
    nav_buttons("Use case")


# ---------------------------------------------------------------------------
# step 3: data
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=20, ttl=24 * 3600)
def _era5(lat, lon, year):
    return weather.fetch_era5(lat, lon, year)


@st.cache_data(show_spinner=False, max_entries=20, ttl=24 * 3600)
def _prices(zone, year):
    return weather.fetch_prices(zone, year)


def step_data():
    st.markdown("## One year of hourly data")
    st.markdown('<p class="lede">The planner needs 8,760 hourly values of one year: wind and solar capacity '
                'factors (0 to 1), and day-ahead prices for merchant or CfD revenue. Demand profiles are needed '
                'only for "follow my hourly profile" delivery.</p>', unsafe_allow_html=True)
    t_up, t_api, t_ex = st.tabs(["Upload a file", "Download by coordinates", "Belle-Île example"])
    with t_up:
        a, b = st.columns([3, 2])
        with a:
            f = st.file_uploader("CSV or Excel file with one row per hour", type=["csv", "xlsx"], key="ts_upload",
                                 help="Recognised columns: wind_cf, pv_cf, price_eur_mwh, elec_demand_mw, "
                                      "h2_demand_kgh. A leap year (8,784 rows) is accepted; 29 February is removed.")
            if f is not None and ss.get("ts_id") != f.file_id:
                ss.ts_id = f.file_id
                try:
                    new, notes = weather.series_from_table(weather.read_table(f))
                    if not new:
                        st.error("No recognised column was found. Use the column names of the template.")
                    else:
                        ss.series.update(new)
                        ss.series_src.update({k: f"upload {f.name}" for k in new})
                        ss.notes = notes
                        ss.result = None
                except Exception as e:  # noqa: BLE001
                    st.error(f"The file could not be read: {e}")
            for n in ss.notes:
                st.caption(n)
        with b:
            st.markdown("**Templates**")
            st.download_button("Hourly template (CSV)", weather.template_csv(), "EVOLVE_timeseries_template.csv",
                               width="stretch")
            st.download_button("Full inputs workbook (Excel)", workbook.to_bytes(U, ss.series, ss.notes),
                               "EVOLVE_inputs.xlsx", width="stretch")
    with t_api:
        st.caption(f"Island at {U['site_lat']:.3f}°, {U['site_lon']:.3f}°. Wind: ERA5 100 m wind → 150 m hub → "
                   "IEA 15 MW reference curve, farm-smoothed, 12.5 % losses. Solar: ERA5 irradiance → pvlib, 10° "
                   "tilt, water-cooled modules, 14 % losses.")
        a, b, c = st.columns([1, 1, 2])
        year = a.selectbox("Weather year", list(range(2024, 1999, -1)), key="api_year")
        zone = b.selectbox("Price zone", ZONES, key="api_zone")
        with c:
            st.write("")
            st.write("")
            col1, col2 = st.columns(2)
            get_w = col1.button("Get wind and solar", width="stretch")
            get_p = col2.button("Get prices", width="stretch")
        if get_w:
            with st.spinner("Downloading ERA5 from the Open-Meteo archive"):
                try:
                    s, meta = _era5(round(U["site_lat"], 3), round(U["site_lon"], 3), int(year))
                    ss.series.update(s)
                    src = f"ERA5 {year} at {meta['lat']:.2f}°, {meta['lon']:.2f}° (Open-Meteo)"
                    ss.series_src.update({"wind_cf": src, "pv_cf": src})
                    ss.result = None
                    st.success(f"Wind and solar loaded. Mean wind speed at 100 m: {meta['mean_ws100']:.1f} m/s.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"The weather service did not answer ({type(e).__name__}). Try again, or upload "
                             "wind_cf and pv_cf in a file.")
        if get_p:
            with st.spinner("Downloading day-ahead prices from Energy-Charts"):
                try:
                    pr, meta = _prices(zone, int(year))
                    ss.series["price"] = pr
                    ss.series_src["price"] = f"Day-ahead {zone} {year} (Energy-Charts, Fraunhofer ISE)"
                    ss.result = None
                    st.success(f"Prices loaded. Mean {meta['mean']:.1f} EUR/MWh.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"The price service did not answer ({e}). Try again, or upload a price_eur_mwh column.")
        st.caption("Wind and solar series derived here are first estimates. For a project, upload your own "
                   "measured or modelled capacity factors.")
    with t_ex:
        st.markdown("Bretagne Sud floating wind zone, south of Belle-Île (47.38° N, 3.55° W), 75 m deep. "
                    "Wind 42 % and solar 14.6 % capacity factor in 2019; French day-ahead prices.")
        a, b, _ = st.columns([1, 1, 2])
        yr = a.selectbox("Year", [2019, 2024], key="ex_year")
        if b.button("Use this year's data", width="stretch"):
            load_example_year(int(yr))
            ss.result = None
            st.success(f"Belle-Île {yr} loaded.")
        presets = json.loads((EX / "presets.json").read_text())
        a, b, _ = st.columns([2, 1, 1])
        pick = a.selectbox("Or load a complete Belle-Île scenario (replaces every input)", list(presets),
                           format_func=lambda k: presets[k]["_title"], key="ex_preset")
        with b:
            st.write("")
            st.write("")
            st.button("Load scenario", on_click=load_preset, args=(pick,), width="stretch")
    # ---- what is loaded --------------------------------------------------------------------
    st.markdown("#### Loaded series")
    rows = []
    labels = {"wind_cf": ("Wind capacity factor", "%", 100), "pv_cf": ("Solar capacity factor", "%", 100),
              "price": ("Day-ahead price", "EUR/MWh", 1), "elec_demand": ("Electricity demand", "MW", 1),
              "h2_demand": ("Hydrogen demand", "kg/h", 1)}
    for k, (lab, unit, sc) in labels.items():
        x = ss.series.get(k)
        rows.append({"series": lab, "status": "loaded" if x is not None else "missing",
                     "mean": f"{np.mean(x) * sc:,.1f} {unit}" if x is not None else "",
                     "source": ss.series_src.get(k, "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    d = derived()
    if d:
        probs = workflow.check_series(ss.series, d)
        if probs:
            for m in probs:
                st.markdown(f'<span class="check-bad">To fix before running: {m}</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="check-ok">The series match the use case. Ready to run.</span>',
                        unsafe_allow_html=True)
        if ss.series.get("wind_cf") is not None:
            a, b = st.columns(2)
            a.plotly_chart(charts.monthly_cf(ss.series), width="stretch")
            b.plotly_chart(charts.duration(ss.series), width="stretch")
        if ss.series.get("price") is not None:
            st.plotly_chart(charts.price_profile(ss.series["price"]), width="stretch")
    nav_buttons("Data")


# ---------------------------------------------------------------------------
# step 4: technologies
# ---------------------------------------------------------------------------

EDIT_GROUPS = ["Finance", "Offshore wind", "Floating PV", "Electrolysis", "Compression", "Fuel cell", "Battery",
               "Hydrogen tank", "Export cable", "Hydrogen pipeline", "Island platform", "Solver"]


def preview_design():
    on = lambda k: U[k]
    d = dict(DEMO)
    d.update(C_pv=DEMO["C_pv"] if on("enable_pv") else 0, C_ez_off=20 if on("enable_ez_off") else 0,
             C_cmp_off=0.5 if (on("enable_ez_off") and on("enable_pipe")) else 0,
             C_ez_on=15 if on("enable_ez_on") else 0, C_cmp_on=0.2 if on("enable_ez_on") else 0,
             C_fc_off=5 if on("enable_fc_off") else 0, C_fc_on=10 if on("enable_fc_on") else 0,
             E_bat_off=20 if on("enable_batt_off") else 0, P_bat_off=5 if on("enable_batt_off") else 0,
             E_bat_on=40 if on("enable_batt_on") else 0, P_bat_on=10 if on("enable_batt_on") else 0,
             E_tank_off=30000 if on("enable_tank_off") else 0, E_tank_on=150000 if on("enable_tank_on") else 0,
             C_cab=60 if on("enable_cable") else 0, pipe="new_small_12in" if on("enable_pipe") else "none")
    dd = derived()
    if dd:
        d.update(floating=dd["floating"], link_mode=dd["link_mode"], grid_km=dd["grid_distance_km"],
                 pipe_km=dd["pipe_distance_km"], depth_m=U["avg_water_depth_m"], site_name=U["site_name"],
                 grid_name=U["grid_name"], h2_name=U["h2_name"], grid_gwh=None, h2_t=None)
    return d


def step_tech():
    st.markdown("## Which technologies may the optimiser use?")
    st.markdown('<p class="lede">Offshore wind is always available. Switch off anything that is not an option '
                'for your project; the optimiser sizes the rest, and may size an allowed technology at zero.</p>',
                unsafe_allow_html=True)
    a, b, c = st.columns(3, gap="large")
    with a:
        st.markdown("#### On the island")
        for k in ("enable_pv", "enable_ez_off", "enable_fc_off", "enable_batt_off", "enable_tank_off"):
            w(k, BY[k].label.replace(" on the island", ""))
    with b:
        st.markdown("#### Onshore")
        for k in ("enable_ez_on", "enable_fc_on", "enable_batt_on", "enable_tank_on"):
            w(k, BY[k].label.replace(" onshore", ""))
    with c:
        st.markdown("#### Links to shore")
        w("enable_cable")
        w("enable_pipe")
        if U["enable_pipe"] and not U["existing_pipeline_available"]:
            st.caption("Only new pipelines are considered. Tick 'existing gas pipeline' on the Site step to allow "
                       "a repurposed one.")
    svg_block(island_svg(preview_design(), animate=False))
    st.caption("Dashed outlines are technologies you switched off. Sizes in this preview are illustrative.")
    st.markdown("#### Costs and performance")
    adv = st.toggle("Show advanced parameters", key="show_adv")
    st.caption("Values marked as placeholders will be replaced by referenced values in Step 3. Edit any value "
               "in the value column.")
    tabs = st.tabs(EDIT_GROUPS)
    for g, tab in zip(EDIT_GROUPS, tabs):
        with tab:
            specs = [s for s in SPEC if s.group == g and s.kind in ("float", "int") and (adv or not s.advanced)]
            if not specs:
                st.caption("No parameters in this group.")
                continue
            df = pd.DataFrame({"parameter": [s.label for s in specs],
                               "value": [float(U[s.key]) for s in specs],
                               "unit": [s.unit for s in specs],
                               "status": ["placeholder" if s.step3 else "" for s in specs],
                               "default": [float(s.default) for s in specs]})
            ed = st.data_editor(df, key=f"ed_{g}_{int(adv)}", hide_index=True, width="stretch",
                                disabled=["parameter", "unit", "status", "default"],
                                column_config={"value": st.column_config.NumberColumn("value", format="%g"),
                                               "default": st.column_config.NumberColumn("default", format="%g")})
            for s, v in zip(specs, ed["value"].tolist()):
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    continue
                U[s.key] = int(v) if s.kind == "int" else float(v)
                ss.pop("w_" + s.key, None)
    nav_buttons("Technologies")


# ---------------------------------------------------------------------------
# step 5: run
# ---------------------------------------------------------------------------

@st.cache_resource
def _run_lock():
    return threading.Lock()


def step_run():
    st.markdown("## Find the lowest-cost design")
    d = derived()
    if d is None:
        st.error("Some inputs are not valid numbers. Check the previous steps.")
        return
    probs = workflow.check_series(ss.series, d)
    uc = NAMES[("use_case", U["use_case"])]
    want = []
    if d["annual_demand_mwh"] > 0 and d["elec_revenue"] == "ppa":
        want.append(f"{d['annual_demand_mwh'] / 1e3:,.0f} GWh of electricity a year")
    if d["annual_h2_demand_kg"] > 0:
        want.append(f"{d['annual_h2_demand_kg'] / 1e3:,.0f} t of hydrogen a year")
    st.markdown(
        f"**{U['site_name']}**: {uc.lower()}"
        + (f", {' and '.join(want)}" if want else ", volume chosen by the optimiser")
        + f". {'Floating' if d['floating'] else 'Bottom-fixed'} wind at {U['avg_water_depth_m']:.0f} m, "
          f"{d['link_mode']} export over {d['grid_distance_km']:.0f} km.")
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("The run has three stages:")
        st.markdown(
            "1. **Reduce.** The cumulative surplus-and-deficit curves of "
            + " and ".join({"wind_cf": "wind", "pv_cf": "solar", "price": "price", "elec_demand": "electricity demand",
                            "h2_demand": "hydrogen demand"}[k] for k in workflow._cut_attrs(ss.series, d))
            + " are analysed with persistent homology. Every long surplus or deficit episode becomes a fixed cut, "
              "and neighbouring hours are merged only where the curve stays within a small error.\n"
            "2. **Size.** The capacity-expansion model is solved on the reduced year, with storage carried "
            "across the whole year.\n"
            "3. **Check.** The design is operated on all 8,760 hours. If any hour falls short, capacities are "
            "scaled up by the smallest factor that delivers every contract, and the year is re-optimised.")
    with right:
        n = st.select_slider("Detail of the reduced year", options=[730, 1460, 2190], value=1460, key="n_blocks",
                             format_func=lambda v: {730: "Quick (730 blocks)", 1460: "Standard (1,460 blocks)",
                                                    2190: "Fine (2,190 blocks)"}[v])
        solvers = ["highs"] + (["glpk"] if shutil.which("glpsol") else [])
        solver = st.radio("Solver", solvers, horizontal=True, key="solver",
                          format_func=lambda s: {"highs": "HiGHS", "glpk": "GLPK (slower)"}[s])
        st.caption("Standard detail kept the cost within 0.3 % of the full-year optimum in the Step 2 tests. "
                   "A run takes about one to three minutes.")
    if probs:
        for m in probs:
            st.markdown(f'<span class="check-bad">{m}</span>', unsafe_allow_html=True)
        st.button("Go to the data step", on_click=go, args=("Data",))
        return
    if st.button("Find the lowest-cost design", type="primary"):
        lock = _run_lock()
        with st.status("Solving", expanded=True) as status:
            if not lock.acquire(blocking=False):
                status.write("Another design is being solved on this server. Yours starts as soon as it finishes.")
                lock.acquire()
            t0 = time.time()
            try:
                res = workflow.plan(dict(U), dict(ss.series), n_blocks=int(n), solver=solver,
                                    progress=lambda stage, text: status.write(f"{text} ({time.time() - t0:.0f} s)"))
                ss.result = res
                status.update(label=f"Design found in {res['timing']['total_s']:.0f} s", state="complete")
            except Exception as e:  # noqa: BLE001
                status.update(label="The run stopped", state="error")
                st.error(f"{e}")
                return
            finally:
                lock.release()
        ss._goto = "Results"          # the step selector is already drawn in this run
        st.rerun()


# ---------------------------------------------------------------------------
# step 6: results
# ---------------------------------------------------------------------------

CAP_ISLAND = [("C_wt", "Offshore wind", "MW"), ("C_pv", "Floating PV", "MW"), ("C_ez_off", "Electrolyser", "MW"),
              ("C_cmp_off", "Compressor", "MW"), ("C_fc_off", "Fuel cell", "MW"), ("P_bat_off", "Battery power", "MW"),
              ("E_bat_off", "Battery energy", "MWh"), ("E_tank_off", "Hydrogen tank", "t")]
CAP_SHORE = [("C_cab", "Export cable", "MW"), ("C_ez_on", "Electrolyser", "MW"), ("C_cmp_on", "Compressor", "MW"),
             ("C_fc_on", "Fuel cell", "MW"), ("P_bat_on", "Battery power", "MW"), ("E_bat_on", "Battery energy", "MWh"),
             ("E_tank_on", "Hydrogen tank", "t")]


def cap_table(f, rows):
    out = []
    for k, lab, unit in rows:
        v = f[k] / 1000 if unit == "t" else f[k]
        if v > 1e-3:
            out.append({"component": lab, "size": f"{v:,.1f} {unit}"})
    return pd.DataFrame(out) if out else pd.DataFrame({"component": ["Nothing built"], "size": [""]})


def step_results():
    res = ss.result
    if not res:
        st.markdown("## Results")
        st.info("No design yet. Set up the project and run it on the Run step.")
        st.button("Go to the run step", on_click=go, args=("Run",))
        return
    f, r, d = res["final"], res["reduced"], res["derived"]
    inp = res["inputs"]
    st.markdown(f"## {inp['site_name']}: lowest-cost design")
    st.caption(f"{NAMES[('use_case', inp['use_case'])]}. Sized on {res['tda']['blocks']:,} TDA blocks, checked on "
               f"8,760 hours, {res['timing']['total_s']:.0f} s with "
               f"{'HiGHS' if res['solver'] == 'highs' else 'GLPK'}.")
    built_any = f["C_wt"] + f["C_pv"] > 1e-3
    if not built_any:
        st.warning("Nothing is built: with these costs and revenues every MWh would cost more than it earns, and no "
                   "volume is contracted. Lower the costs, raise the price, or contract a volume under a PPA.")
    gen = f["gen_wind_mwh"] + f["gen_pv_mwh"]
    u = lambda s: f'<span class="u">{s}</span>'
    net = f["net_cost"]
    items = [("Net annual surplus (revenue − cost)" if net < 0 else "Net annual cost (cost − revenue)",
              eur(abs(net)) + u("/yr"), "n"),
             ("Investment", eur(f["capex_total"]), "n")]
    if f["grid_mwh"] > 1:
        items += [("Electricity to the grid", f"{f['grid_mwh'] / 1e3:,.0f}" + u("GWh/yr"), "p"),
                  ("Net cost of electricity", f"€{f['lcoe_net']:,.1f}" + u("/MWh"), "p")]
    if f["h2_kg"] > 1:
        items += [("Hydrogen delivered", f"{f['h2_kg'] / 1e3:,.0f}" + u("t/yr"), "h"),
                  ("Net cost of hydrogen", f"€{f['lcoh_net']:,.2f}" + u("/kg"), "h")]
    if gen > 1:
        items.append(("Generation curtailed", f"{100 * f['curt_mwh'] / gen:,.1f}" + u("%"), "s"))
    theme.kpis(items)
    if f["short_e_mwh"] > 1 or f["short_h_kg"] > 1:
        st.warning(f"Not delivered after the full-year check: {f['short_e_mwh']:,.0f} MWh of electricity and "
                   f"{f['short_h_kg'] / 1e3:,.1f} t of hydrogen. Usually the sea area, deck area or grid capacity "
                   "limits the design; relax one of them and run again.")
    svg_block(island_svg(design_from_result(res), animate=True))
    a, b = st.columns(2)
    with a:
        st.markdown("#### On the island")
        st.dataframe(cap_table(f, CAP_ISLAND), hide_index=True, width="stretch")
    with b:
        st.markdown("#### Links and onshore")
        st.dataframe(cap_table(f, CAP_SHORE), hide_index=True, width="stretch")
        if f["pipe"] != "none":
            st.caption(f"Hydrogen pipeline: {f['pipe'].replace('_', ' ')}, {f['pipe_distance_km']:.0f} km.")
    tabs = st.tabs(["Energy flows", "Hour by hour", "Storage", "Costs and revenues", "TDA check", "Map",
                    "Download"])
    h = res["hourly"]
    with tabs[0]:
        st.plotly_chart(charts.sankey(f, {**d, "cable_eff": P.derive(inp)["cable_eff"]}), width="stretch")
    with tabs[1]:
        day = st.slider("First day of the week shown", 1, 359, 15, key="week_day")
        st.plotly_chart(charts.week(h, day - 1), width="stretch")
        a, b = st.columns(2)
        a.plotly_chart(charts.carpet(h, "p_grid", "Power to the grid", "MW", theme.PALETTE["power"]),
                       width="stretch")
        h2 = {"h2": np.asarray(h["h2_off"]) + np.asarray(h["h2_on"])}
        b.plotly_chart(charts.carpet(h2, "h2", "Hydrogen production", "kg/h", theme.PALETTE["h2_ink"]),
                       width="stretch")
    with tabs[2]:
        st.plotly_chart(charts.storage(h), width="stretch")
    with tabs[3]:
        st.plotly_chart(charts.costs(f), width="stretch")
        rows = [("Total annual cost", f["total_cost"]), ("Electricity revenue", -f["rev_e"]),
                ("Hydrogen revenue", -f["rev_h"]), ("Penalty for undelivered energy", f["penalty"]),
                ("Net annual cost", f["net_cost"])]
        st.dataframe(pd.DataFrame([(k, f"{v / 1e6:,.2f}") for k, v in rows], columns=["item", "M EUR per year"]),
                     hide_index=True, width="stretch")
        st.caption("Investment is annualised with the capital recovery factor of each component's lifetime at the "
                   "discount rate, plus fixed O&M. Revenues are shown negative.")
    with tabs[4]:
        t = res["tda"]
        diff = 100 * (f["net_cost"] - r["net_cost"]) / max(abs(r["total_cost"]), 1.0)
        theme.kpis([("Time steps in the reduced year", f"{t['blocks']:,} blocks", "n"),
                    ("Shape error of the energy balance", f"{100 * t['eps']:.2f} %", "n"),
                    ("Persistent episodes kept exactly", f"{t['n_fixed']:,}", "n"),
                    ("Cost change in the full-year check", f"{diff:+.2f}" + '<span class="u">%</span>', "n")])
        a, b = st.columns(2)
        a.plotly_chart(charts.tda_balance(t["diag"]), width="stretch")
        b.plotly_chart(charts.tda_diagram(t["diag"]), width="stretch")
        sc = res["scale"]
        st.caption(
            f"Series used to place the cuts: {', '.join(t['attrs'])}. Repair factors applied on the full year: "
            f"generation ×{sc['generation']:.3f}, conversion ×{sc['conversion']:.3f}, storage ×{sc['storage']:.3f}. "
            "The persistence diagram lists every deficit episode of the wind balance: a point far from the diagonal "
            "is a long, deep lull. Points of the reduced year sit on those of the full year, so the storage need is "
            "preserved.")
    with tabs[5]:
        site_map(None, height=420)
    with tabs[6]:
        st.download_button("Results workbook (Excel)", report.results_xlsx(res),
                           f"EVOLVE_results_{inp['site_name'][:30].replace(' ', '_')}.xlsx", type="primary")
        st.download_button("Inputs workbook of this run (Excel)", workbook.to_bytes(inp, ss.series, ss.notes),
                           f"EVOLVE_inputs_{inp['site_name'][:30].replace(' ', '_')}.xlsx")
        st.download_button("Drawing of the design (SVG)", island_svg(design_from_result(res), animate=False),
                           "EVOLVE_design.svg", mime="image/svg+xml")
        st.caption("The results workbook holds the summary, capacities, annual costs, the 8,760-hour operation, the "
                   "TDA blocks and every input used.")


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------

def nav_buttons(step):
    i = STEPS.index(step)
    st.write("")
    a, b, _ = st.columns([1, 1, 5])
    if i > 0:
        a.button("Back", on_click=go, args=(STEPS[i - 1],), key=f"back_{step}", width="stretch")
    if i < len(STEPS) - 1:
        b.button(f"Next: {STEPS[i + 1].lower()}", on_click=go, args=(STEPS[i + 1],), type="primary",
                 key=f"next_{step}", width="stretch")


def _keep_nav():
    if not ss.nav:                     # clicking the selected step again would clear it
        ss.nav = ss.get("_last_nav", STEPS[0])


def main():
    sidebar()
    if not ss.started:
        landing()
        return
    if ss.get("_goto"):
        ss.nav = ss.pop("_goto")
    st.segmented_control("Step", STEPS, key="nav", label_visibility="collapsed", on_change=_keep_nav)
    ss._last_nav = ss.nav
    {"Site": step_site, "Use case": step_use, "Data": step_data, "Technologies": step_tech, "Run": step_run,
     "Results": step_results}[ss.nav]()


main()
