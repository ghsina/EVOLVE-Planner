"""Animated cross-section of the floating energy island, its export routes and the shore.

`island_svg(design)` returns a self-contained HTML string (SVG + CSS) for
st.components.v1.html. Everything that is drawn comes from the design dict:
built assets are solid and labelled with their size, assets the optimiser did
not build are drawn as faint dashed outlines, so the picture shows the choice.
"""
from __future__ import annotations

from html import escape

import math

POWER = "#E3A72F"      # electricity
H2 = "#3FC1C9"         # hydrogen
STORE = "#8E7CC3"      # storage
INK = "#13232E"
DECK = "#D9E2E7"
STEEL = "#5B6B75"
SEA_TOP = "#1F6F8B"
SEA_DEEP = "#0E2A3B"
LAND = "#E4E8D8"
SKY = "#EEF3F5"


def _fmt(x, unit, nd=0):
    if x is None:
        return "-"
    if unit == "t" and x >= 1000:
        return f"{x / 1000:,.1f} kt"
    return f"{x:,.{nd}f} {unit}"


def _icon(kind, x, y, s=1.0, color=INK):
    """Small line icons drawn at (x, y) = icon centre, nominal size 28."""
    g = f'<g transform="translate({x},{y}) scale({s})" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    if kind == "electrolyser":
        g += ('<rect x="-12" y="-9" width="24" height="18" rx="3"/><line x1="-6" y1="-9" x2="-6" y2="9"/>'
              '<line x1="0" y1="-9" x2="0" y2="9"/><line x1="6" y1="-9" x2="6" y2="9"/>'
              '<circle cx="-3" cy="-14" r="2"/><circle cx="4" cy="-15" r="1.5"/>')
    elif kind == "tank":
        g += '<rect x="-7" y="-12" width="14" height="24" rx="7"/><line x1="-7" y1="-2" x2="7" y2="-2"/>'
    elif kind == "battery":
        g += ('<rect x="-12" y="-7" width="22" height="14" rx="2"/><rect x="10" y="-3" width="3" height="6"/>'
              '<polyline points="-3,-4 -6,1 -1,1 -4,5"/>')
    elif kind == "fuelcell":
        g += ('<rect x="-11" y="-10" width="22" height="20" rx="3"/><path d="M-5 -3 h10 M-5 3 h10"/>'
              '<circle cx="0" cy="0" r="1.2"/>')
    elif kind == "compressor":
        g += '<circle cx="0" cy="0" r="10"/><path d="M-6 6 L6 -6 M2 -6 H6 V-2"/>'
    elif kind == "water":
        g += '<path d="M0 -11 C6 -3 8 1 8 4 A8 8 0 0 1 -8 4 C-8 1 -6 -3 0 -11 Z"/>'
    elif kind == "substation":
        g += ('<path d="M-10 12 L-4 -12 L4 -12 L10 12 M-7 0 H7 M-8.5 6 H8.5 M-4 -12 L4 0 M4 -12 L-4 0"/>')
    elif kind == "converter":
        g += '<rect x="-11" y="-9" width="22" height="18" rx="2"/><path d="M-7 -2 q3 -5 6 0 t6 0 M-7 5 h14"/>'
    elif kind == "inverter":
        g += ('<rect x="-11" y="-10" width="22" height="20" rx="2"/><path d="M-7 -4 h6 M-7 -1 h6"/>'
              '<path d="M1 5 q1.5 -4 3 0 t3 0"/><line x1="-8" y1="8" x2="8" y2="-8"/>')
    elif kind == "factory":
        g += '<path d="M-12 12 V-2 L-5 3 V-2 L2 3 V-10 H8 V12 Z"/><line x1="-12" y1="12" x2="12" y2="12"/>'
    elif kind == "grid":
        g += '<path d="M-12 0 H12 M6 -6 L12 0 L6 6"/>'
    g += "</g>"
    return g


def _module(x, y, w, h, kind, title, value, built, color, compact=False):
    op = 1.0 if built else 0.35
    dash = "" if built else ' stroke-dasharray="4 3"'
    fill = "#FFFFFF" if built else "none"
    out = (f'<g opacity="{op}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" '
           f'stroke="{color}" stroke-width="{1.8 if built else 1.2}"{dash}/>')
    ix, tx = (14, 27) if compact else (18, 34)
    out += _icon(kind, x + ix, y + h / 2, 0.7 if compact else 0.8, color if built else STEEL)
    out += (f'<text x="{x + tx}" y="{y + h / 2 - 3}" class="t-mod">{title}</text>'
            f'<text x="{x + tx}" y="{y + h / 2 + 11}" class="t-val">{value if built else "not built"}</text></g>')
    return out


def _turbine(x, sea_y, height, rotor, floating, depth_px, seabed_y, i, spin=True):
    hub_y = sea_y - height
    out = f'<g class="turbine">'
    # foundation
    if floating:
        out += (f'<rect x="{x - 9}" y="{sea_y - 4}" width="18" height="16" rx="3" fill="{STEEL}"/>'
                f'<path d="M{x - 9} {sea_y + 10} Q {x - 40} {seabed_y - 30} {x - 60} {seabed_y}" class="mooring"/>'
                f'<path d="M{x + 9} {sea_y + 10} Q {x + 40} {seabed_y - 30} {x + 60} {seabed_y}" class="mooring"/>')
    else:
        out += f'<line x1="{x}" y1="{sea_y}" x2="{x}" y2="{seabed_y + 6}" stroke="{STEEL}" stroke-width="5"/>'
    out += (f'<line x1="{x}" y1="{sea_y}" x2="{x}" y2="{hub_y}" stroke="#F7F9FA" stroke-width="3.2"/>'
            f'<line x1="{x}" y1="{sea_y}" x2="{x}" y2="{hub_y}" stroke="#AFBBC2" stroke-width="0.6"/>'
            f'<rect x="{x - 4}" y="{hub_y - 3}" width="10" height="6" rx="2" fill="#F7F9FA" stroke="#AFBBC2" stroke-width="0.6"/>')
    dur = 3.2 + (i % 3) * 0.6
    blades = "".join(
        f'<path d="M0 0 L{rotor * math.sin(math.radians(a)) * 0.08:.1f} {-rotor * math.cos(math.radians(a)) * 0.08:.1f} '
        f'L{rotor * math.sin(math.radians(a)):.1f} {-rotor * math.cos(math.radians(a)):.1f} Z" '
        f'fill="#F7F9FA" stroke="#AFBBC2" stroke-width="0.6"/>' for a in (0, 120, 240))
    anim = f' style="animation-duration:{dur}s"' if spin else ' style="animation:none"'
    out += (f'<g transform="translate({x},{hub_y})"><g class="rotor"{anim}>{blades}'
            f'<circle r="{rotor}" fill="none" stroke="none"/><circle r="2.4" fill="#AFBBC2"/></g></g></g>')
    return out


_N = 0


def island_svg(d: dict, height: int = 560, animate: bool = True, labels: bool = True) -> str:
    """d: design and context, keys (all optional):
    C_wt, C_pv, C_ez_off, C_ez_on, C_cmp_off, C_cmp_on, C_fc_off, C_fc_on, C_cab, E_bat_off, P_bat_off,
    E_bat_on, P_bat_on, E_tank_off, E_tank_on, pipe (class or 'none'), link_mode, floating, depth_m,
    grid_km, pipe_km, turbine_mw, grid_gwh, h2_t, gen_gwh, curt_gwh, grid_name, h2_name, site_name."""
    g = lambda k: float(d.get(k) or 0.0)
    built = lambda k, tol=1e-3: g(k) > tol
    floating = bool(d.get("floating", True))
    W_, H_ = 1320, 560
    sea_y, seabed_y = 205, 470
    land_y = sea_y - 14
    global _N
    _N += 1
    cls = f"isl{_N}"
    sc = "svg." + cls
    out = [f'<svg class="{cls}" viewBox="0 0 {W_} {H_}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Cross-section of the floating energy island, export routes and onshore plant">']
    out.append(f"""<defs>
      <linearGradient id="sea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{SEA_TOP}"/>
        <stop offset="1" stop-color="{SEA_DEEP}"/></linearGradient>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F7FAFB"/>
        <stop offset="1" stop-color="#DCE8EE"/></linearGradient>
      <pattern id="sand" width="10" height="10" patternUnits="userSpaceOnUse">
        <circle cx="2" cy="3" r="0.8" fill="#8E8B78"/><circle cx="7" cy="7" r="0.6" fill="#8E8B78"/></pattern>
    </defs>""")
    # sky, sea, seabed, shore
    out.append(f'<rect width="{W_}" height="{sea_y}" fill="url(#sky)"/>')
    out.append(f'<rect y="{sea_y}" width="{W_}" height="{H_ - sea_y}" fill="url(#sea)"/>')
    bed = (f'M0 {seabed_y} C 300 {seabed_y - 12}, 620 {seabed_y + 10}, 860 {seabed_y - 30} '
           f'C 930 {seabed_y - 60}, 960 {sea_y + 40}, 985 {sea_y} L 1000 {land_y} L {W_} {land_y} '
           f'L {W_} {H_} L 0 {H_} Z')
    out.append(f'<path d="{bed}" fill="#6E6A57"/><path d="{bed}" fill="url(#sand)" opacity="0.5"/>')
    out.append(f'<path d="M985 {sea_y} L 1000 {land_y} L {W_} {land_y} L {W_} {land_y + 10} L 990 {land_y + 10} Z" '
               f'fill="#B9BFA6"/>')
    out.append(f'<rect x="1000" y="{land_y}" width="{W_ - 1000}" height="{sea_y - land_y + 4}" fill="{LAND}"/>')
    # waves
    wave = " ".join(f"q 15 -5 30 0 t 30 0" for _ in range(16))
    out.append(f'<g class="waves"><path d="M-60 {sea_y} {wave}" fill="none" stroke="#9FD3DE" stroke-width="1.4" '
               f'opacity="0.8"/></g>')
    # ---------------- wind farm ----------------
    n_turb = round(g("C_wt") / max(g("turbine_mw") or 15.0, 1e-6))
    n_draw = max(1, min(n_turb if n_turb > 0 else 3, 7))
    xs = [40 + i * 44 for i in range(n_draw)]
    for i, x in enumerate(xs):
        hgt = 104 - (i % 2) * 8
        out.append(f'<g opacity="{1.0 if built("C_wt") else 0.35}">' +
                   _turbine(x, sea_y, hgt, 30 - (i % 2) * 3, floating, 0, seabed_y - 8, i, animate) + "</g>")
    if labels:
        wl = (f"Offshore wind {g('C_wt'):,.0f} MW" if built("C_wt") else "Offshore wind: not built")
        sub = (f"{n_turb} x {g('turbine_mw') or 15:.0f} MW turbines" + (f" ({n_draw} drawn)" if n_turb > n_draw else "")
               + (" on floating foundations" if floating else " on fixed foundations"))
        out.append(f'<text x="30" y="30" class="t-head">{wl}</text><text x="30" y="48" class="t-sub">{sub}</text>')
    # floating PV patch
    pv_on = built("C_pv")
    px0, py0 = 60, sea_y + 2
    panels = "".join(f'<rect x="{px0 + c * 15}" y="{py0 + r * 7}" width="12" height="4" rx="1" '
                     f'fill="#2E4A7A" stroke="#C9D6E8" stroke-width="0.5" transform="skewX(-20)"/>'
                     for r in range(2) for c in range(9))
    out.append(f'<g class="bob" opacity="{1 if pv_on else 0.3}">{panels}</g>')
    if labels:
        out.append(f'<text x="40" y="{sea_y + 34}" class="t-onwater">'
                   f'{"Floating PV " + _fmt(g("C_pv"), "MW") if pv_on else "Floating PV: not built"}</text>')
    # inter-array cable
    if built("C_wt"):
        out.append(f'<path d="M{xs[0]} {seabed_y - 10} L {xs[-1]} {seabed_y - 12} L 380 {seabed_y - 14}" '
                   f'class="flow-p" stroke-width="2"/>')
    # ---------------- island hub ----------------
    hx, hw = 350, 384
    top_y = 66
    float_cls = "bob" if floating else ""
    hub = [f'<g class="{float_cls}">']
    if floating:
        for cx in (hx + 30, hx + hw / 2, hx + hw - 30):
            hub.append(f'<rect x="{cx - 16}" y="{sea_y - 22}" width="32" height="48" rx="6" fill="{STEEL}"/>')
        hub.append(f'<rect x="{hx + 14}" y="{sea_y + 18}" width="{hw - 28}" height="10" rx="4" fill="#4A5961"/>')
        for ax, dx in ((hx + 30, -90), (hx + hw - 30, 90)):
            hub.append(f'<path d="M{ax} {sea_y + 26} Q {ax + dx * 0.5} {seabed_y - 40} {ax + dx} {seabed_y - 4}" class="mooring"/>'
                       f'<rect x="{ax + dx - 5}" y="{seabed_y - 8}" width="10" height="6" fill="#3E474C"/>')
        hub.append(f'<rect x="{hx}" y="{sea_y - 34}" width="{hw}" height="12" fill="#7A8A93"/>')
    else:
        for lx in (hx + 40, hx + hw - 40):
            top_, bot = sea_y - 22, seabed_y - 4
            hub.append(f'<path d="M{lx - 8} {top_} L {lx - 26} {bot} M{lx + 8} {top_} L {lx + 26} {bot}" '
                       f'stroke="{STEEL}" stroke-width="4" fill="none"/>')
            n_b = 5
            for k in range(n_b):
                y1 = top_ + k * (bot - top_) / n_b
                y2 = top_ + (k + 1) * (bot - top_) / n_b
                w1 = 8 + 18 * k / n_b
                w2 = 8 + 18 * (k + 1) / n_b
                hub.append(f'<path d="M{lx - w1} {y1} L {lx + w2} {y2} M{lx + w1} {y1} L {lx - w2} {y2}" '
                           f'stroke="{STEEL}" stroke-width="1.3" fill="none"/>')
        hub.append(f'<rect x="{hx}" y="{sea_y - 34}" width="{hw}" height="12" fill="#7A8A93"/>')
    hub.append(f'<rect x="{hx}" y="{top_y}" width="{hw}" height="{sea_y - 34 - top_y}" rx="4" '
               f'fill="{DECK}" stroke="#AFBBC2"/>')
    cab_on = built("C_cab")
    hvdc = d.get("link_mode") == "HVDC"
    mods = [
        ("converter" if hvdc else "substation", "Converter" if hvdc else "Substation",
         f'{"HVDC" if hvdc else "HVAC"} {g("C_cab"):,.0f} MW', cab_on, POWER),
        ("inverter", "Inverters", _fmt(g("C_pv"), "MW"), built("C_pv"), POWER),
        ("battery", "Battery", f"{g('E_bat_off'):,.0f} MWh", built("E_bat_off"), STORE),
        ("electrolyser", "Electrolyser", _fmt(g("C_ez_off"), "MW"), built("C_ez_off"), H2),
        ("water", "Desalination", "for electrolysis", built("C_ez_off"), H2),
        ("compressor", "Compressor", _fmt(g("C_cmp_off"), "MW", 1), built("C_cmp_off"), H2),
        ("tank", "H2 tank", _fmt(g("E_tank_off") / 1000, "t"), built("E_tank_off", 1.0), STORE),
        ("fuelcell", "Fuel cell", _fmt(g("C_fc_off"), "MW"), built("C_fc_off"), POWER),
    ]
    mw, mh = (hw - 18 - 12) / 3, 32
    for i, (k, t, v, b, c) in enumerate(mods):
        mx = hx + 9 + (i % 3) * (mw + 6)
        my = top_y + 6 + (i // 3) * (mh + 3)
        hub.append(_module(mx, my, mw, mh, k, t, v, b, c, compact=True))
    hub.append("</g>")
    out.append("".join(hub))
    sub_kind = "converter" if d.get("link_mode") == "HVDC" else "substation"
    if labels:
        cfg = "Floating island" if floating else "Bottom-fixed island"
        out.append(f'<text x="{hx}" y="30" class="t-head">{cfg}</text>'
                   f'<text x="{hx}" y="48" class="t-sub">{escape(str(d.get("site_name", "")))}  |  water depth '
                   f'{g("depth_m"):.0f} m</text>')
    # ---------------- export routes along the seabed ----------------
    cab = built("C_cab")
    pipe = d.get("pipe", "none") not in (None, "", "none")
    cw = 2.5 + min(g("C_cab") / 60.0, 7.0)
    route_c = (f'M{hx + hw - 40} {sea_y + 20} L {hx + hw - 40} {seabed_y - 22} C 800 {seabed_y - 26}, '
               f'900 {seabed_y - 60}, 960 {sea_y + 30} L 1010 {land_y + 4} L 1080 {land_y + 4} L 1080 {land_y - 6}')
    route_p = (f'M{hx + hw - 70} {sea_y + 20} L {hx + hw - 70} {seabed_y - 10} C 800 {seabed_y - 12}, '
               f'915 {seabed_y - 48}, 975 {sea_y + 34} L 1020 {land_y + 8} L 1240 {land_y + 8} L 1240 {land_y - 6}')
    out.append(f'<path d="{route_c}" fill="none" stroke="#2A3A44" stroke-width="{cw + 3}" opacity="{1 if cab else 0.3}"/>')
    out.append(f'<path d="{route_c}" class="{"flow-p" if cab else "ghost"}" stroke-width="{cw}"/>')
    out.append(f'<path d="{route_p}" fill="none" stroke="#2A3A44" stroke-width="7" opacity="{1 if pipe else 0.3}"/>')
    out.append(f'<path d="{route_p}" class="{"flow-h" if pipe else "ghost"}" stroke-width="4"/>')
    if labels:
        ctext = (f'{d.get("link_mode", "HVAC")} export cable {g("C_cab"):,.0f} MW, {g("grid_km"):,.0f} km'
                 if cab else "No export cable")
        ptext = (f'H2 pipeline ({str(d.get("pipe")).replace("_", " ")}), {g("pipe_km"):,.0f} km'
                 if pipe else "No hydrogen pipeline")
        out.append(f'<text x="{hx + hw - 84}" y="{seabed_y - 38}" text-anchor="end" class="t-sea">{ctext}</text>'
                   f'<text x="{hx + hw - 84}" y="{seabed_y + 18}" text-anchor="end" class="t-sea">{ptext}</text>')
    # ---------------- onshore ----------------
    ox = 1000
    on = [
        (sub_kind, "HVDC converter" if sub_kind == "converter" else "Substation",
         _fmt(g("C_cab"), "MW") if cab else "", cab, POWER),
        ("electrolyser", "Electrolyser", _fmt(g("C_ez_on"), "MW"), built("C_ez_on"), H2),
        ("compressor", "Compressor", _fmt(g("C_cmp_on"), "MW", 1), built("C_cmp_on"), H2),
        ("tank", "H2 tank", _fmt(g("E_tank_on") / 1000, "t"), built("E_tank_on", 1.0), STORE),
        ("battery", "Battery", f"{g('E_bat_on'):,.0f} MWh / {g('P_bat_on'):,.0f} MW", built("E_bat_on"), STORE),
        ("fuelcell", "Fuel cell", _fmt(g("C_fc_on"), "MW"), built("C_fc_on"), POWER),
    ]
    out.append(f'<rect x="{ox}" y="{top_y}" width="{W_ - ox - 12}" height="{land_y - top_y}" rx="4" '
               f'fill="#F4F6EE" stroke="#C9CFB8"/>')
    for i, (k, t, v, b, c) in enumerate(on):
        out.append(_module(ox + 8 + (i % 2) * 152, top_y + 6 + (i // 2) * 36, 144, 32, k, t, v, b, c))
    if labels:
        sub = (f'<tspan fill="{POWER}" font-weight="600">Grid {g("grid_gwh"):,.0f} GWh/yr</tspan>'
               f'<tspan dx="14" fill="#1E8C93" font-weight="600">H2 {g("h2_t"):,.0f} t/yr</tspan>'
               if d.get("grid_gwh") is not None else 'Onshore plant and grid connection')
        out.append(f'<text x="{ox}" y="30" class="t-head">Onshore</text>'
                   f'<text x="{ox}" y="48" class="t-sub">{sub}</text>')
    # legend
    out.append(f'<g transform="translate(40,{H_ - 22})" class="t-leg">'
               f'<line x1="0" y1="-4" x2="22" y2="-4" stroke="{POWER}" stroke-width="3"/><text x="28" y="0">electricity</text>'
               f'<line x1="110" y1="-4" x2="132" y2="-4" stroke="{H2}" stroke-width="3"/><text x="138" y="0">hydrogen</text>'
               f'<rect x="222" y="-10" width="12" height="12" fill="none" stroke="{STORE}" stroke-width="1.8"/>'
               f'<text x="240" y="0">storage</text>'
               f'<rect x="312" y="-10" width="12" height="12" fill="none" stroke="#C9D3D8" stroke-dasharray="3 2"/>'
               f'<text x="330" y="0">option not chosen by the optimiser</text>'
               f'<text x="1120" y="0" opacity="0.8">Schematic, not to scale</text></g>')
    out.append("</svg>")
    css = f"""<style>
      {sc} {{ width:100%; height:auto; display:block; font-family:'IBM Plex Sans', system-ui, sans-serif; }}
      {sc} .t-head {{ font: 600 17px 'Archivo', 'IBM Plex Sans', sans-serif; fill:{INK}; }}
      {sc} .t-sub {{ font: 400 12.5px 'IBM Plex Sans', sans-serif; fill:#4B5B65; }}
      {sc} .t-mod {{ font: 600 11.5px 'IBM Plex Sans', sans-serif; fill:{INK}; }}
      {sc} .t-val {{ font: 400 11px 'IBM Plex Sans', sans-serif; fill:#3A4A54; font-variant-numeric: tabular-nums; }}
      {sc} .t-sea {{ font: 500 12px 'IBM Plex Sans', sans-serif; fill:#E8F1F4; }}
      {sc} .t-onwater {{ font: 500 11.5px 'IBM Plex Sans', sans-serif; fill:#E8F1F4; }}
      {sc} .t-flow {{ font: 600 12px 'IBM Plex Sans', sans-serif; }}
      {sc} .t-leg text {{ font: 400 11.5px 'IBM Plex Sans', sans-serif; fill:#E8F1F4; }}
      {sc} .mooring {{ fill:none; stroke:#A9B4BA; stroke-width:1; opacity:0.7; }}
      {sc} .flow-p {{ fill:none; stroke:{POWER}; stroke-dasharray:10 8; stroke-linecap:round; animation: isl-dash 1.6s linear infinite; }}
      {sc} .flow-h {{ fill:none; stroke:{H2}; stroke-dasharray:10 8; stroke-linecap:round; animation: isl-dash 2.2s linear infinite; }}
      {sc} .ghost {{ fill:none; stroke:#7D8C95; stroke-dasharray:4 6; opacity:0.5; }}
      {sc} .rotor {{ animation: isl-spin linear infinite; transform-box: fill-box; transform-origin: center; }}
      {sc} .waves {{ animation: isl-drift 9s linear infinite; }}
      {sc} .bob {{ animation: isl-bob 5s ease-in-out infinite; }}
      @keyframes isl-dash {{ to {{ stroke-dashoffset: -36; }} }}
      @keyframes isl-spin {{ to {{ transform: rotate(360deg); }} }}
      @keyframes isl-drift {{ to {{ transform: translateX(60px); }} }}
      @keyframes isl-bob {{ 50% {{ transform: translateY(2px); }} }}
      @media (prefers-reduced-motion: reduce) {{ {sc} .flow-p, {sc} .flow-h, {sc} .rotor, {sc} .waves, {sc} .bob {{ animation:none; }} }}
      {'' if animate else sc + ' .flow-p,' + sc + ' .flow-h,' + sc + ' .rotor,' + sc + ' .waves,' + sc + ' .bob{animation:none}'}
    </style>"""
    fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@87,500;87,600;87,700&'
             'family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">')
    return fonts + css + "".join(out)


def design_from_result(res: dict) -> dict:
    f, inp, der = res["final"], res["inputs"], res["derived"]
    return {**{k: f[k] for k in ("C_wt", "C_pv", "C_ez_off", "C_ez_on", "C_cmp_off", "C_cmp_on", "C_fc_off",
                                 "C_fc_on", "C_cab", "E_bat_off", "P_bat_off", "E_bat_on", "P_bat_on",
                                 "E_tank_off", "E_tank_on")},
            "pipe": f["pipe"], "link_mode": f["link_mode"], "floating": der["floating"],
            "depth_m": inp.get("avg_water_depth_m"), "grid_km": der["grid_distance_km"],
            "pipe_km": der["pipe_distance_km"], "turbine_mw": inp.get("turbine_mw", 15.0),
            "grid_gwh": f["grid_mwh"] / 1000, "h2_t": f["h2_kg"] / 1000, "site_name": inp.get("site_name", ""),
            "grid_name": inp.get("grid_name", "Grid point"), "h2_name": inp.get("h2_name", "")}


DEMO = {"C_wt": 105, "C_pv": 40, "C_ez_off": 20, "C_ez_on": 15, "C_cmp_off": 0.5, "C_cmp_on": 0.2, "C_fc_off": 0,
        "C_fc_on": 20, "C_cab": 60, "E_bat_off": 0, "E_bat_on": 40, "P_bat_on": 10, "E_tank_off": 30000,
        "E_tank_on": 150000, "pipe": "new_small_12in", "link_mode": "HVAC", "floating": True, "depth_m": 75,
        "grid_km": 55, "pipe_km": 60, "turbine_mw": 15, "grid_gwh": 200, "h2_t": 2000,
        "site_name": "Example site", "grid_name": "Grid substation"}
