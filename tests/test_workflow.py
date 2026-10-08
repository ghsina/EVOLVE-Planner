"""End-to-end check on the Belle-Ile example: the design delivers every contract on the full year."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evolve_planner import params, report, workbook, workflow  # noqa: E402

EX = ROOT / "examples" / "belle_ile"


def _case(name):
    pre = json.loads((EX / "presets.json").read_text())[name]
    user = params.defaults()
    user.update({k: v for k, v in pre.items() if not k.startswith("_")})
    df = pd.read_csv(EX / "timeseries_2019.csv")
    return user, {"wind_cf": df.wind_cf.to_numpy(), "pv_cf": df.pv_cf.to_numpy(), "price": df.price_eur_mwh.to_numpy()}


@pytest.mark.slow
def test_hybrid_delivers_contracts():
    user, series = _case("hybrid_ppa")
    res = workflow.plan(user, series, n_blocks=730)
    f = res["final"]
    assert f["grid_mwh"] == pytest.approx(user["annual_demand_mwh"], rel=1e-4)
    assert f["h2_kg"] == pytest.approx(user["annual_h2_demand_kg"], rel=1e-4)
    assert f["short_e_mwh"] < 1 and f["short_h_kg"] < 1
    assert len(report.results_xlsx(res)) > 10_000


def test_workbook_round_trip(tmp_path):
    user, series = _case("hybrid_ppa")
    p = tmp_path / "w.xlsx"
    p.write_bytes(workbook.to_bytes(user, series))
    u2, s2, _ = workbook.from_file(p)
    assert u2["site_name"] == user["site_name"] and u2["sea_area_km2"] == user["sea_area_km2"]
    assert abs(s2["wind_cf"].mean() - series["wind_cf"].mean()) < 1e-5


def test_series_check_names_missing_price():
    user, series = _case("power_cfd")
    series.pop("price")
    msgs = workflow.check_series(series, params.derive(user))
    assert any("price" in m for m in msgs)
